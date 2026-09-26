"""
Medpark Meeting Intelligence System - Speaker Attribution Endpoints

Reviewer-facing view of the diarization clusters of one meeting and the ONLY write path that puts a person's
name on transcript segments. A voiceprint match is a question ("Is this X?"), never an answer: the cluster
becomes confirmed/corrected exclusively through POST .../{cluster_id}/confirm, bound to the meeting revision,
audited in the speaker map, and refused (409) whenever the cluster's own diagnostics say it cannot be trusted
in bulk. Names never reach segment.speaker (the anonymous label the LLM sees) and never reach a segment with
less than SPEAKER_MIN_PRINTABLE_SPEECH_S of speech (printable_name / display_speaker).

Besides confirming an enrolled voiceprint match, a reviewer may assign a LABEL to a cluster (action "label"):
a meeting attendee or guest picked from the roster, or a typed name. It is stored as a correction with no
Person behind it (attribution_basis "reviewer_label") and follows exactly the same printable floor, evidence
and owner rules as a confirmed name; no voiceprint is created.
"""

import re
from datetime import datetime, timezone
from typing import Literal, Optional, get_args

import numpy as np
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.logging import logger
from app.models.extraction import MinutesOfMeeting
from app.models.meeting import Meeting, ReviewStatus
from app.models.person import Person, SpeakerAttributionEvent, SpeakerMap
from app.models.transcript import AttributionState, MatchBand, SpeakerSuggestion, Transcript, TranscriptSegment
from app.services.diarization.embedder import cosine, speaker_embedder
from app.services.diarization.matching import Candidate, VoiceprintRef, collect_voiceprints, pick_suggestion, score_vector
from app.services.diarization.speaker_engine import STRADDLE_FLAG_REASON, cluster_label, load_cached_embeddings
from app.services.documents.generator import document_generator
from app.storage.file_manager import file_manager
from app.storage.repository import repository

router = APIRouter(prefix="/meetings/{meeting_id}/speakers", tags=["Speaker Attribution"])

MAX_SAMPLE_TURNS = 5
ConfirmAction = Literal["confirm", "correct", "reject", "unknown", "label"]
# Reviewer labels must be real names: an anonymous cluster label ("Speaker 3") or a prose token ("S3") assigned
# as a "name" would print as an identity while meaning nothing.
LABEL_MIN_CHARS = 2
LABEL_MAX_CHARS = 60
RESERVED_LABEL_PATTERN = re.compile(r"^(Speaker \d+|S\d+)$", re.IGNORECASE)
# Audit actions the SpeakerAttributionEvent model accepts; a label decision is recorded as "label" once the
# model lists it and as a "correct" otherwise (the event still carries person_id None + the label snapshot).
_EVENT_ACTIONS: tuple[str, ...] = get_args(SpeakerAttributionEvent.model_fields["action"].annotation)


# ---------------------------------------------------------------- API models
class ClusterSampleTurn(BaseModel):
    segment_id: str
    start: float
    end: float
    text: str
    speech_seconds: float


class LabelOption(BaseModel):
    """A meeting attendee or guest the reviewer may assign to a cluster as its printed name (no voiceprint involved)."""
    id: str
    name: str
    role: str
    is_guest: bool


class SpeakerCluster(BaseModel):
    cluster_id: str
    display_label: str = Field(..., description="Anonymous label, e.g. 'Speaker 2'")
    total_speech_seconds: float
    turn_count: int
    state: AttributionState
    suggested_profile_id: Optional[str] = None
    suggested_name: Optional[str] = None
    match_score: Optional[float] = Field(None, description="Cosine similarity, not a probability")
    match_band: Optional[MatchBand] = None
    confirmed_profile_id: Optional[str] = None
    confirmed_name: Optional[str] = None
    confirmed_for_revision: Optional[int] = None
    current_label: Optional[str] = Field(None, description="Reviewer-assigned label when the cluster's name has no voiceprint behind it")
    label_options: list[LabelOption] = Field(default_factory=list, description="Meeting attendees and guests offered for action 'label'")
    sample_turns: list[ClusterSampleTurn] = Field(
        default_factory=list, description="The LOWEST-scoring turns against the candidate/confirmed voiceprint, never the longest"
    )
    sampled_seconds: float = 0.0
    printable_turns: int = 0
    unprintable_turns: int = 0
    blocking_reasons: list[str] = Field(default_factory=list)
    merge_suggestion_with: list[str] = Field(default_factory=list)


