"""
Offline TestClient tests for the speaker confirmation write path (V7: /meetings/{id}/speakers).

    PYTHONPATH=backend .venv\\Scripts\\python.exe backend\\tests\\test_speaker_confirmation_flow.py

No audio is diarized here: a stored transcript (clusters + speech_seconds), minutes whose owners and evidence
speakers are anonymous "Speaker N" labels, enrolled people with synthetic voiceprints and a synthetic
segment-embedding cache are written into an isolated store, and the API is driven through FastAPI's
TestClient. No GPU, no Whisper, no Ollama (dead port), SMTP on a dead port with simulated delivery off.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_ROOT = Path(tempfile.mkdtemp(prefix="medpark_test_confirm_flow_"))
_REPO_ROOT = Path(__file__).resolve().parents[2]
os.environ["DATA_DIR"] = str(_ROOT / "data")
os.environ["UPLOADS_DIR"] = str(_ROOT / "uploads")
os.environ["EXPORTS_DIR"] = str(_ROOT / "exports")
os.environ["FIXTURES_DIR"] = str(_ROOT / "fixtures")
os.environ["VOICEPRINTS_DIR"] = str(_ROOT / "voiceprints")
os.environ.setdefault("MODELS_DIR", str(_REPO_ROOT / "data" / "models"))
os.environ["SMTP_HOST"] = "127.0.0.1"
os.environ["SMTP_PORT"] = "9"
os.environ["ALLOW_SIMULATED_DELIVERY"] = "false"
os.environ["REQUIRE_LOCAL_LLM"] = "false"
os.environ["LLM_API_BASE_URL"] = "http://127.0.0.1:9"
os.environ["WHISPER_DEVICE"] = "cpu"
os.environ["VOICE_ID_ENABLED"] = "true"
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

import json  # noqa: E402
import sys  # noqa: E402
import uuid  # noqa: E402
import zipfile  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.models.delivery import DeliveryRecord, DeliveryStatus  # noqa: E402
from app.models.extraction import ActionItem, DecisionItem, EvidenceQuote, MinutesOfMeeting, RiskOrQuestionItem  # noqa: E402
from app.models.meeting import Attendee, Meeting, ProcessingStatus, ReviewStatus, WorkflowMode  # noqa: E402
from app.models.person import ConsentRecord, Person, Voiceprint, compute_space_id  # noqa: E402
from app.models.transcript import SpeakerSuggestion, Transcript, TranscriptSegment  # noqa: E402
from app.services.diarization.embedder import speaker_embedder  # noqa: E402
from app.services.documents.generator import document_generator  # noqa: E402
from app.storage.file_manager import file_manager  # noqa: E402
from app.storage.repository import repository  # noqa: E402

NAME_A = "Dr. Ana Popescu"
NAME_B = "Dr. Ion Rusu"
NAME_D = "Dr. Maria Ciobanu"
ROSTER = "Dr. Elena Ceban"
REVIEWER = {"reviewer_name": "Dr. Rev", "reviewer_role": "Reviewer"}
FLOOR = float(settings.SPEAKER_MIN_PRINTABLE_SPEECH_S)

# (id, start, end, text, label, cluster, speech_seconds)
SEGMENT_SPEC = [
    ("a1", 0.0, 6.0, "Aprobăm protocolul de anticoagulare de la 1 octombrie.", "Speaker 1", "SPEAKER_01", 5.5),
    ("a2", 6.5, 7.7, "Da.", "Speaker 1", "SPEAKER_01", 1.0),
    ("a3", 8.0, 12.5, "Eu voi actualiza lista de medicamente până vineri.", "Speaker 1", "SPEAKER_01", 4.0),
    ("b1", 13.0, 19.5, "Raportul lunar de calitate va fi pregătit de mine până luni.", "Speaker 2", "SPEAKER_02", 6.0),
    ("b2", 20.0, 23.5, "Verificăm dozajul la toți pacienții internați.", "Speaker 2", "SPEAKER_02", 3.0),
    ("b3", 24.0, 29.5, "Programăm ședința următoare pentru săptămâna viitoare.", "Speaker 2", "SPEAKER_02", 5.0),
    ("c1", 30.0, 35.0, "Rămâne deschisă întrebarea privind bugetul secției.", "Speaker 3", "SPEAKER_03", 4.5),
    ("c2", 35.5, 39.0, "Trebuie clarificat cu departamentul financiar.", "Speaker 3", "SPEAKER_03", 3.0),
    ("c3", 40.0, 44.0, "Revenim cu detalii în ședința următoare.", "Speaker 3", "SPEAKER_03", 3.5),
]
TEXT = {spec[0]: spec[3] for spec in SEGMENT_SPEC}
SPAN = {spec[0]: (spec[1], spec[2]) for spec in SEGMENT_SPEC}


class _Skip(Exception):
    pass


def _skip(reason: str):
    try:
        import pytest

        pytest.skip(reason)
    except ImportError:
        raise _Skip(reason)


def _client():
    from fastapi.testclient import TestClient
    from app.main import app

    return TestClient(app)


def _space_id() -> str:
    """The real embedder space when the ONNX is present so the fixtures are scorable; a fixed one otherwise."""
    return speaker_embedder.space_id or compute_space_id("0" * 64, 512)


def _unit(rng: np.random.Generator, base: np.ndarray | None = None, noise: float = 0.0) -> np.ndarray:
    """A random unit vector, or `base` tilted by a unit noise direction scaled by `noise` (cosine ~ 1/sqrt(1+noise^2))."""
    direction = rng.standard_normal(512).astype(np.float32)
    direction /= np.linalg.norm(direction)
    vector = direction if base is None else base + noise * direction
    return (vector / np.linalg.norm(vector)).astype(np.float32)


def _person(name: str, vector: np.ndarray, space_id: str) -> Person:
    person = Person(full_name=name, role="Medic", email=f"{uuid.uuid4().hex[:6]}@example.invalid",
                    consent=ConsentRecord(given=True, given_at=datetime.now(timezone.utc)))
    vp_id = str(uuid.uuid4())
    path = file_manager.get_voiceprint_path(person.id, vp_id)
    file_manager.save_embedding_matrix(path, vector)
    person.voiceprints.append(Voiceprint(
        id=vp_id, space_id=space_id, model_sha256=speaker_embedder.model_sha256 or "0" * 64, dim=512,
        artifact_path=path.relative_to(settings.VOICEPRINTS_DIR).as_posix(), sample_count=3,
        total_speech_seconds=25.0, cohesion=0.82,
    ))
    repository.save_person(person)
    return person


def _quote(seg_id: str, label: str) -> EvidenceQuote:
    start, end = SPAN[seg_id]
    return EvidenceQuote(segment_id=seg_id, start=start, end=end, quote=TEXT[seg_id], speaker=label)


def _scenario() -> dict:
    """Fresh meeting + people + transcript + minutes + embedding cache in the isolated store."""
    assert repository.storage_dir.is_relative_to(_ROOT)
    assert Path(settings.VOICEPRINTS_DIR).is_relative_to(_ROOT)
    # People persist across scenarios in this process; a duplicate person with an identical voiceprint would
    # collapse the top1 - top2 margin to 0 and (correctly) suppress every suggestion.
    for stale in repository.list_people(include_inactive=True):
        file_manager.purge_person_biometrics(stale.id)
        repository.delete_person(stale.id)
    rng = np.random.default_rng(11)
    space_id = _space_id()
    v_a, v_b, v_c, v_d = _unit(rng), _unit(rng), _unit(rng), _unit(rng)
    person_a = _person(NAME_A, v_a, space_id)
    person_b = _person(NAME_B, v_b, space_id)
    person_d = _person(NAME_D, v_d, space_id)

    meeting = Meeting(
        title="Ședință Consiliu Medical - Flux confirmare vorbitori",
        workflow_mode=WorkflowMode.SUPERVISED,
        attendees=[Attendee(name=ROSTER, role="Director Medical", email="reviewer@example.invalid")],
        distribution_list=["outbox@example.invalid"],
        processing_status=ProcessingStatus.COMPLETED,
        processing_progress=100,
        review_status=ReviewStatus.PENDING_REVIEW,
        current_revision=1,
    )
    repository.save_meeting(meeting)

    suggestion = SpeakerSuggestion(person_id=person_a.id, person_name=NAME_A, score=0.72, margin=0.30, band="moderate", space_id=space_id)
    segments = []
    for seg_id, start, end, text, label, cluster_id, speech in SEGMENT_SPEC:
        fields = dict(id=seg_id, start=start, end=end, raw_text=text, speaker=label, cluster_id=cluster_id, speech_seconds=speech)
        if cluster_id == "SPEAKER_01":
            fields.update(attribution_state="suggested", suggestion=suggestion, suggested_identity=NAME_A)
        if seg_id == "c1":
            fields.update(is_flagged=True, flag_reason="Speaker change mid-segment")
        segments.append(TranscriptSegment(**fields))
    transcript = Transcript(meeting_id=meeting.id, segments=segments)
    transcript.compute_stats()
    repository.save_transcript(transcript)

    minutes = MinutesOfMeeting(
        meeting_id=meeting.id, title=meeting.title, meeting_type="medical", revision=1,
        summary_ro="Consiliul a aprobat protocolul de anticoagulare și a stabilit sarcini de urmărire.",
        decisions=[DecisionItem(topic="Protocoale ATI", decision="Se aprobă protocolul de anticoagulare.",
                                evidence=[_quote("a1", "Speaker 1"), _quote("a2", "Speaker 1")])],
        action_items=[
            ActionItem(id="act1", task="Actualizarea listei de medicamente.", owner="Speaker 1", owner_source="speaker",
                       deadline_phrase="până vineri", evidence=[_quote("a3", "Speaker 1")]),
            ActionItem(id="act2", task="Confirmarea protocolului.", owner="Speaker 1", owner_source="speaker",
                       evidence=[_quote("a1", "Speaker 1"), _quote("a2", "Speaker 1")]),
            ActionItem(id="act3", task="Pregătirea raportului lunar de calitate.", owner="Speaker 2", owner_source="speaker",
                       deadline_phrase="până luni", evidence=[_quote("b1", "Speaker 2")]),
            ActionItem(id="act4", task="Verificarea dozajului.", owner=ROSTER, owner_source="roster", evidence=[_quote("b2", "Speaker 2")]),
        ],
        risks_and_questions=[RiskOrQuestionItem(item_type="unresolved_question", description="Bugetul secției.", evidence=[_quote("c1", "Speaker 3")])],
        model_version="test-fixture",
    )
    pdf_path, docx_path = file_manager.get_export_paths(meeting.id, revision=1)
    document_generator.generate_all(meeting, minutes, pdf_path, docx_path)
    minutes.pdf_path, minutes.docx_path = str(pdf_path), str(docx_path)
    repository.save_minutes(minutes)

    # segment-embedding cache exactly as the diarizer writes it (sidecar version 1)
    rows = []
    for seg_id, *_rest in SEGMENT_SPEC:
        base = {"a": v_a, "b": v_b, "c": v_c}[seg_id[0]]
        rows.append(_unit(rng, base, noise=0.15))
    matrix = np.stack(rows).astype(np.float32)
    matrix_path, sidecar_path = file_manager.get_segment_embedding_paths(meeting.id)
    digest = file_manager.save_embedding_matrix(matrix_path, matrix)

    def cluster_meta(label: str, number: int, seconds: float, regions: int, short: bool, candidates: list) -> dict:
        reasons = [f"Only {regions} distinct speech region(s) in this cluster; at least 3 are needed before it can be confirmed in bulk."] if short else []
        return {"display_label": f"Speaker {number}", "window_count": 3, "window_speech_seconds": seconds, "region_count": regions,
                "mixed_suspect": False, "short_suspect": short, "split_cosine": 0.91, "split_shares": [0.6, 0.4],
                "reasons": reasons, "candidates": candidates}

    cand_a = [{"person_id": person_a.id, "person_name": NAME_A, "score": 0.72, "margin": 0.30, "band": "moderate", "voiceprint_id": person_a.voiceprints[0].id},
              {"person_id": person_b.id, "person_name": NAME_B, "score": 0.42, "margin": -0.30, "band": "no_match", "voiceprint_id": person_b.voiceprints[0].id}]
    sidecar = {
        "version": 1, "meeting_id": meeting.id, "segment_ids": [spec[0] for spec in SEGMENT_SPEC], "space_id": space_id,
        "model_sha256": speaker_embedder.model_sha256 or "0" * 64, "sha256": digest, "dim": 512,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "clusters": {
            "SPEAKER_01": cluster_meta("SPEAKER_01", 1, 10.5, 3, False, cand_a),
            "SPEAKER_02": cluster_meta("SPEAKER_02", 2, 14.0, 3, False, []),
            "SPEAKER_03": cluster_meta("SPEAKER_03", 3, 11.0, 2, True, []),
        },
        "merge_suggestions": [],
    }
    sidecar_path.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
    return {"meeting": meeting, "a": person_a, "b": person_b, "d": person_d, "space_id": space_id,
            "docx_before": docx_path.read_bytes()}


def _segments(meeting_id: str) -> dict[str, TranscriptSegment]:
    transcript = repository.get_transcript(meeting_id)
    assert transcript is not None
    return {seg.id: seg for seg in transcript.segments}


def _actions(meeting_id: str) -> dict[str, ActionItem]:
    minutes = repository.get_minutes(meeting_id)
    assert minutes is not None
    return {item.id: item for item in minutes.action_items}


def _evidence(meeting_id: str, seg_id: str) -> list[EvidenceQuote]:
    minutes = repository.get_minutes(meeting_id)
    assert minutes is not None
    found = []
    for item in [*minutes.decisions, *minutes.action_items, *minutes.risks_and_questions]:
        found.extend(ev for ev in item.evidence if ev.segment_id == seg_id)
    assert found, f"no evidence cites {seg_id}"
    return found


def _confirm(client, meeting_id: str, cluster_id: str, action: str, profile_id: str | None, expected_revision: int):
    body = {"action": action, "profile_id": profile_id, "expected_revision": expected_revision, **REVIEWER}
    return client.post(f"/api/v1/meetings/{meeting_id}/speakers/{cluster_id}/confirm", json=body)


def _docx_text(path: str) -> str:
    with zipfile.ZipFile(path) as zf:
        return zf.read("word/document.xml").decode("utf-8")


def _assert_untouched_cluster_b(meeting_id: str) -> None:
    for seg_id in ("b1", "b2", "b3"):
        seg = _segments(meeting_id)[seg_id]
        assert seg.attribution_state == "anonymous" and seg.speaker_id is None and seg.printable_name is False, seg_id
        assert seg.speaker == "Speaker 2" and seg.display_speaker == "Speaker 2"


# ---------------------------------------------------------------- read model
def test_get_speakers_lists_clusters_with_states_and_blocking_reasons():
    scenario = _scenario()
    meeting = scenario["meeting"]
    with _client() as client:
        res = client.get(f"/api/v1/meetings/{meeting.id}/speakers")
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["current_revision"] == 1 and payload["enrolled_people"] == 3
    assert isinstance(payload["embedder_available"], bool) and isinstance(payload["warnings"], list)
    clusters = {c["cluster_id"]: c for c in payload["clusters"]}
    assert set(clusters) == {"SPEAKER_01", "SPEAKER_02", "SPEAKER_03"}
    one = clusters["SPEAKER_01"]
    assert one["display_label"] == "Speaker 1" and one["state"] == "suggested"
    assert one["suggested_profile_id"] == scenario["a"].id and one["suggested_name"] == NAME_A
    assert one["match_band"] == "moderate" and 0.0 < one["match_score"] < 1.0
    assert one["turn_count"] == 3 and abs(one["total_speech_seconds"] - 10.5) < 0.01
    assert one["printable_turns"] == 2 and one["unprintable_turns"] == 1, "a2 (1.0 s) is below the printable floor"
    assert one["blocking_reasons"] == [] and one["confirmed_profile_id"] is None and one["confirmed_name"] is None
    assert 1 <= len(one["sample_turns"]) <= 5 and all({"segment_id", "start", "end", "text", "speech_seconds"} <= set(t) for t in one["sample_turns"])
    # sampled_seconds is audio the reviewer is asked to play (segment spans), bounded by the cluster's own turns
    cluster_span = sum(spec[2] - spec[1] for spec in SEGMENT_SPEC if spec[5] == "SPEAKER_01")
    assert 0.0 < one["sampled_seconds"] <= cluster_span + 1e-6
    two = clusters["SPEAKER_02"]
    assert two["state"] == "anonymous" and two["suggested_name"] is None and two["blocking_reasons"] == []
    three = clusters["SPEAKER_03"]
    assert three["blocking_reasons"], "a straddling segment / too few regions must block bulk confirmation"


def test_confirm_refuses_wrong_revision_blocked_cluster_and_missing_profile():
    scenario = _scenario()
    meeting, a = scenario["meeting"], scenario["a"]
    with _client() as client:
        assert _confirm(client, meeting.id, "SPEAKER_01", "confirm", a.id, expected_revision=99).status_code == 409
        blocked = _confirm(client, meeting.id, "SPEAKER_03", "confirm", a.id, expected_revision=1)
        assert blocked.status_code == 409, blocked.text
        assert _confirm(client, meeting.id, "SPEAKER_01", "confirm", None, expected_revision=1).status_code == 400
        assert _confirm(client, meeting.id, "SPEAKER_01", "correct", None, expected_revision=1).status_code == 400
        assert _confirm(client, meeting.id, "SPEAKER_99", "confirm", a.id, expected_revision=1).status_code == 404
        assert _confirm(client, "no-such-meeting", "SPEAKER_01", "confirm", a.id, expected_revision=1).status_code == 404
    # nothing was written
    segs = _segments(meeting.id)
    assert all(seg.attribution_state in ("anonymous", "suggested") for seg in segs.values())
    assert repository.get_speaker_map(meeting.id) is None or repository.get_speaker_map(meeting.id).events == []
    assert repository.get_meeting(meeting.id).current_revision == 1


# ---------------------------------------------------------------- happy path
def test_confirm_writes_segments_minutes_event_and_regenerates_in_place():
    scenario = _scenario()
    meeting, a = scenario["meeting"], scenario["a"]
    assert NAME_A not in _docx_text(repository.get_minutes(meeting.id).docx_path), "no name before confirmation"
    with _client() as client:
        res = _confirm(client, meeting.id, "SPEAKER_01", "confirm", a.id, expected_revision=1)
        assert res.status_code == 200, res.text
        cluster = res.json()
        listing = client.get(f"/api/v1/meetings/{meeting.id}/speakers").json()
    assert cluster["state"] == "confirmed" and cluster["confirmed_profile_id"] == a.id and cluster["confirmed_name"] == NAME_A
    assert cluster["confirmed_for_revision"] == 1
    assert cluster["printable_turns"] == 2 and cluster["unprintable_turns"] == 1
    assert cluster["suggested_name"] is None or cluster["suggested_name"] == NAME_A
    assert [c["state"] for c in listing["clusters"] if c["cluster_id"] == "SPEAKER_01"] == ["confirmed"]

    segs = _segments(meeting.id)
    for seg_id in ("a1", "a3"):
        seg = segs[seg_id]
        assert seg.attribution_state == "confirmed" and seg.speaker_id == a.id and seg.confirmed_display_name == NAME_A
        assert seg.printable_name is True and seg.display_speaker == NAME_A
        assert seg.confirmed_by == "Dr. Rev (Reviewer)" and seg.confirmed_at is not None and seg.confirmed_for_revision == 1
        assert seg.suggestion is None and seg.speaker == "Speaker 1", "the anonymous label and the LLM view never change"
    short = segs["a2"]
    assert short.attribution_state == "confirmed" and short.speaker_id == a.id
    assert short.speech_seconds == 1.0 and short.speech_seconds < FLOOR
    assert short.printable_name is False and short.display_speaker == "Speaker 1", "1.0 s 'Da.' never prints a name"
    _assert_untouched_cluster_b(meeting.id)
    transcript = repository.get_transcript(meeting.id)
    assert NAME_A not in transcript.to_full_text() and all(NAME_A not in line for line in transcript.to_indexed_lines()[0])

    # minutes: only printable segments carry the name
    for ev in _evidence(meeting.id, "a1"):
        assert ev.speaker == NAME_A and ev.speaker_person_id == a.id and ev.speaker_is_confirmed is True
    for ev in _evidence(meeting.id, "a2"):
        assert ev.speaker == "Speaker 1" and ev.speaker_person_id is None and ev.speaker_is_confirmed is False
    actions = _actions(meeting.id)
    assert actions["act1"].owner == NAME_A and actions["act1"].owner_source == "confirmed_speaker"
    assert actions["act2"].owner == "Speaker 1" and actions["act2"].owner_source == "speaker", "an unprintable evidence segment keeps the owner anonymous"
    assert actions["act3"].owner == "Speaker 2" and actions["act3"].owner_source == "speaker"
    assert actions["act4"].owner == ROSTER and actions["act4"].owner_source == "roster"

    # audit event
    speaker_map = repository.get_speaker_map(meeting.id)
    assert speaker_map is not None and len(speaker_map.events) == 1
    event = speaker_map.events[0]
    assert event.action == "confirm" and event.cluster_id == "SPEAKER_01" and event.person_id == a.id
    assert event.person_name_snapshot == NAME_A and event.reviewer == "Dr. Rev (Reviewer)"
    assert set(event.segment_ids) == {"a1", "a2", "a3"} and event.score_at_decision is not None

    # pending review: regenerated in place at Rev1, revision untouched
    stored = repository.get_meeting(meeting.id)
    minutes = repository.get_minutes(meeting.id)
    assert stored.current_revision == 1 and minutes.revision == 1 and stored.review_status == ReviewStatus.PENDING_REVIEW
    assert minutes.pdf_path.endswith("Medpark_MoM_Rev1.pdf") and Path(minutes.pdf_path).is_file()
    docx_after = _docx_text(minutes.docx_path)
    assert NAME_A in docx_after, "the regenerated document carries the confirmed name"
    assert NAME_B not in docx_after and NAME_D not in docx_after
    assert Path(minutes.docx_path).read_bytes() != scenario["docx_before"]


def test_confirm_after_approval_bumps_revision_and_invalidates_sign_off():
    scenario = _scenario()
    meeting, a, b = scenario["meeting"], scenario["a"], scenario["b"]
    with _client() as client:
        assert _confirm(client, meeting.id, "SPEAKER_01", "confirm", a.id, expected_revision=1).status_code == 200
        stored = repository.get_meeting(meeting.id)
        stored.review_status = ReviewStatus.APPROVED
        stored.approved_by = "Dr. Rev (Reviewer)"
        stored.approved_at = datetime.now(timezone.utc)
        repository.save_meeting(stored)

        res = _confirm(client, meeting.id, "SPEAKER_02", "confirm", b.id, expected_revision=1)
        assert res.status_code == 200, res.text
        assert res.json()["confirmed_for_revision"] == 2
    stored = repository.get_meeting(meeting.id)
    minutes = repository.get_minutes(meeting.id)
    assert stored.current_revision == 2 and minutes.revision == 2
    assert stored.review_status == ReviewStatus.PENDING_REVIEW and stored.approved_by is None and stored.approved_at is None
    assert minutes.pdf_path.endswith("Medpark_MoM_Rev2.pdf") and Path(minutes.pdf_path).is_file()
    assert Path(minutes.docx_path).name == "Medpark_MoM_Rev2.docx" and Path(minutes.docx_path).is_file()
    assert file_manager.get_export_paths(meeting.id, revision=1)[0].is_file(), "the Rev1 export stays immutable"
    segs = _segments(meeting.id)
    assert segs["b1"].confirmed_for_revision == 2 and segs["b1"].display_speaker == NAME_B
    assert segs["a1"].confirmed_for_revision == 1 and segs["a1"].display_speaker == NAME_A
    assert _actions(meeting.id)["act3"].owner == NAME_B and _actions(meeting.id)["act3"].owner_source == "confirmed_speaker"
    docx = _docx_text(minutes.docx_path)
    assert NAME_A in docx and NAME_B in docx

    # a delivery record for the current revision also forces a new revision on the next decision
    repository.save_delivery(DeliveryRecord(meeting_id=meeting.id, revision=2, recipients=["outbox@example.invalid"],
                                            subject="x", status=DeliveryStatus.DISPATCHED))
    with _client() as client:
        res = _confirm(client, meeting.id, "SPEAKER_02", "reject", None, expected_revision=2)
        assert res.status_code == 200, res.text
    assert repository.get_meeting(meeting.id).current_revision == 3
    assert repository.get_minutes(meeting.id).revision == 3


def test_reject_reverses_and_correct_replaces():
    scenario = _scenario()
    meeting, a, b, d = scenario["meeting"], scenario["a"], scenario["b"], scenario["d"]
    with _client() as client:
        assert _confirm(client, meeting.id, "SPEAKER_01", "confirm", a.id, expected_revision=1).status_code == 200
        assert _confirm(client, meeting.id, "SPEAKER_02", "confirm", b.id, expected_revision=1).status_code == 200
        assert _actions(meeting.id)["act3"].owner == NAME_B
        assert _evidence(meeting.id, "b1")[0].speaker == NAME_B

        res = _confirm(client, meeting.id, "SPEAKER_02", "reject", None, expected_revision=1)
        assert res.status_code == 200, res.text
        assert res.json()["state"] == "anonymous" and res.json()["confirmed_name"] is None
        _assert_untouched_cluster_b(meeting.id)
        for ev in _evidence(meeting.id, "b1"):
            assert ev.speaker == "Speaker 2" and ev.speaker_person_id is None and ev.speaker_is_confirmed is False
        actions = _actions(meeting.id)
        assert actions["act3"].owner == "Speaker 2" and actions["act3"].owner_source == "speaker"
        assert actions["act4"].owner == ROSTER and actions["act4"].owner_source == "roster"
        assert actions["act1"].owner == NAME_A, "rejecting cluster 2 never touches cluster 1"
        assert NAME_B not in _docx_text(repository.get_minutes(meeting.id).docx_path)

        res = _confirm(client, meeting.id, "SPEAKER_01", "correct", d.id, expected_revision=1)
        assert res.status_code == 200, res.text
        assert res.json()["state"] == "corrected" and res.json()["confirmed_name"] == NAME_D
    segs = _segments(meeting.id)
    assert segs["a1"].attribution_state == "corrected" and segs["a1"].speaker_id == d.id and segs["a1"].display_speaker == NAME_D
    assert segs["a2"].attribution_state == "corrected" and segs["a2"].printable_name is False and segs["a2"].display_speaker == "Speaker 1"
    assert _evidence(meeting.id, "a1")[0].speaker == NAME_D and _evidence(meeting.id, "a1")[0].speaker_person_id == d.id
    assert _actions(meeting.id)["act1"].owner == NAME_D and _actions(meeting.id)["act1"].owner_source == "confirmed_speaker"
    docx = _docx_text(repository.get_minutes(meeting.id).docx_path)
    assert NAME_D in docx and NAME_A not in docx
    events = repository.get_speaker_map(meeting.id).events
    assert [e.action for e in events] == ["confirm", "confirm", "reject", "correct"]
    assert events[-1].person_id == d.id and events[-1].person_name_snapshot == NAME_D
    # a reject event may record the person that was turned down (audit), never somebody else
    assert events[2].person_id in (None, b.id)

    with _client() as client:
        res = _confirm(client, meeting.id, "SPEAKER_02", "unknown", None, expected_revision=1)
        assert res.status_code == 200 and res.json()["state"] == "anonymous"
    _assert_untouched_cluster_b(meeting.id)


def test_same_person_on_a_second_cluster_needs_an_explicit_correct():
    scenario = _scenario()
    meeting, a = scenario["meeting"], scenario["a"]
    with _client() as client:
        assert _confirm(client, meeting.id, "SPEAKER_01", "confirm", a.id, expected_revision=1).status_code == 200
        res = _confirm(client, meeting.id, "SPEAKER_02", "confirm", a.id, expected_revision=1)
        assert res.status_code == 409, res.text
        _assert_untouched_cluster_b(meeting.id)
        res = _confirm(client, meeting.id, "SPEAKER_02", "correct", a.id, expected_revision=1)
        assert res.status_code == 200, res.text
        assert res.json()["state"] == "corrected" and res.json()["confirmed_name"] == NAME_A
    segs = _segments(meeting.id)
    assert segs["b1"].display_speaker == NAME_A and segs["a1"].display_speaker == NAME_A
    assert segs["b1"].attribution_state == "corrected" and segs["a1"].attribution_state == "confirmed"


def test_rematch_rescoring_keeps_confirmations_and_needs_no_audio():
    scenario = _scenario()
    meeting, a = scenario["meeting"], scenario["a"]
    with _client() as client:
        assert _confirm(client, meeting.id, "SPEAKER_01", "confirm", a.id, expected_revision=1).status_code == 200
        res = client.post(f"/api/v1/meetings/{meeting.id}/speakers/rematch")
        assert res.status_code == 200, res.text
        payload = res.json()
    clusters = {c["cluster_id"]: c for c in payload["clusters"]}
    assert clusters["SPEAKER_01"]["state"] == "confirmed" and clusters["SPEAKER_01"]["confirmed_name"] == NAME_A
    assert clusters["SPEAKER_03"]["blocking_reasons"]
    assert _segments(meeting.id)["a1"].display_speaker == NAME_A
    if not speaker_embedder.available:
        _skip("embedder unavailable: rematch scores cannot be checked without an active space")
    # synthetic cache: cluster 2 rows sit on person B's vector, so re-scoring must propose B for it
    assert clusters["SPEAKER_02"]["suggested_name"] == NAME_B and clusters["SPEAKER_02"]["state"] == "suggested"
    assert _segments(meeting.id)["b1"].attribution_state == "suggested"
    assert _segments(meeting.id)["b1"].display_speaker == "Speaker 2", "a suggestion never prints"


if __name__ == "__main__":
    import traceback

    tests = [(n, f) for n, f in globals().items() if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except _Skip as s:
            print(f"SKIP {name}: {s}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
            print("    " + "\n    ".join(traceback.format_exc().strip().splitlines()[-4:]))
    print(f"{len(tests) - failed}/{len(tests)} passed (store: {repository.storage_dir})")
    sys.exit(1 if failed else 0)
