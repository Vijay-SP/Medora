"""
Offline unit tests for the speaker-attribution models (V3), the people / speaker-map stores (V4) and the
biometric file layout (nothing biometric in a JSON store, purge cascades).

    PYTHONPATH=backend .venv\\Scripts\\python.exe backend\\tests\\test_voice_models_and_storage.py

Storage is isolated to a throwaway directory BEFORE any app import (the repository singleton binds DATA_DIR
at import and derived directories do not follow it). No model, no GPU, no network, no SMTP.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_ROOT = Path(tempfile.mkdtemp(prefix="medpark_test_voice_models_"))
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
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

import json  # noqa: E402
import re  # noqa: E402
import sys  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.core.exceptions import ResourceNotFoundError  # noqa: E402
from app.models.extraction import ActionItem, EvidenceQuote  # noqa: E402
from app.models.meeting import Meeting  # noqa: E402
from app.models.person import (  # noqa: E402
    ConsentRecord,
    Person,
    SpeakerAttributionEvent,
    SpeakerMap,
    Voiceprint,
    compute_space_id,
    summarize_person,
)
from app.models.transcript import SpeakerSuggestion, Transcript, TranscriptSegment  # noqa: E402
from app.storage.file_manager import file_manager  # noqa: E402
from app.storage.repository import repository  # noqa: E402

SPACE = compute_space_id("1068e4ac3a76bb9c769e6816ef30bf89363f6e966f1d938210cb8ed4038f8e93", 512)
ANON = re.compile(r"^Speaker \d+$")
# A run of at least 16 comma-separated floats is the signature of an embedding vector serialised into JSON.
FLOAT_VECTOR = re.compile(r"\[\s*-?\d+\.\d+(?:\s*,\s*-?\d+\.\d+){15,}")
AUDIT_TRANSCRIPTS = _REPO_ROOT / ".audit" / "real-run" / "store" / "transcripts.json"


class _Skip(Exception):
    pass


def _skip(reason: str):
    try:
        import pytest

        pytest.skip(reason)
    except ImportError:
        raise _Skip(reason)


def _assert_isolated() -> None:
    assert repository.storage_dir.is_relative_to(_ROOT), f"store not isolated: {repository.storage_dir}"
    assert Path(settings.VOICEPRINTS_DIR).is_relative_to(_ROOT), f"voiceprints not isolated: {settings.VOICEPRINTS_DIR}"


def _raises_value_error(**fields) -> bool:
    base = dict(start=0.0, end=3.0, raw_text="text")
    base.update(fields)
    try:
        TranscriptSegment(**base)
    except ValueError:
        return True
    return False


def _suggestion(name: str = "Dr. Ana Popescu") -> SpeakerSuggestion:
    return SpeakerSuggestion(person_id="p-a", person_name=name, score=0.72, margin=0.30, band="moderate", space_id=SPACE)


# ---------------------------------------------------------------- V3: the four states
def test_anonymous_is_the_default_and_carries_no_identity():
    seg = TranscriptSegment(start=0.0, end=3.0, raw_text="Bună ziua.")
    assert seg.attribution_state == "anonymous"
    assert seg.speaker == "Speaker 1" and ANON.match(seg.speaker)
    assert seg.speaker_id is None and seg.confirmed_display_name is None and seg.confirmed_by is None
    assert seg.suggestion is None and seg.suggested_identity is None
    assert seg.printable_name is False
    assert seg.display_speaker == "Speaker 1"
    # the computed field is serialised, so the UI can rely on it
    assert seg.model_dump(mode="json")["display_speaker"] == "Speaker 1"


def test_suggested_state_requires_a_suggestion_and_no_name_fields():
    seg = TranscriptSegment(
        start=0.0, end=3.0, raw_text="x", speaker="Speaker 2", attribution_state="suggested",
        suggestion=_suggestion(), suggested_identity="Dr. Ana Popescu", speech_seconds=2.6
    )
    assert seg.attribution_state == "suggested"
    assert seg.display_speaker == "Speaker 2", "a suggestion must never surface through display_speaker"
    assert seg.speaker_id is None and seg.confirmed_display_name is None
    assert _raises_value_error(attribution_state="suggested"), "suggested without suggestion must raise"
    assert _raises_value_error(attribution_state="suggested", suggestion=_suggestion(), speaker_id="p-a")
    assert _raises_value_error(attribution_state="suggested", suggestion=_suggestion(), confirmed_display_name="Dr. A")
    assert _raises_value_error(attribution_state="suggested", suggestion=_suggestion(), printable_name=True)


def test_confirmed_and_corrected_require_person_id_and_snapshot():
    now = datetime.now(timezone.utc)
    for state in ("confirmed", "corrected"):
        seg = TranscriptSegment(
            start=0.0, end=6.0, raw_text="x", speaker="Speaker 1", attribution_state=state,
            speaker_id="p-a", confirmed_display_name="Dr. Ana Popescu", confirmed_by="Dr. Rev (Reviewer)",
            confirmed_at=now, confirmed_for_revision=1, speech_seconds=5.5, printable_name=True
        )
        assert seg.attribution_state == state
        assert seg.speaker == "Speaker 1", "the anonymous label survives confirmation"
        assert seg.display_speaker == "Dr. Ana Popescu"
        assert seg.confirmed_at is not None and seg.confirmed_at.tzinfo is not None
        assert _raises_value_error(attribution_state=state, confirmed_display_name="Dr. A"), f"{state} without speaker_id"
        assert _raises_value_error(attribution_state=state, speaker_id="p-a"), f"{state} without display name"
        assert _raises_value_error(attribution_state=state), f"{state} with nothing"


def test_anonymous_rejects_every_identity_field():
    assert _raises_value_error(attribution_state="anonymous", speaker_id="p-a")
    assert _raises_value_error(attribution_state="anonymous", confirmed_display_name="Dr. A")
    assert _raises_value_error(attribution_state="anonymous", confirmed_by="Dr. Rev (Reviewer)")
    assert _raises_value_error(attribution_state="anonymous", printable_name=True)
    # a free-text speaker label is how an unconfirmed name would be laundered into the document
    assert _raises_value_error(attribution_state="anonymous", speaker="Dr. Ceban")
    assert _raises_value_error(attribution_state="anonymous", speaker="speaker 1")
    assert _raises_value_error(attribution_state="anonymous", speaker="Speaker 1 ")


def test_display_speaker_honours_the_printable_floor():
    """A confirmed segment prints its name only when the handler marked it printable (>= 2.0 s of speech)."""
    common = dict(start=0.0, end=1.2, raw_text="Да.", speaker="Speaker 3", attribution_state="confirmed",
                  speaker_id="p-a", confirmed_display_name="Dr. Ana Popescu", confirmed_by="Dr. Rev (Reviewer)")
    short = TranscriptSegment(**common, speech_seconds=0.9, printable_name=False)
    assert short.display_speaker == "Speaker 3", "a 0.9 s 'Да.' inside a confirmed cluster must stay anonymous"
    assert short.speaker_id == "p-a", "eligibility is kept on the segment even when the name does not print"
    long_ = TranscriptSegment(**{**common, "end": 6.0}, speech_seconds=5.2, printable_name=True)
    assert long_.display_speaker == "Dr. Ana Popescu"
    assert float(settings.SPEAKER_MIN_PRINTABLE_SPEECH_S) == 2.0

    transcript = Transcript(meeting_id="m", segments=[short, long_])
    plain = transcript.to_full_text()
    assert "Dr. Ana Popescu" not in plain, "to_full_text() without the kwarg must stay anonymous forever"
    named = transcript.to_full_text(use_display_names=True)
    assert "Speaker 3: Да." in named and "Dr. Ana Popescu:" in named
    lines, ids = transcript.to_indexed_lines()
    assert all("Popescu" not in line for line in lines), "confirmed names must never reach the LLM prompt"
    assert ids == [short.id, long_.id]


# ---------------------------------------------------------------- V3: legacy migration
def test_legacy_rows_migrate_to_anonymous_idempotently():
    legacy = {"id": "abc12345", "start": 0.0, "end": 4.5, "speaker": "Dr. Ceban", "speaker_id": "att-77",
              "suggested_identity": "Dr. Ceban", "raw_text": "Bună ziua, începem ședința.", "language": "ro",
              "confidence": 0.9, "is_flagged": False, "flag_reason": None, "corrected_text": None}
    seg = TranscriptSegment.model_validate(legacy)
    assert seg.attribution_state == "anonymous"
    assert seg.speaker == "Speaker 1" and seg.legacy_speaker_label == "Dr. Ceban"
    assert seg.speaker_id is None and seg.legacy_speaker_id == "att-77"
    assert seg.display_speaker == "Speaker 1"
    # already-anonymous legacy rows keep their label and gain no legacy fields
    plain = TranscriptSegment.model_validate({"start": 1.0, "end": 2.0, "speaker": "Speaker 2", "raw_text": "Да."})
    assert plain.speaker == "Speaker 2" and plain.legacy_speaker_label is None and plain.legacy_speaker_id is None
    # idempotent: a migrated row round-trips through JSON unchanged
    dumped = seg.model_dump(mode="json")
    again = TranscriptSegment.model_validate(dumped)
    assert again.model_dump(mode="json") == dumped
    assert TranscriptSegment.model_validate(json.loads(json.dumps(dumped))).legacy_speaker_label == "Dr. Ceban"


def test_every_audit_transcript_loads_anonymous():
    """Transcripts persisted before attribution existed must load with no name anywhere."""
    if not AUDIT_TRANSCRIPTS.is_file():
        _skip(f"no stored transcripts at {AUDIT_TRANSCRIPTS}")
    data = json.loads(AUDIT_TRANSCRIPTS.read_text(encoding="utf-8"))
    assert data, "the audit store is empty"
    total = 0
    for meeting_id, raw in data.items():
        transcript = Transcript.model_validate(raw)
        assert transcript.meeting_id == meeting_id
        for seg in transcript.segments:
            total += 1
            assert seg.attribution_state == "anonymous", (meeting_id, seg.id, seg.attribution_state)
            assert ANON.match(seg.speaker), (meeting_id, seg.id, seg.speaker)
            assert seg.speaker_id is None and seg.confirmed_display_name is None
            assert seg.printable_name is False and seg.display_speaker == seg.speaker
        assert "Speaker" in transcript.to_full_text()
    assert total > 0


# ---------------------------------------------------------------- extraction model extensions
def test_extraction_models_carry_confirmed_speaker_provenance():
    quote = EvidenceQuote(segment_id="s1", start=0.0, end=3.0, quote="Aprobăm.", speaker="Speaker 1")
    assert quote.speaker_person_id is None and quote.speaker_is_confirmed is False
    item = ActionItem(task="t", owner="Dr. Ana Popescu", owner_source="confirmed_speaker", evidence=[quote])
    assert item.owner_source == "confirmed_speaker"
    try:
        ActionItem(task="t", owner_source="voiceprint")
        assert False, "unknown owner_source must be rejected"
    except ValueError:
        pass


# ---------------------------------------------------------------- V2/V4: people store
def _person(name: str = "Dr. Ana Popescu", enrolled: bool = False, space_id: str = SPACE) -> Person:
    person = Person(full_name=name, role="Chirurg", email="ana.popescu@medpark.md",
                    consent=ConsentRecord(given=True, given_at=datetime.now(timezone.utc)))
    if enrolled:
        vp_id = str(uuid.uuid4())
        person.voiceprints.append(Voiceprint(
            id=vp_id, space_id=space_id, model_sha256="1068e4ac3a76" + "0" * 52, dim=512,
            artifact_path=f"people/{person.id}/{vp_id}.npy", sample_count=3, total_speech_seconds=24.0, cohesion=0.81
        ))
    return person


def test_people_crud_and_summary_states():
    _assert_isolated()
    person = _person(enrolled=True)
    saved = repository.save_person(person)
    assert saved.id == person.id
    assert (repository.storage_dir / "people.json").is_file()
    loaded = repository.get_person(person.id)
    assert loaded is not None and loaded.full_name == "Dr. Ana Popescu" and len(loaded.voiceprints) == 1
    assert loaded.voiceprints[0].enrolled_at.tzinfo is not None
    assert any(p.id == person.id for p in repository.list_people())

    inactive = _person(name="Dr. Fost Angajat")
    inactive.is_active = False
    repository.save_person(inactive)
    assert all(p.id != inactive.id for p in repository.list_people())
    assert any(p.id == inactive.id for p in repository.list_people(include_inactive=True))

    assert summarize_person(loaded, SPACE).state == "enrolled"
    assert summarize_person(loaded, compute_space_id("f" * 64, 512)).state == "needs_reenrollment"
    assert summarize_person(_person(), SPACE).state == "not_enrolled"
    summary = summarize_person(loaded, SPACE)
    assert summary.person_name == "Dr. Ana Popescu" and summary.sample_count == 3 and summary.total_sample_seconds == 24.0
    assert summary.embedding_model == "campplus-LM" and summary.consent_given_at is not None
    assert "artifact_path" not in summary.model_dump() and "voiceprints" not in summary.model_dump()

    assert repository.delete_person(person.id) is True
    assert repository.get_person(person.id) is None
    assert repository.delete_person(person.id) is False
    assert repository.get_person("does-not-exist") is None


def test_speaker_map_store_round_trip():
    _assert_isolated()
    meeting_id = str(uuid.uuid4())
    assert repository.get_speaker_map(meeting_id) is None
    event = SpeakerAttributionEvent(
        meeting_id=meeting_id, cluster_id="SPEAKER_01", action="confirm", person_id="p-a",
        person_name_snapshot="Dr. Ana Popescu", score_at_decision=0.72, margin_at_decision=0.3, space_id=SPACE,
        reviewer="Dr. Rev (Reviewer)", segment_ids=["a1", "a2"]
    )
    repository.save_speaker_map(SpeakerMap(meeting_id=meeting_id, space_id=SPACE, events=[event]))
    assert (repository.storage_dir / "speaker_maps.json").is_file()
    loaded = repository.get_speaker_map(meeting_id)
    assert loaded is not None and loaded.space_id == SPACE and len(loaded.events) == 1
    assert loaded.events[0].action == "confirm" and loaded.events[0].timestamp.tzinfo is not None
    assert loaded.events[0].segment_ids == ["a1", "a2"]
    loaded.events.append(SpeakerAttributionEvent(meeting_id=meeting_id, cluster_id="SPEAKER_01", action="reject", reviewer="x"))
    repository.save_speaker_map(loaded)
    assert len(repository.get_speaker_map(meeting_id).events) == 2


# ---------------------------------------------------------------- biometric files and purge cascades
def test_biometric_paths_are_validated_and_live_under_voiceprints_dir():
    _assert_isolated()
    person_id = str(uuid.uuid4())
    vp_path = file_manager.get_voiceprint_path(person_id, "vp-1")
    sample_path = file_manager.get_enrollment_sample_path(person_id, 0)
    npy_path, sidecar_path = file_manager.get_segment_embedding_paths("meeting-1")
    root = Path(settings.VOICEPRINTS_DIR).resolve()
    for p in (vp_path, sample_path, npy_path, sidecar_path):
        assert p.resolve().is_relative_to(root), p
    assert vp_path.suffix == ".npy" and sample_path.suffix == ".wav"
    assert npy_path.suffix == ".npy" and sidecar_path.suffix == ".json"
    for bad in ("../evil", "a/b", "", "x" * 65, "p;rm"):
        for call in (lambda: file_manager.get_voiceprint_path(bad, "vp-1"),
                     lambda: file_manager.get_voiceprint_path(person_id, bad),
                     lambda: file_manager.get_enrollment_sample_path(bad, 0),
                     lambda: file_manager.get_segment_embedding_paths(bad),
                     lambda: file_manager.purge_person_biometrics(bad),
                     lambda: file_manager.purge_meeting_embeddings(bad)):
            try:
                call()
                assert False, f"unsafe id {bad!r} was accepted"
            except ResourceNotFoundError:
                pass


def test_purge_person_biometrics_removes_every_file():
    _assert_isolated()
    person_id = str(uuid.uuid4())
    vp_path = file_manager.get_voiceprint_path(person_id, "vp-1")
    vp_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(vp_path, np.ones(512, dtype=np.float32))
    for i in range(2):
        sample = file_manager.get_enrollment_sample_path(person_id, i)
        sample.parent.mkdir(parents=True, exist_ok=True)
        sample.write_bytes(b"RIFF" + b"\0" * 64)
    assert file_manager.purge_person_biometrics(person_id) == 3
    assert not vp_path.exists() and not vp_path.parent.exists()
    assert file_manager.purge_person_biometrics(person_id) == 0


def test_save_embedding_matrix_and_meeting_purge_cascade():
    _assert_isolated()
    meeting = Meeting(title="Ședință cascadă embeddings")
    repository.save_meeting(meeting)
    npy_path, sidecar_path = file_manager.get_segment_embedding_paths(meeting.id)
    matrix = np.random.default_rng(1).standard_normal((4, 512)).astype(np.float32)
    digest = file_manager.save_embedding_matrix(npy_path, matrix)
    assert re.fullmatch(r"[0-9a-f]{64}", digest) and digest == file_manager.compute_sha256(npy_path)
    assert np.array_equal(np.load(npy_path), matrix)
    sidecar_path.write_text(json.dumps({"segment_ids": ["a", "b", "c", "d"], "space_id": SPACE,
                                        "model_sha256": "1068e4ac3a76", "sha256": digest}), encoding="utf-8")
    assert repository.delete_meeting(meeting.id) is True
    assert not npy_path.exists() and not sidecar_path.exists(), "delete_meeting must purge cached embeddings"
    assert file_manager.purge_meeting_embeddings(meeting.id) == 0


def test_no_json_store_ever_contains_a_float_vector():
    _assert_isolated()
    person = _person(name="Dr. Vector Test", enrolled=True)
    vp = person.voiceprints[0]
    vp_path = file_manager.get_voiceprint_path(person.id, vp.id)
    assert str(vp_path.relative_to(settings.VOICEPRINTS_DIR)).replace("\\", "/") == vp.artifact_path
    vp_path.parent.mkdir(parents=True, exist_ok=True)
    vector = np.random.default_rng(2).standard_normal(512).astype(np.float32)
    np.save(vp_path, vector / np.linalg.norm(vector))
    repository.save_person(person)
    meeting = Meeting(title="Ședință fără vectori în JSON")
    repository.save_meeting(meeting)
    seg = TranscriptSegment(start=0.0, end=4.0, raw_text="x", cluster_id="SPEAKER_01", speech_seconds=3.5,
                            attribution_state="suggested", suggestion=_suggestion(), suggested_identity="Dr. Ana Popescu")
    repository.save_transcript(Transcript(meeting_id=meeting.id, segments=[seg]))
    repository.save_speaker_map(SpeakerMap(meeting_id=meeting.id, space_id=SPACE))

    stores = sorted(repository.storage_dir.glob("*.json"))
    assert {p.name for p in stores} >= {"people.json", "speaker_maps.json", "transcripts.json", "meetings.json"}
    for store in stores:
        text = store.read_text(encoding="utf-8")
        assert not FLOAT_VECTOR.search(text), f"{store.name} contains a float vector"
        assert ".npy" not in text or store.name == "people.json", f"{store.name} references an artifact"
    # the only place the vector exists is the .npy under VOICEPRINTS_DIR
    assert vp_path.is_file() and Path(settings.VOICEPRINTS_DIR).resolve() not in repository.storage_dir.resolve().parents


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