class SpeakersResponse(BaseModel):
    clusters: list[SpeakerCluster]
    embedder_available: bool
    space_id: Optional[str]
    enrolled_people: int
    current_revision: int
    warnings: list[str] = Field(default_factory=list)


class SpeakerDecisionRequest(BaseModel):
    action: ConfirmAction
    profile_id: Optional[str] = None
    # action "label": a typed name, or the id of a meeting attendee/guest whose name becomes the label
    display_label: Optional[str] = Field(None, description=f"Typed label, {LABEL_MIN_CHARS}-{LABEL_MAX_CHARS} chars, not an anonymous label")
    attendee_id: Optional[str] = Field(None, description="Meeting.attendees[].id (roster people and client-side guests)")
    expected_revision: int
    reviewer_name: str = Field(..., min_length=1, max_length=200)
    reviewer_role: str = "Reviewer"


# ---------------------------------------------------------------- shared context
class _Context:
    """Everything the read and write paths need about one meeting, loaded once."""

    def __init__(self, meeting_id: str):
        self.meeting = repository.get_meeting(meeting_id)
        if not self.meeting:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
        self.transcript = repository.get_transcript(meeting_id)
        if not self.transcript:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transcript not found for this meeting")
        self.warnings: list[str] = []
        self.embedder_available = bool(settings.VOICE_ID_ENABLED and speaker_embedder.available)
        self.space_id = speaker_embedder.space_id if self.embedder_available else None
        if not settings.VOICE_ID_ENABLED:
            self.warnings.append("Voice identification is disabled (VOICE_ID_ENABLED=false); clusters stay anonymous.")
        elif not speaker_embedder.available:
            self.warnings.append(f"Speaker embedder unavailable: {speaker_embedder.load_error}")
        try:
            self.people: list[Person] = repository.list_people()
        except Exception as exc:
            logger.warning(f"Could not load people for speaker view: {exc}")
            self.people = []
            self.warnings.append("Enrolled people could not be loaded; no suggestions are possible.")
        self.enrolled_people = sum(1 for p in self.people if p.enrollment_state(self.space_id) == "enrolled")
        self.refs, skipped = collect_voiceprints(self.people, self.space_id) if self.space_id else ([], [])
        self.warnings.extend(skipped)
        self.cache = load_cached_embeddings(meeting_id)
        self.cache_matches_space = bool(self.cache and self.space_id and self.cache[1].get("space_id") == self.space_id)
        if self.cache is None:
            self.warnings.append("No cached segment embeddings for this meeting: re-matching and turn sampling are unavailable until it is re-processed.")
        elif self.space_id and not self.cache_matches_space:
            self.warnings.append("Cached segment embeddings were produced by another embedder model; re-process the meeting before re-matching.")
        self.row_index: dict[str, int] = {}
        if self.cache is not None:
            self.row_index = {seg_id: i for i, seg_id in enumerate(self.cache[1].get("segment_ids", []))}
        self._grouped = self._group_segments()
        self.label_options = build_label_options(self.meeting)

    # -- lookups
    def _group_segments(self) -> dict[str, list[TranscriptSegment]]:
        """
        Cluster membership is the diarizer's cluster_id AND the label it stands for. A segment whose 'speaker'
        a reviewer moved to another label (PUT /transcript/segments) is that reviewer's explicit correction of a
        diarization error: it leaves its cluster, so a later bulk decision on the cluster cannot override it or
        make the cluster carry a second label. Such segments are counted once into the warnings.
        """
        grouped: dict[str, list[TranscriptSegment]] = {}
        relabelled: list[TranscriptSegment] = []
        for seg in sorted(self.transcript.segments, key=lambda s: (s.start, s.end)):
            if not seg.cluster_id:
                continue
            label = cluster_label(seg.cluster_id)
            if label is None:
                relabelled.append(seg)
            elif seg.speaker == label:
                grouped.setdefault(seg.cluster_id, []).append(seg)
            else:
                relabelled.append(seg)
        if relabelled:
            self.warnings.append(
                f"{len(relabelled)} segment(s) were relabelled by a reviewer and are not part of any cluster; "
                "they keep their anonymous label."
            )
            named = [seg for seg in relabelled if seg.attribution_state in ("confirmed", "corrected")]
            if named:
                self.warnings.append(
                    f"{len(named)} relabelled segment(s) still carry a confirmed name from their former cluster; "
                    "reject that cluster or re-process the meeting to clear it."
                )
        return grouped

    def clusters(self) -> dict[str, list[TranscriptSegment]]:
        return self._grouped

    def person_vector(self, person_id: str) -> Optional[np.ndarray]:
        """Mean of the person's active voiceprints in the active space (None when nothing is loadable)."""
        vectors = [vec for ref, vec in self.refs if ref.person_id == person_id]
        if not vectors:
            return None
        mean = np.mean(np.stack(vectors, axis=0), axis=0)
        norm = float(np.linalg.norm(mean))
        return mean / (norm if norm > 1e-12 else 1.0)

    def segment_vector(self, seg: TranscriptSegment) -> Optional[np.ndarray]:
        if self.cache is None or seg.id not in self.row_index:
            return None
        return self.cache[0][self.row_index[seg.id]]

    def cluster_centroid(self, segs: list[TranscriptSegment]) -> Optional[np.ndarray]:
        """Speech-weighted mean of the cluster's cached segment embeddings."""
        rows, weights = [], []
        for seg in segs:
            vec = self.segment_vector(seg)
            if vec is not None:
                rows.append(vec)
                weights.append(max(seg.speech_seconds or 0.0, 1e-3))
        if not rows:
            return None
        w = np.asarray(weights, dtype=np.float64)[:, None]
        mean = (np.stack(rows, axis=0).astype(np.float64) * w).sum(axis=0) / w.sum()
        norm = float(np.linalg.norm(mean))
        return mean / (norm if norm > 1e-12 else 1.0)

    def cluster_state(self, segs: list[TranscriptSegment]) -> AttributionState:
        states = {seg.attribution_state for seg in segs}
        for candidate in ("corrected", "confirmed", "suggested"):
            if candidate in states:
                return candidate  # type: ignore[return-value]
        return "anonymous"

    def effective_person(self, segs: list[TranscriptSegment]) -> Optional[str]:
        """Person id a cluster is confirmed to, or suggested to be; None when anonymous."""
        for seg in segs:
            if seg.speaker_id:
                return seg.speaker_id
        for seg in segs:
            if seg.suggestion:
                return seg.suggestion.person_id
        return None

    def blocking_reasons(self, cluster_id: str, segs: list[TranscriptSegment]) -> list[str]:
        reasons: list[str] = []
        if self.cache is None:
            reasons.append("Cluster diagnostics are unavailable (no cached embeddings for this meeting); re-process the meeting before confirming.")
        else:
            diag = (self.cache[1].get("clusters") or {}).get(cluster_id)
            if diag is None:
                reasons.append(f"Cluster diagnostics are missing for {cluster_id}; re-process the meeting before confirming.")
            else:
                reasons.extend(str(r) for r in diag.get("reasons", []))
                if diag.get("mixed_suspect") and not any("two voices" in r for r in reasons):
                    reasons.append("This cluster may contain two voices; it cannot be confirmed in bulk.")
                if diag.get("short_suspect") and not any("distinct speech region" in r for r in reasons):
                    reasons.append("Fewer than 3 distinct speech regions in this cluster; too little evidence to confirm in bulk.")
        straddling = sum(1 for seg in segs if seg.is_flagged and seg.flag_reason and STRADDLE_FLAG_REASON in seg.flag_reason)
        if straddling:
            reasons.append(
                f"{straddling} segment(s) in this cluster straddle a speaker change; review them in the transcript "
                "(clear the flag once corrected) before confirming this cluster."
            )
        return reasons

    def build_cluster(self, cluster_id: str, segs: list[TranscriptSegment], all_clusters: dict[str, list[TranscriptSegment]]) -> SpeakerCluster:
        state = self.cluster_state(segs)
        suggestion = next((seg.suggestion for seg in segs if seg.suggestion), None)
        confirmed_id = next((seg.speaker_id for seg in segs if seg.speaker_id), None)
        confirmed_name = next((seg.confirmed_display_name for seg in segs if seg.confirmed_display_name), None)
        confirmed_rev = next((seg.confirmed_for_revision for seg in segs if seg.confirmed_for_revision is not None), None)
        current_label = next(
            (seg.confirmed_display_name for seg in segs
             if seg.attribution_state == "corrected" and seg.attribution_basis == "reviewer_label" and seg.confirmed_display_name),
            None,
        )

        # Reference for turn sampling: confirmed person's voiceprint, else the candidate's, else the cluster's own centroid
        reference: Optional[np.ndarray] = None
        if confirmed_id:
            reference = self.person_vector(confirmed_id)
        elif suggestion:
            reference = self.person_vector(suggestion.person_id)
        centroid = self.cluster_centroid(segs)
        if reference is None:
            reference = centroid

        match_score: Optional[float] = None
        match_band: Optional[MatchBand] = None
        if state == "suggested" and suggestion:
            match_score, match_band = suggestion.score, suggestion.band
        elif confirmed_id and centroid is not None:
            vec = self.person_vector(confirmed_id)
            if vec is not None:
                cand = score_vector(centroid, [(VoiceprintRef(person_id=confirmed_id, person_name=confirmed_name or "", voiceprint_id="", space_id=self.space_id or ""), vec)])
                if cand:
                    match_score, match_band = cand[0].score, cand[0].band

        scored: list[tuple[float, TranscriptSegment]] = []
        if reference is not None:
            for seg in segs:
                vec = self.segment_vector(seg)
                if vec is not None:
                    scored.append((cosine(vec, reference), seg))
        scored.sort(key=lambda item: (item[0], item[1].start))
        sample_turns = [
            ClusterSampleTurn(segment_id=seg.id, start=seg.start, end=seg.end, text=seg.display_text, speech_seconds=seg.speech_seconds or 0.0)
            for _, seg in scored[:MAX_SAMPLE_TURNS]
        ]

        min_printable = settings.SPEAKER_MIN_PRINTABLE_SPEECH_S
        printable = sum(1 for seg in segs if (seg.speech_seconds or 0.0) >= min_printable)
        mine = self.effective_person(segs)
        merge_with = [
            other for other, other_segs in all_clusters.items()
            if other != cluster_id and mine is not None and self.effective_person(other_segs) == mine
        ]
        return SpeakerCluster(
            cluster_id=cluster_id,
            display_label=cluster_label(cluster_id) or segs[0].speaker,
            total_speech_seconds=round(sum(seg.speech_seconds or 0.0 for seg in segs), 2),
            turn_count=len(segs),
            state=state,
            suggested_profile_id=suggestion.person_id if suggestion else None,
            suggested_name=suggestion.person_name if suggestion else None,
            match_score=match_score,
            match_band=match_band,
            confirmed_profile_id=confirmed_id,
            confirmed_name=confirmed_name,
            confirmed_for_revision=confirmed_rev,
            current_label=current_label,
            label_options=self.label_options,
            sample_turns=sample_turns,
            sampled_seconds=round(sum(t.end - t.start for t in sample_turns), 2),
            printable_turns=printable,
            unprintable_turns=len(segs) - printable,
            blocking_reasons=self.blocking_reasons(cluster_id, segs),
            merge_suggestion_with=merge_with,
        )

    def response(self) -> SpeakersResponse:
        grouped = self.clusters()
        clusters = [self.build_cluster(cid, segs, grouped) for cid, segs in sorted(grouped.items())]
        if not clusters:
            self.warnings.append("This transcript has no speaker clusters (processed before embedding diarization or without the embedder).")
        return SpeakersResponse(
            clusters=clusters,
            embedder_available=self.embedder_available,
            space_id=self.space_id,
            enrolled_people=self.enrolled_people,
            current_revision=self.meeting.current_revision,
            warnings=self.warnings,
        )


