"""
Offline TestClient tests for the reviewer LABEL assignment and the resolved-minutes read path (contract N4):

  - GET /meetings/{id}/speakers lists label_options (meeting attendees incl. client-side guests) and current_label;
  - POST .../{cluster}/confirm with action "label" (display_label or attendee_id) writes a "corrected" cluster with
    NO Person record (speaker_id None, attribution_basis "reviewer_label"), the same printable floor, evidence and
    owner rules as a voiceprint confirmation, an audit event, and regenerates the documents;
  - GET /meetings/{id}/minutes returns names inline where allowed (default names=resolved) while the store and
    ?names=labels keep the anonymous S<n> tokens; the translate endpoint returns resolved text; PUT stores verbatim;
  - the PDF and DOCX carry the assigned name and "Vorbitorul N" for the other clusters;
  - the relaxed TranscriptSegment invariant: "corrected" needs confirmed_display_name and (speaker_id OR a
    reviewer label); "confirmed" still needs speaker_id.

    PYTHONPATH=backend .venv\\Scripts\\python.exe backend\\tests\\test_speaker_label_action.py

No audio, no GPU, no Whisper, no Ollama (dead port), dead SMTP port, isolated storage under %TEMP%.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_ROOT = Path(tempfile.mkdtemp(prefix="medpark_test_label_action_"))
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
import re  # noqa: E402
import sys  # noqa: E402
import zipfile  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

import numpy as np  # noqa: E402
from pydantic import ValidationError  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from app.core.config import settings  # noqa: E402
from app.models.extraction import ActionItem, DecisionItem, EvidenceQuote, MinutesOfMeeting, RiskOrQuestionItem  # noqa: E402
from app.models.meeting import Attendee, Meeting, ProcessingStatus, ReviewStatus, WorkflowMode  # noqa: E402
from app.models.person import compute_space_id  # noqa: E402
from app.models.transcript import Transcript, TranscriptSegment  # noqa: E402
from app.services.diarization.embedder import speaker_embedder  # noqa: E402
from app.services.documents.generator import document_generator  # noqa: E402
from app.services.extraction.attribution_render import LABEL_RE  # noqa: E402
from app.storage.file_manager import file_manager  # noqa: E402
from app.storage.repository import repository  # noqa: E402
from voice_e2e_gpu import pdf_text  # noqa: E402  (best-effort fpdf2 text extractor; no GPU code runs on import)

ROSTER = "Dr. Elena Ceban"
GUEST_ID = "guest_1758870000000_k3x9q"
GUEST = "Ing. Vasile Oprea"
LABEL = "Consultant extern"
REVIEWER = {"reviewer_name": "Dr. Rev", "reviewer_role": "Reviewer"}
FLOOR = float(settings.SPEAKER_MIN_PRINTABLE_SPEECH_S)

# (id, start, end, text, label, cluster, speech_seconds)
SEGMENT_SPEC = [
    ("a1", 0.0, 6.0, "Deschidem ședința. Aprobăm protocolul de anticoagulare de la 1 octombrie.", "Speaker 1", "SPEAKER_01", 5.5),
    ("a2", 6.5, 7.7, "Da.", "Speaker 1", "SPEAKER_01", 1.0),
    ("a3", 8.0, 12.5, "Eu voi actualiza lista de medicamente până vineri.", "Speaker 1", "SPEAKER_01", 4.0),
    ("b1", 13.0, 19.5, "Raportul lunar de calitate va fi pregătit de mine până luni.", "Speaker 2", "SPEAKER_02", 6.0),
    ("b2", 20.0, 21.4, "Verificăm dozajul.", "Speaker 2", "SPEAKER_02", 1.2),
    ("b3", 22.0, 27.5, "Propun actualizarea listei de medicamente.", "Speaker 2", "SPEAKER_02", 5.0),
    ("c1", 30.0, 35.0, "Rămâne deschisă întrebarea privind bugetul secției.", "Speaker 3", "SPEAKER_03", 4.5),
    ("c2", 35.5, 39.0, "Trebuie clarificat cu departamentul financiar.", "Speaker 3", "SPEAKER_03", 3.0),
    ("c3", 40.0, 44.0, "Revenim cu detalii în ședința următoare.", "Speaker 3", "SPEAKER_03", 3.5),
]
TEXT = {spec[0]: spec[3] for spec in SEGMENT_SPEC}
SPAN = {spec[0]: (spec[1], spec[2]) for spec in SEGMENT_SPEC}
SUMMARY_RO = "S1 a deschis ședința și a aprobat protocolul de anticoagulare. S2 a propus actualizarea listei de medicamente; S1 a aprobat. S3 a ridicat întrebarea bugetului secției."
SUMMARY_EN = "S1 opened the meeting and approved the anticoagulation protocol. S2 proposed updating the medication list; S1 approved. S3 raised the budget question."


def _client():
    from fastapi.testclient import TestClient
    from app.main import app

    return TestClient(app)


def _quote(seg_id: str, label: str) -> EvidenceQuote:
    start, end = SPAN[seg_id]
    return EvidenceQuote(segment_id=seg_id, start=start, end=end, quote=TEXT[seg_id], speaker=label)


def _scenario() -> Meeting:
    """Fresh meeting (roster person + client-side guest) + anonymous transcript + labelled minutes + embedding cache."""
    assert repository.storage_dir.is_relative_to(_ROOT)
    assert Path(settings.VOICEPRINTS_DIR).is_relative_to(_ROOT)
    meeting = Meeting(
        title="Ședință Consiliu Medical - Etichete vorbitori",
        workflow_mode=WorkflowMode.SUPERVISED,
        attendees=[
            Attendee(name=ROSTER, role="Director Medical", email="reviewer@example.invalid"),
            Attendee(id=GUEST_ID, name=GUEST, role="External Guest", email="guest@example.invalid"),
        ],
        distribution_list=["outbox@example.invalid"],
        processing_status=ProcessingStatus.COMPLETED,
        processing_progress=100,
        review_status=ReviewStatus.PENDING_REVIEW,
        current_revision=1,
    )
    repository.save_meeting(meeting)

    segments = [
        TranscriptSegment(id=seg_id, start=start, end=end, raw_text=text, speaker=label, cluster_id=cluster_id, speech_seconds=speech)
        for seg_id, start, end, text, label, cluster_id, speech in SEGMENT_SPEC
    ]
    transcript = Transcript(meeting_id=meeting.id, segments=segments)
    transcript.compute_stats()
    repository.save_transcript(transcript)

    minutes = MinutesOfMeeting(
        meeting_id=meeting.id, title=meeting.title, meeting_type="medical", revision=1, speaker_label_style="labels",
        summary_ro=SUMMARY_RO, summary_en=SUMMARY_EN,
        agenda_topics=["Protocol anticoagulare", "Lista de medicamente", "Buget secție"],
        decisions=[DecisionItem(topic="Protocoale ATI", decision="S1 a aprobat protocolul de anticoagulare de la 1 octombrie.",
                                evidence=[_quote("a1", "Speaker 1"), _quote("a2", "Speaker 1")])],
        action_items=[
            ActionItem(id="act1", task="S2 va pregăti raportul lunar de calitate.", owner="Speaker 2", owner_source="speaker",
                       deadline_phrase="până luni", evidence=[_quote("b1", "Speaker 2")]),
            ActionItem(id="act2", task="S2 va verifica dozajul.", owner="Speaker 2", owner_source="speaker",
                       evidence=[_quote("b2", "Speaker 2")]),
            ActionItem(id="act3", task="S1 va actualiza lista de medicamente.", owner="Speaker 1", owner_source="speaker",
                       deadline_phrase="până vineri", evidence=[_quote("a3", "Speaker 1")]),
            ActionItem(id="act4", task="Verificarea dozajului conform S2.", owner=ROSTER, owner_source="roster", evidence=[_quote("b3", "Speaker 2")]),
        ],
        risks_and_questions=[RiskOrQuestionItem(item_type="unresolved_question", description="S3 a ridicat întrebarea bugetului secției.",
                                                evidence=[_quote("c1", "Speaker 3")])],
        model_version="test-fixture",
    )
    pdf_path, docx_path = file_manager.get_export_paths(meeting.id, revision=1)
    document_generator.generate_all(meeting, minutes, pdf_path, docx_path)
    minutes.pdf_path, minutes.docx_path = str(pdf_path), str(docx_path)
    repository.save_minutes(minutes)

    # segment-embedding cache exactly as the diarizer writes it (sidecar version 1), so no cluster is blocked
    rng = np.random.default_rng(7)
    space_id = speaker_embedder.space_id or compute_space_id("0" * 64, 512)
    bases = {}
    for prefix in "abc":
        v = rng.standard_normal(512).astype(np.float32)
        bases[prefix] = v / np.linalg.norm(v)
    rows = []
    for seg_id, *_rest in SEGMENT_SPEC:
        v = bases[seg_id[0]] + 0.15 * rng.standard_normal(512).astype(np.float32)
        rows.append(v / np.linalg.norm(v))
    matrix = np.stack(rows).astype(np.float32)
    matrix_path, sidecar_path = file_manager.get_segment_embedding_paths(meeting.id)
    digest = file_manager.save_embedding_matrix(matrix_path, matrix)

    def cluster_meta(number: int, seconds: float) -> dict:
        return {"display_label": f"Speaker {number}", "window_count": 3, "window_speech_seconds": seconds, "region_count": 3,
                "mixed_suspect": False, "short_suspect": False, "split_cosine": 0.91, "split_shares": [0.6, 0.4],
                "reasons": [], "candidates": []}

    sidecar = {
        "version": 1, "meeting_id": meeting.id, "segment_ids": [spec[0] for spec in SEGMENT_SPEC], "space_id": space_id,
        "model_sha256": speaker_embedder.model_sha256 or "0" * 64, "sha256": digest, "dim": 512,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "clusters": {"SPEAKER_01": cluster_meta(1, 10.5), "SPEAKER_02": cluster_meta(2, 12.2), "SPEAKER_03": cluster_meta(3, 11.0)},
        "merge_suggestions": [],
    }
    sidecar_path.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
    return meeting


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


def _decide(client, meeting_id: str, cluster_id: str, action: str, expected_revision: int = 1, **fields):
    body = {"action": action, "expected_revision": expected_revision, **REVIEWER, **fields}
    return client.post(f"/api/v1/meetings/{meeting_id}/speakers/{cluster_id}/confirm", json=body)


def _docx_text(path: str) -> str:
    with zipfile.ZipFile(path) as zf:
        return re.sub(r"<[^>]+>", " ", zf.read("word/document.xml").decode("utf-8"))


def _docx_action_owners(path: str) -> dict[str, str]:
    """Task text -> 'Responsabil' cell of the DOCX action table (the table whose header starts with 'Sarcină')."""
    from docx import Document

    for table in Document(path).tables:
        header = [cell.text.strip() for cell in table.rows[0].cells]
        if header and header[0].startswith("Sarcină") and len(header) >= 2 and header[1] == "Responsabil":
            return {row.cells[0].text.strip(): row.cells[1].text.strip() for row in table.rows[1:]}
    raise AssertionError("no action table in the DOCX")


def _pdf_text(path: str) -> str:
    return pdf_text(Path(path).read_bytes())


def _tokens(text: str | None) -> set[str]:
    return {"S" + m.group(1) for m in LABEL_RE.finditer(text or "")}


# ---------------------------------------------------------------- read model
def test_speakers_listing_offers_attendees_and_guests_as_label_options():
    meeting = _scenario()
    with _client() as client:
        res = client.get(f"/api/v1/meetings/{meeting.id}/speakers")
    assert res.status_code == 200, res.text
    clusters = {c["cluster_id"]: c for c in res.json()["clusters"]}
    assert set(clusters) == {"SPEAKER_01", "SPEAKER_02", "SPEAKER_03"}
    for cluster in clusters.values():
        assert cluster["current_label"] is None and cluster["state"] == "anonymous"
        options = {o["id"]: o for o in cluster["label_options"]}
        assert set(options) == {meeting.attendees[0].id, GUEST_ID}, options
        roster = options[meeting.attendees[0].id]
        assert roster["name"] == ROSTER and roster["role"] == "Director Medical" and roster["is_guest"] is False
        guest = options[GUEST_ID]
        assert guest["name"] == GUEST and guest["role"] == "External Guest" and guest["is_guest"] is True
        assert cluster["blocking_reasons"] == []
    print("PASS test_speakers_listing_offers_attendees_and_guests_as_label_options")


# ---------------------------------------------------------------- label with a typed name
def test_label_action_with_custom_label_names_cluster_without_a_person():
    meeting = _scenario()
    docx_before = _docx_text(repository.get_minutes(meeting.id).docx_path)
    assert LABEL not in docx_before and "Vorbitorul 2" in docx_before, "before: anonymous everywhere, prose already resolved"
    assert "S2 a propus" in repository.get_minutes(meeting.id).summary_ro, "the store keeps label tokens"

    with _client() as client:
        res = _decide(client, meeting.id, "SPEAKER_02", "label", display_label=f"  {LABEL}  ")
        assert res.status_code == 200, res.text
        cluster = res.json()
        listing = client.get(f"/api/v1/meetings/{meeting.id}/speakers").json()
        resolved = client.get(f"/api/v1/meetings/{meeting.id}/minutes").json()
        resolved_explicit = client.get(f"/api/v1/meetings/{meeting.id}/minutes", params={"names": "resolved"}).json()
        labels = client.get(f"/api/v1/meetings/{meeting.id}/minutes", params={"names": "labels"}).json()
        assert client.get(f"/api/v1/meetings/{meeting.id}/minutes", params={"names": "bogus"}).status_code == 422

    # cluster card: corrected, labelled, no voiceprint behind it
    assert cluster["state"] == "corrected" and cluster["current_label"] == LABEL, cluster
    assert cluster["confirmed_profile_id"] is None and cluster["confirmed_name"] == LABEL
    assert cluster["confirmed_for_revision"] == 1
    assert cluster["printable_turns"] == 2 and cluster["unprintable_turns"] == 1, "b2 (1.2 s) is below the printable floor"
    assert [c["current_label"] for c in listing["clusters"] if c["cluster_id"] == "SPEAKER_02"] == [LABEL]
    assert all(c["current_label"] is None for c in listing["clusters"] if c["cluster_id"] != "SPEAKER_02")

    # segments: state, basis, printable floor, anonymous label untouched
    segs = _segments(meeting.id)
    for seg_id in ("b1", "b3"):
        seg = segs[seg_id]
        assert seg.attribution_state == "corrected" and seg.attribution_basis == "reviewer_label"
        assert seg.speaker_id is None and seg.confirmed_display_name == LABEL
        assert seg.printable_name is True and seg.display_speaker == LABEL
        assert seg.confirmed_by == "Dr. Rev (Reviewer)" and seg.confirmed_at is not None and seg.confirmed_for_revision == 1
        assert seg.speaker == "Speaker 2", "the anonymous label the LLM sees never changes"
    short = segs["b2"]
    assert short.attribution_state == "corrected" and short.confirmed_display_name == LABEL
    assert short.speech_seconds < FLOOR and short.printable_name is False and short.display_speaker == "Speaker 2"
    for seg_id in ("a1", "a2", "a3", "c1", "c2", "c3"):
        assert segs[seg_id].attribution_state == "anonymous" and segs[seg_id].confirmed_display_name is None
    transcript = repository.get_transcript(meeting.id)
    assert LABEL not in transcript.to_full_text() and all(LABEL not in line for line in transcript.to_indexed_lines()[0])
    assert LABEL in transcript.to_full_text(use_display_names=True)

    # no Person and no voiceprint were created
    assert repository.list_people(include_inactive=True) == []
    assert not list(Path(settings.VOICEPRINTS_DIR).glob("people/**/*.npy"))

    # stored minutes: evidence and owner follow the label ONLY on printable segments; prose keeps its tokens
    for ev in _evidence(meeting.id, "b1"):
        assert ev.speaker == LABEL and ev.speaker_is_confirmed is True and ev.speaker_person_id is None
    for ev in _evidence(meeting.id, "b2"):
        assert ev.speaker == "Speaker 2" and ev.speaker_is_confirmed is False and ev.speaker_person_id is None
    actions = _actions(meeting.id)
    assert actions["act1"].owner == LABEL and actions["act1"].owner_source == "confirmed_speaker"
    assert actions["act2"].owner == "Speaker 2" and actions["act2"].owner_source == "speaker", "an unprintable evidence segment keeps the owner anonymous"
    assert actions["act3"].owner == "Speaker 1" and actions["act3"].owner_source == "speaker"
    assert actions["act4"].owner == ROSTER and actions["act4"].owner_source == "roster"
    stored = repository.get_minutes(meeting.id)
    assert stored.summary_ro == SUMMARY_RO and stored.action_items[0].task == "S2 va pregăti raportul lunar de calitate."
    assert LABEL not in stored.summary_ro and LABEL not in stored.decisions[0].decision

    # GET /minutes: resolved by default, tokens on request
    assert resolved == resolved_explicit
    assert resolved["summary_ro"] == (
        f"Vorbitorul 1 a deschis ședința și a aprobat protocolul de anticoagulare. {LABEL} a propus actualizarea listei de medicamente; "
        "Vorbitorul 1 a aprobat. Vorbitorul 3 a ridicat întrebarea bugetului secției."
    ), resolved["summary_ro"]
    assert resolved["summary_en"] == (
        f"Speaker 1 opened the meeting and approved the anticoagulation protocol. {LABEL} proposed updating the medication list; "
        "Speaker 1 approved. Speaker 3 raised the budget question."
    ), resolved["summary_en"]
    assert resolved["decisions"][0]["decision"] == "Vorbitorul 1 a aprobat protocolul de anticoagulare de la 1 octombrie."
    resolved_actions = {a["id"]: a for a in resolved["action_items"]}
    assert resolved_actions["act1"]["task"] == f"{LABEL} va pregăti raportul lunar de calitate." and resolved_actions["act1"]["owner"] == LABEL
    assert resolved_actions["act1"]["evidence"][0]["speaker"] == LABEL, "a printable labelled turn prints the label on its quote"
    # Prose attributes the whole cluster, but an evidence quote IS one segment and a speaker-derived owner is only as
    # printable as every turn it cites: b2 (1.2 s) is below the floor, so its quote and act2's owner stay anonymous in
    # the resolved read exactly as in storage (invariant 4; same rule as _apply_attribution_to_minutes).
    assert resolved_actions["act2"]["task"] == f"{LABEL} va verifica dozajul."
    assert resolved_actions["act2"]["owner"] == "Speaker 2" and resolved_actions["act2"]["owner_source"] == "speaker", resolved_actions["act2"]
    assert resolved_actions["act2"]["evidence"][0]["speaker"] == "Speaker 2", resolved_actions["act2"]["evidence"]
    resolved_decision_evidence = {ev["segment_id"]: ev["speaker"] for ev in resolved["decisions"][0]["evidence"]}
    assert resolved_decision_evidence == {"a1": "Speaker 1", "a2": "Speaker 1"}, resolved_decision_evidence
    assert resolved_actions["act4"]["task"] == f"Verificarea dozajului conform {LABEL}." and resolved_actions["act4"]["owner"] == ROSTER
    assert resolved["risks_and_questions"][0]["description"] == "Vorbitorul 3 a ridicat întrebarea bugetului secției."
    assert not _tokens(json.dumps(resolved, ensure_ascii=False)), "no S<n> token survives a resolved read"
    assert labels["summary_ro"] == SUMMARY_RO and labels["decisions"][0]["decision"].startswith("S1 a aprobat")
    assert labels["action_items"][0]["owner"] == LABEL, "?names=labels is the stored form: evidence/owner names written by the decision stay"
    assert resolved["speaker_label_style"] == "labels" and labels["speaker_label_style"] == "labels"

    # audit event: no person behind the label, the label snapshotted
    events = repository.get_speaker_map(meeting.id).events
    assert len(events) == 1 and events[0].cluster_id == "SPEAKER_02" and events[0].person_id is None
    assert events[0].person_name_snapshot == LABEL and events[0].reviewer == "Dr. Rev (Reviewer)"
    assert events[0].action in ("label", "correct"), events[0].action
    assert set(events[0].segment_ids) == {"b1", "b2", "b3"}

    # documents regenerated in place at Rev1: the label inline, "Vorbitorul N" for the other clusters, legend printed
    minutes = repository.get_minutes(meeting.id)
    assert minutes.revision == 1 and minutes.docx_path.endswith("Medpark_MoM_Rev1.docx")
    docx = _docx_text(minutes.docx_path)
    assert f"{LABEL} a propus actualizarea listei" in docx and f"{LABEL} va pregăti raportul" in docx, "label inline in the DOCX prose"
    assert "Vorbitorul 1 a deschis" in docx and "Vorbitorul 3 a ridicat" in docx
    assert not _tokens(docx), "no raw S<n> token printed"
    assert "Atribuirea Vorbitorilor" in docx and f"{LABEL} — corectat de Dr. Rev (Reviewer)" in docx, "legend names the label and the reviewer"
    assert docx.count(GUEST) == 1, "the guest appears once, in the participants line, never as an attribution"
    owner_column = _docx_action_owners(minutes.docx_path)
    assert owner_column == {
        f"{LABEL} va pregăti raportul lunar de calitate.": LABEL,
        f"{LABEL} va verifica dozajul.": "Vorbitor 2",
        "Vorbitorul 1 va actualiza lista de medicamente.": "Vorbitor 1",
        f"Verificarea dozajului conform {LABEL}.": ROSTER,
    }, owner_column
    pdf = _pdf_text(minutes.pdf_path)
    if len(pdf) >= 200:
        assert LABEL in pdf and "Vorbitorul 1" in pdf and "Vorbitorul 3" in pdf, pdf[:400]
        assert f"Responsabil: {LABEL}" in pdf and "Responsabil: Vorbitor 2" in pdf, "the sub-floor task's owner stays anonymous in the PDF"
        assert not _tokens(pdf)
    else:
        print("  (PDF text extraction yielded too little text on this host; DOCX assertions cover the content)")
    print("PASS test_label_action_with_custom_label_names_cluster_without_a_person")


# ---------------------------------------------------------------- label from the roster / a guest
def test_label_action_with_attendee_ids_including_a_guest():
    meeting = _scenario()
    roster_id = meeting.attendees[0].id
    with _client() as client:
        res = _decide(client, meeting.id, "SPEAKER_03", "label", attendee_id=GUEST_ID)
        assert res.status_code == 200, res.text
        assert res.json()["state"] == "corrected" and res.json()["current_label"] == GUEST and res.json()["confirmed_profile_id"] is None
        res = _decide(client, meeting.id, "SPEAKER_01", "label", attendee_id=roster_id, display_label="ignored when attendee_id is given")
        assert res.status_code == 200, res.text
        assert res.json()["current_label"] == ROSTER
        resolved = client.get(f"/api/v1/meetings/{meeting.id}/minutes").json()
    segs = _segments(meeting.id)
    assert segs["c1"].confirmed_display_name == GUEST and segs["c1"].speaker_id is None and segs["c1"].attribution_basis == "reviewer_label"
    assert segs["a1"].confirmed_display_name == ROSTER and segs["a1"].speaker_id is None and segs["a1"].attribution_basis == "reviewer_label"
    assert segs["a2"].printable_name is False and segs["a2"].display_speaker == "Speaker 1"
    assert repository.list_people(include_inactive=True) == [], "an attendee label never creates a Person"
    assert resolved["summary_ro"].startswith(f"{ROSTER} a deschis ședința") and f"{GUEST} a ridicat întrebarea" in resolved["summary_ro"]
    assert "Vorbitorul 2 a propus" in resolved["summary_ro"]
    assert resolved["risks_and_questions"][0]["evidence"][0]["speaker"] == GUEST
    events = repository.get_speaker_map(meeting.id).events
    assert [e.person_name_snapshot for e in events] == [GUEST, ROSTER] and all(e.person_id is None for e in events)
    docx = _docx_text(repository.get_minutes(meeting.id).docx_path)
    assert GUEST in docx and ROSTER in docx and "Vorbitorul 2" in docx
    print("PASS test_label_action_with_attendee_ids_including_a_guest")


# ---------------------------------------------------------------- refusals
def test_label_action_refuses_bad_labels_and_writes_nothing():
    meeting = _scenario()
    with _client() as client:
        assert _decide(client, meeting.id, "SPEAKER_02", "label").status_code == 400, "display_label or attendee_id is required"
        for bad in ("S1", "s2", "Speaker 3", "speaker 12", "x", " ", "a" * 61):
            res = _decide(client, meeting.id, "SPEAKER_02", "label", display_label=bad)
            assert res.status_code in (400, 422), (bad, res.status_code, res.text)
        assert _decide(client, meeting.id, "SPEAKER_02", "label", attendee_id="no-such-attendee").status_code in (400, 404)
        assert _decide(client, meeting.id, "SPEAKER_02", "label", display_label=LABEL, expected_revision=99).status_code == 409
        assert _decide(client, meeting.id, "SPEAKER_99", "label", display_label=LABEL).status_code == 404
        assert _decide(client, "no-such-meeting", "SPEAKER_02", "label", display_label=LABEL).status_code == 404
        # the voiceprint actions keep their own guard
        assert _decide(client, meeting.id, "SPEAKER_02", "confirm").status_code == 400
    segs = _segments(meeting.id)
    assert all(seg.attribution_state == "anonymous" and seg.confirmed_display_name is None for seg in segs.values())
    speaker_map = repository.get_speaker_map(meeting.id)
    assert speaker_map is None or speaker_map.events == []
    assert repository.get_meeting(meeting.id).current_revision == 1
    assert _actions(meeting.id)["act1"].owner == "Speaker 2"
    print("PASS test_label_action_refuses_bad_labels_and_writes_nothing")


# ---------------------------------------------------------------- reversal and revision binding
def test_reject_clears_label_and_approved_minutes_get_a_new_revision():
    meeting = _scenario()
    with _client() as client:
        assert _decide(client, meeting.id, "SPEAKER_02", "label", display_label=LABEL).status_code == 200
        assert _actions(meeting.id)["act1"].owner == LABEL
        res = _decide(client, meeting.id, "SPEAKER_02", "reject")
        assert res.status_code == 200, res.text
        assert res.json()["state"] == "anonymous" and res.json()["current_label"] is None and res.json()["confirmed_name"] is None
        resolved = client.get(f"/api/v1/meetings/{meeting.id}/minutes").json()
    segs = _segments(meeting.id)
    for seg_id in ("b1", "b2", "b3"):
        seg = segs[seg_id]
        assert seg.attribution_state == "anonymous" and seg.confirmed_display_name is None and seg.printable_name is False
        assert seg.attribution_basis == "voiceprint" and seg.display_speaker == "Speaker 2"
    for ev in _evidence(meeting.id, "b1"):
        assert ev.speaker == "Speaker 2" and ev.speaker_is_confirmed is False
    assert _actions(meeting.id)["act1"].owner == "Speaker 2" and _actions(meeting.id)["act1"].owner_source == "speaker"
    assert "Vorbitorul 2 a propus" in resolved["summary_ro"] and LABEL not in json.dumps(resolved, ensure_ascii=False)
    assert LABEL not in _docx_text(repository.get_minutes(meeting.id).docx_path)

    # a label on approved minutes invalidates the sign-off and binds to the new revision
    stored = repository.get_meeting(meeting.id)
    stored.review_status = ReviewStatus.APPROVED
    stored.approved_by = "Dr. Rev (Reviewer)"
    stored.approved_at = datetime.now(timezone.utc)
    repository.save_meeting(stored)
    with _client() as client:
        res = _decide(client, meeting.id, "SPEAKER_02", "label", display_label=LABEL, expected_revision=1)
        assert res.status_code == 200, res.text
        assert res.json()["confirmed_for_revision"] == 2
    stored = repository.get_meeting(meeting.id)
    minutes = repository.get_minutes(meeting.id)
    assert stored.current_revision == 2 and minutes.revision == 2 and stored.review_status == ReviewStatus.PENDING_REVIEW
    assert stored.approved_by is None and minutes.docx_path.endswith("Medpark_MoM_Rev2.docx")
    assert file_manager.get_export_paths(meeting.id, revision=1)[1].is_file(), "the Rev1 export stays immutable"
    assert _segments(meeting.id)["b1"].confirmed_for_revision == 2
    print("PASS test_reject_clears_label_and_approved_minutes_get_a_new_revision")


# ---------------------------------------------------------------- translate + PUT read/write semantics
def test_translate_endpoint_resolves_and_put_stores_verbatim():
    meeting = _scenario()
    with _client() as client:
        assert _decide(client, meeting.id, "SPEAKER_02", "label", display_label=LABEL).status_code == 200
        # dead LLM port -> deterministic "[RU] " fallback on the STORED token text; the response is resolved
        res = client.post(f"/api/v1/meetings/{meeting.id}/translate", params={"target_lang": "ru"})
        assert res.status_code == 200, res.text
        body = res.json()
        stored = repository.get_minutes(meeting.id)
        assert stored.action_items[0].task_ru == "[RU] S2 va pregăti raportul lunar de calitate.", stored.action_items[0].task_ru
        assert stored.decisions[0].decision_ru.startswith("[RU] S1 a aprobat")
        assert body["action_items"][0]["task_ru"] == f"[RU] {LABEL} va pregăti raportul lunar de calitate."
        assert body["decisions"][0]["decision_ru"].startswith("[RU] Участник 1 a aprobat")
        assert body["action_items"][0]["task"] == f"{LABEL} va pregăti raportul lunar de calitate."
        assert not _tokens(json.dumps(body, ensure_ascii=False))
        ro = client.post(f"/api/v1/meetings/{meeting.id}/translate", params={"target_lang": "ro"})
        assert ro.status_code == 200 and ro.json()["summary_ro"] == client.get(f"/api/v1/meetings/{meeting.id}/minutes").json()["summary_ro"]

        # PUT: what the reviewer sends is stored as sent (tokens stay tokens, a typed name stays a name)
        current = client.get(f"/api/v1/meetings/{meeting.id}/minutes", params={"names": "labels"}).json()
        current["summary_ro"] = "S3 a semnalat un risc nou; S2 a preluat sarcina."
        current["decisions"][0]["decision"] = "Dr. Rev a aprobat protocolul (notă a revizorului)."
        put = client.put(f"/api/v1/meetings/{meeting.id}/minutes", json=current)
        assert put.status_code == 200, put.text
        stored = repository.get_minutes(meeting.id)
        assert stored.summary_ro == "S3 a semnalat un risc nou; S2 a preluat sarcina." and stored.revision == 2
        assert stored.decisions[0].decision == "Dr. Rev a aprobat protocolul (notă a revizorului)."
        resolved = client.get(f"/api/v1/meetings/{meeting.id}/minutes").json()
        assert resolved["summary_ro"] == f"Vorbitorul 3 a semnalat un risc nou; {LABEL} a preluat sarcina."
        assert resolved["decisions"][0]["decision"] == "Dr. Rev a aprobat protocolul (notă a revizorului)."
    docx = _docx_text(repository.get_minutes(meeting.id).docx_path)
    assert f"{LABEL} a preluat sarcina" in docx and "Vorbitorul 3 a semnalat" in docx
    print("PASS test_translate_endpoint_resolves_and_put_stores_verbatim")


# ---------------------------------------------------------------- model invariants
def test_segment_invariants_accept_reviewer_label_without_a_person():
    base = dict(id="x", start=0.0, end=5.0, raw_text="text", speaker="Speaker 2", speech_seconds=4.5,
                confirmed_display_name=LABEL, confirmed_by="Dr. Rev (Reviewer)", confirmed_for_revision=1, printable_name=True)
    seg = TranscriptSegment(**base, attribution_state="corrected", speaker_id=None, attribution_basis="reviewer_label")
    assert seg.display_speaker == LABEL and seg.speaker == "Speaker 2"
    again = TranscriptSegment.model_validate(json.loads(seg.model_dump_json()))
    assert again.attribution_basis == "reviewer_label" and again.speaker_id is None and again.display_speaker == LABEL
    assert TranscriptSegment(id="d", start=0.0, end=1.0, raw_text="t").attribution_basis == "voiceprint", "default basis"

    def _raises(**fields) -> None:
        try:
            TranscriptSegment(**fields)
        except (ValidationError, ValueError):
            return
        raise AssertionError(f"expected a validation error for {fields}")

    # "confirmed" still needs a Person; a voiceprint-based correction too; a reviewer label never carries a Person
    _raises(**base, attribution_state="confirmed", speaker_id=None, attribution_basis="reviewer_label")
    _raises(**base, attribution_state="confirmed", speaker_id=None)
    _raises(**base, attribution_state="corrected", speaker_id=None, attribution_basis="voiceprint")
    _raises(**base, attribution_state="corrected", speaker_id="person-1", attribution_basis="reviewer_label")
    _raises(**{**base, "confirmed_display_name": None}, attribution_state="corrected", speaker_id=None, attribution_basis="reviewer_label")
    # anonymous/suggested segments still forbid every identity field
    _raises(id="a", start=0.0, end=1.0, raw_text="t", attribution_state="anonymous", confirmed_display_name=LABEL)
    # legacy rows still migrate to anonymous
    legacy = TranscriptSegment.model_validate({"id": "l", "start": 0.0, "end": 1.0, "raw_text": "t", "speaker": "Dr. Ceban", "speaker_id": "att-1"})
    assert legacy.attribution_state == "anonymous" and legacy.speaker == "Speaker 1" and legacy.legacy_speaker_label == "Dr. Ceban"
    print("PASS test_segment_invariants_accept_reviewer_label_without_a_person")


if __name__ == "__main__":
    import traceback

    tests = [(n, f) for n, f in list(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
            print("    " + "\n    ".join(traceback.format_exc().strip().splitlines()[-6:]))
    print(f"{len(tests) - failed}/{len(tests)} passed (store: {repository.storage_dir})")
    sys.exit(1 if failed else 0)