# ---------------------------------------------------------------- label helpers
def build_label_options(meeting: Meeting) -> list[LabelOption]:
    """Every meeting attendee as a label candidate; guests are the client-side entries with no Person record."""
    return [
        LabelOption(
            id=att.id, name=att.name, role=att.role,
            is_guest=att.id.startswith("guest_") or "guest" in (att.role or "").lower(),
        )
        for att in meeting.attendees
    ]


def validate_label(candidate: Optional[str]) -> str:
    """The trimmed label, or HTTP 400 when it is empty, too short/long, or an anonymous label in disguise."""
    label = (candidate or "").strip()
    if not (LABEL_MIN_CHARS <= len(label) <= LABEL_MAX_CHARS):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"display_label must be {LABEL_MIN_CHARS}-{LABEL_MAX_CHARS} characters after trimming",
        )
    if RESERVED_LABEL_PATTERN.match(label):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"'{label}' is an anonymous speaker label, not a name; type the person's name or pick an attendee",
        )
    return label


def resolve_label(payload: SpeakerDecisionRequest, meeting: Meeting) -> str:
    """
    The name action 'label' will put on the cluster: an attendee/guest of the meeting when attendee_id is given
    (the roster is the only source of that name), otherwise the typed display_label. Validated either way.
    """
    if payload.attendee_id:
        attendee = next((att for att in meeting.attendees if att.id == payload.attendee_id), None)
        if attendee is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attendee not found on this meeting")
        return validate_label(attendee.name)
    if payload.display_label is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="action 'label' requires display_label or attendee_id")
    return validate_label(payload.display_label)


# ---------------------------------------------------------------- write helpers
def _set_suggestion(segs: list[TranscriptSegment], pick: Optional[Candidate], space_id: str) -> None:
    """Suggestion or anonymity on every segment of an unconfirmed cluster; never touches confirmed ones."""
    for seg in segs:
        if seg.attribution_state in ("confirmed", "corrected"):
            continue
        if pick is None:
            seg.suggestion = None
            seg.suggested_identity = None
            seg.attribution_state = "anonymous"
        else:
            seg.suggestion = SpeakerSuggestion(
                person_id=pick.person_id, person_name=pick.person_name, score=pick.score,
                margin=pick.margin, band=pick.band, space_id=space_id,
            )
            seg.suggested_identity = pick.person_name
            seg.attribution_state = "suggested"


def _apply_decision_to_segments(
    segs: list[TranscriptSegment], action: ConfirmAction, person: Optional[Person], reviewer: str, now: datetime, revision: int,
    label: Optional[str] = None,
) -> None:
    """
    Writes the attribution state; printable_name is derived from speech_seconds exactly as V3 defines it.
    A confirmed person and a reviewer label take the same path: the only difference is what stands behind the
    name (speaker_id + basis 'voiceprint' vs. no Person + basis 'reviewer_label'). reject/unknown clear both.
    """
    min_printable = settings.SPEAKER_MIN_PRINTABLE_SPEECH_S
    if action in ("confirm", "correct") and person is not None:
        name, person_id, basis = person.full_name, person.id, "voiceprint"
    elif action == "label" and label:
        name, person_id, basis = label, None, "reviewer_label"
    else:
        name = None
    for seg in segs:
        seg.suggestion = None
        seg.suggested_identity = None
        if name is not None:
            seg.attribution_state = "confirmed" if action == "confirm" else "corrected"
            seg.speaker_id = person_id
            seg.attribution_basis = basis
            seg.confirmed_display_name = name
            seg.confirmed_by = reviewer
            seg.confirmed_at = now
            seg.confirmed_for_revision = revision
            seg.printable_name = (seg.speech_seconds or 0.0) >= min_printable
        else:
            seg.attribution_state = "anonymous"
            seg.speaker_id = None
            seg.attribution_basis = "voiceprint"
            seg.confirmed_display_name = None
            seg.confirmed_by = None
            seg.confirmed_at = None
            seg.confirmed_for_revision = None
            seg.printable_name = False


def _apply_attribution_to_minutes(
    minutes: MinutesOfMeeting, transcript: Transcript, segs: list[TranscriptSegment], display_label: str
) -> None:
    """
    Evidence quotes carry the confirmed name only for printable segments; action items owned by this cluster's
    anonymous label become owned by the confirmed name only when every evidence segment is printable and in the
    cluster. Rejecting reverses both. Free text (summaries, decisions) is never touched: stored prose carries
    anonymous S<n> tokens at most, and the render layer resolves them from the transcript at read time.

    An action item belongs to this decision only through its EVIDENCE: every cited segment must lie in this
    cluster. Neither the owner name nor the label identifies the cluster (the same person may be confirmed on
    several clusters, two people may share a name), so an item attributed through another cluster is never
    touched here, and a reverted item takes back the anonymous label of the segments it cites.
    """
    seg_by_id = {seg.id: seg for seg in transcript.segments}
    cluster_ids = {seg.id for seg in segs}
    new_name = next((seg.confirmed_display_name for seg in segs if seg.confirmed_display_name), None)
    items = list(minutes.decisions) + list(minutes.action_items) + list(minutes.risks_and_questions)
    for item in items:
        for quote in item.evidence:
            seg = seg_by_id.get(quote.segment_id)
            if seg is None or seg.id not in cluster_ids:
                continue
            if seg.printable_name and seg.confirmed_display_name:
                quote.speaker = seg.confirmed_display_name
                quote.speaker_person_id = seg.speaker_id
                quote.speaker_is_confirmed = True
            else:
                quote.speaker = seg.speaker
                quote.speaker_person_id = None
                quote.speaker_is_confirmed = False
    for action in minutes.action_items:
        evidence_segs = [seg_by_id.get(q.segment_id) for q in action.evidence]
        evidence_in_cluster = bool(evidence_segs) and all(seg is not None and seg.id in cluster_ids for seg in evidence_segs)
        if not evidence_in_cluster:
            continue
        # Only "confirmed_speaker" owners are ever written by this handler, and with all evidence inside this
        # cluster only a decision on THIS cluster can have written it; anonymous owners must name this cluster.
        tied = action.owner_source == "confirmed_speaker" or (action.owner_source == "speaker" and action.owner == display_label)
        if not tied:
            continue
        if new_name and all(seg.printable_name for seg in evidence_segs):
            action.owner = new_name
            action.owner_source = "confirmed_speaker"
        else:
            action.owner = evidence_segs[0].speaker
            action.owner_source = "speaker"


def _rejected_people(speaker_map: Optional[SpeakerMap]) -> dict[str, set[str]]:
    """Per cluster, the people a reviewer explicitly rejected (reject events record the suggestion they turned down)."""
    rejected: dict[str, set[str]] = {}
    for event in (speaker_map.events if speaker_map else []):
        if event.action == "reject" and event.person_id:
            rejected.setdefault(event.cluster_id, set()).add(event.person_id)
    return rejected


def _bump_revision_if_signed_off(meeting: Meeting, minutes: MinutesOfMeeting) -> None:
    """Approved or delivered minutes get a new revision (approval invalidated); otherwise the current one is redrawn in place."""
    delivered_current = any(rec.revision == meeting.current_revision for rec in repository.list_deliveries(meeting.id))
    if meeting.review_status in (ReviewStatus.APPROVED, ReviewStatus.DELIVERED) or delivered_current:
        meeting.current_revision += 1
        minutes.revision = meeting.current_revision
        meeting.review_status = ReviewStatus.PENDING_REVIEW
        meeting.approved_by = None
        meeting.approved_at = None


# ---------------------------------------------------------------- endpoints
@router.get("", response_model=SpeakersResponse)
def get_speakers(meeting_id: str) -> SpeakersResponse:
    """Clusters of a meeting with their attribution state, sampling turns and confirmation blockers."""
    return _Context(meeting_id).response()


@router.post("/rematch", response_model=SpeakersResponse)
def rematch_speakers(meeting_id: str) -> SpeakersResponse:
    """Re-scores unconfirmed clusters against the current voiceprints from the cached embeddings (no audio re-run)."""
    with repository.lock:
        ctx = _Context(meeting_id)
        if ctx.cache is None or not ctx.space_id:
            ctx.warnings.append("Re-matching skipped: no usable embedding cache or no embedder.")
            return ctx.response()
        if not ctx.cache_matches_space:
            ctx.warnings.append("Re-matching skipped: the cache belongs to another embedder model.")
            return ctx.response()
        rejected = _rejected_people(repository.get_speaker_map(meeting_id))
        changed = 0
        for cluster_id, segs in ctx.clusters().items():
            if ctx.cluster_state(segs) in ("confirmed", "corrected"):
                continue
            centroid = ctx.cluster_centroid(segs)
            pick = None
            if centroid is not None and ctx.refs:
                # A person a reviewer already rejected on this cluster is not asked about again
                candidates = [c for c in score_vector(centroid, ctx.refs) if c.person_id not in rejected.get(cluster_id, set())]
                pick = pick_suggestion(candidates)
            before = [(seg.attribution_state, seg.suggestion.person_id if seg.suggestion else None) for seg in segs]
            _set_suggestion(segs, pick, ctx.space_id)
            after = [(seg.attribution_state, seg.suggestion.person_id if seg.suggestion else None) for seg in segs]
            if before != after:
                changed += 1
        if changed:
            repository.save_transcript(ctx.transcript)
        logger.info(f"Re-matched speakers of meeting {meeting_id}: {changed} cluster(s) changed suggestion")
        ctx.warnings.append(f"Re-matched against {len(ctx.refs)} voiceprint(s); {changed} cluster(s) changed.")
        return ctx.response()


@router.post("/{cluster_id}/confirm", response_model=SpeakerCluster)
def decide_speaker(meeting_id: str, cluster_id: str, payload: SpeakerDecisionRequest) -> SpeakerCluster:
    """
    The single human decision point for speaker identity on a cluster.
    confirm/correct put the person's SNAPSHOT name on the cluster's segments (printable only above the speech
    floor); label puts a reviewer-chosen name (typed, or a meeting attendee/guest) on them the same way without
    any Person record; reject/unknown return them to anonymous, clearing a label too. Bound to the meeting
    revision and refused while the cluster's diagnostics block bulk attribution.
    """
    if payload.action in ("confirm", "correct") and not payload.profile_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"action '{payload.action}' requires profile_id")
    with repository.lock:
        ctx = _Context(meeting_id)
        grouped = ctx.clusters()
        segs = grouped.get(cluster_id)
        if not segs:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Cluster {cluster_id} not found on this meeting")
        label: Optional[str] = resolve_label(payload, ctx.meeting) if payload.action == "label" else None
        if payload.expected_revision != ctx.meeting.current_revision:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Revision conflict: you reviewed Rev.{payload.expected_revision} but the meeting is at Rev.{ctx.meeting.current_revision}. Reload before deciding.",
            )
        person: Optional[Person] = None
        if payload.action in ("confirm", "correct", "label"):
            blockers = ctx.blocking_reasons(cluster_id, segs)
            if blockers:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="; ".join(blockers))
        if payload.action in ("confirm", "correct"):
            person = repository.get_person(payload.profile_id)
            if not person or not person.is_active:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Voice profile not found")
            elsewhere = [
                other for other, other_segs in grouped.items()
                if other != cluster_id and any(seg.speaker_id == person.id for seg in other_segs)
            ]
            if elsewhere and payload.action != "correct":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"{person.full_name} is already confirmed on {', '.join(sorted(elsewhere))}. Use action 'correct' to attribute a second cluster to the same person deliberately.",
                )

        previous_name = next((seg.confirmed_display_name for seg in segs if seg.confirmed_display_name), None)
        previous_person_id = next((seg.speaker_id for seg in segs if seg.speaker_id), None)
        prior_suggestion = next((seg.suggestion for seg in segs if seg.suggestion), None)
        now = datetime.now(timezone.utc)
        reviewer = f"{payload.reviewer_name} ({payload.reviewer_role})"
        minutes = repository.get_minutes(meeting_id)

        # Revision first, so the confirmation is bound to the revision of the document it will be rendered in
        if minutes is not None:
            _bump_revision_if_signed_off(ctx.meeting, minutes)

        _apply_decision_to_segments(segs, payload.action, person, reviewer, now, ctx.meeting.current_revision, label=label)
        repository.save_transcript(ctx.transcript)

        speaker_map = repository.get_speaker_map(meeting_id) or SpeakerMap(meeting_id=meeting_id, space_id=ctx.space_id)
        speaker_map.space_id = speaker_map.space_id or ctx.space_id
        # reject records WHO was turned down (the prior suggestion or confirmation) so re-matching never asks again;
        # a label records the assigned name with no person behind it
        turned_down_id = None
        turned_down_name = None
        if payload.action == "reject":
            turned_down_id = prior_suggestion.person_id if prior_suggestion else previous_person_id
            turned_down_name = prior_suggestion.person_name if prior_suggestion else previous_name
        speaker_map.events.append(SpeakerAttributionEvent(
            meeting_id=meeting_id,
            cluster_id=cluster_id,
            action=payload.action if payload.action in _EVENT_ACTIONS else "correct",
            person_id=person.id if person else turned_down_id,
            person_name_snapshot=person.full_name if person else (label or turned_down_name),
            score_at_decision=prior_suggestion.score if prior_suggestion else None,
            margin_at_decision=prior_suggestion.margin if prior_suggestion else None,
            space_id=prior_suggestion.space_id if prior_suggestion else ctx.space_id,
            reviewer=reviewer,
            timestamp=now,
            segment_ids=[seg.id for seg in segs],
        ))
        repository.save_speaker_map(speaker_map)

        if minutes is not None:
            _apply_attribution_to_minutes(minutes, ctx.transcript, segs, cluster_label(cluster_id) or segs[0].speaker)
            pdf_path, docx_path = file_manager.get_export_paths(ctx.meeting.id, revision=minutes.revision)
            document_generator.generate_all(ctx.meeting, minutes, pdf_path, docx_path)
            minutes.pdf_path = str(pdf_path)
            minutes.docx_path = str(docx_path)
            repository.save_minutes(minutes)

        if person is not None:
            person.last_used_at = now
            person.updated_at = now
            repository.save_person(person)
        repository.save_meeting(ctx.meeting)
        assigned = person.full_name if person else label
        logger.info(
            f"Speaker decision on meeting {meeting_id} cluster {cluster_id}: {payload.action} "
            f"{'-> ' + assigned if assigned else ''} by {reviewer} at Rev.{ctx.meeting.current_revision} "
            f"({sum(1 for s in segs if s.printable_name)}/{len(segs)} turns printable)"
        )
        refreshed = _Context(meeting_id)
        grouped = refreshed.clusters()
        return refreshed.build_cluster(cluster_id, grouped[cluster_id], grouped)
