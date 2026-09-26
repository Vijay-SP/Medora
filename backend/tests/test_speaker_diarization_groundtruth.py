"""
Ground-truth speaker test built from the two offline Windows SAPI voices (zero annotation effort).

    PYTHONPATH=backend .venv\\Scripts\\python.exe backend\\tests\\test_speaker_diarization_groundtruth.py

"Microsoft David Desktop" and "Microsoft Zira Desktop" are rendered through System.Speech at 16 kHz mono
PCM16, trimmed and concatenated into a two-speaker meeting whose turn boundaries and speakers are therefore
known exactly. The diarizer (Silero VAD + CAM++ on CPU, no GPU) must recover them; enrolling both voices from
separate prompted sentences must yield the right suggestions; an unenrolled voice must get none; and the
confirm write path must respect the printable floor and never touch the other cluster.

Skips cleanly when SAPI (PowerShell/System.Speech) or the ONNX model is unavailable. Storage is isolated
before any app import; no SMTP, no Ollama, no Whisper.

CAUTION: TTS voices are clean and consistent. Passing proves the wiring, not far-field meeting-room accuracy.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_ROOT = Path(tempfile.mkdtemp(prefix="medpark_test_diar_gt_"))
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
os.environ["ALLOW_AUTO_CONFIRM_SPEAKERS"] = "false"
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

import json  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import uuid  # noqa: E402
from collections import defaultdict  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from typing import Optional  # noqa: E402

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.models.extraction import ActionItem, EvidenceQuote, MinutesOfMeeting  # noqa: E402
from app.models.meeting import Meeting, ProcessingStatus, ReviewStatus, WorkflowMode  # noqa: E402
from app.models.person import ConsentRecord, Person  # noqa: E402
from app.models.transcript import Transcript, TranscriptSegment  # noqa: E402
from app.services.diarization.embedder import speaker_embedder  # noqa: E402
from app.services.diarization.speaker_engine import diarization_engine  # noqa: E402
from app.services.documents.generator import document_generator  # noqa: E402
from app.storage.file_manager import file_manager  # noqa: E402
from app.storage.repository import repository  # noqa: E402

SR = 16000
GAP_S = 0.8
VOICES = {"david": "Microsoft David Desktop", "zira": "Microsoft Zira Desktop"}
NAMES = {"david": "David Voice", "zira": "Zira Voice"}
SHORT_TURN_TEXT = "Yes, okay."
SHORT_TURN_SECONDS = 1.0  # the segment handed to the diarizer is cut to exactly this length

MEETING_TURNS = [
    ("david", "Good morning everyone, let us start with the report from the intensive care unit."),
    ("zira", "The unit admitted four new patients overnight and two of them remain on ventilation."),
    ("david", "Has the antibiotic protocol been updated according to the last committee decision?"),
    ("zira", "Yes, the pharmacy confirmed the new dosing schedule and the nurses were briefed yesterday."),
    ("david", SHORT_TURN_TEXT),
    ("zira", "We still need approval for the additional monitoring equipment before the end of the month."),
    ("david", "I will prepare the purchase request and send it to the financial department on Friday."),
    ("zira", "Please include the maintenance contract, the previous one expired in August."),
    ("david", "Noted, and the surgical department asked for a review of the discharge procedure."),
    ("zira", "We can schedule that review for the next meeting together with the quality indicators."),
    ("david", "Agreed, then let us close the session and record the decisions in the minutes."),
    ("zira", "Thank you all, the summary will be circulated after the review is complete."),
]
ENROLL_PROMPTS = {
    "david": [
        "My name is David and I am recording this sample for voice enrollment in the hospital meeting system. Today is a regular working day.",
        "The recording takes place in a quiet office with the laptop microphone, and the purpose is only to recognise my voice in future meetings.",
        "Numbers are useful for enrollment: one, two, three, four, five, six, seven, eight, nine, ten, and back to one again slowly.",
    ],
    "zira": [
        "My name is Zira and I am recording this sample for voice enrollment in the hospital meeting system. Today is a regular working day.",
        "The recording takes place in a quiet office with the laptop microphone, and the purpose is only to recognise my voice in future meetings.",
        "Numbers are useful for enrollment: one, two, three, four, five, six, seven, eight, nine, ten, and back to one again slowly.",
    ],
}

_FIXTURE: Optional[dict] = None
_TTS_ERROR: Optional[str] = None


class _Skip(Exception):
    pass


def _skip(reason: str):
    try:
        import pytest

        pytest.skip(reason)
    except ImportError:
        raise _Skip(reason)


# ---------------------------------------------------------------- SAPI synthesis
def synthesize(items: list[dict], out_dir: Path) -> None:
    """Renders {voice, text, path} items to 16 kHz mono PCM16 WAV through System.Speech (PowerShell)."""
    spec_path = out_dir / "tts_spec.json"
    spec_path.write_text(json.dumps(items), encoding="utf-8")
    script = r"""
Add-Type -AssemblyName System.Speech
$items = Get-Content -Raw -Encoding UTF8 $args[0] | ConvertFrom-Json
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
foreach ($it in $items) {
  $s = New-Object System.Speech.Synthesis.SpeechSynthesizer
  $s.SelectVoice($it.voice)
  $s.Rate = 0
  $s.SetOutputToWaveFile($it.path, $fmt)
  $s.Speak($it.text)
  $s.Dispose()
}
"""
    script_path = out_dir / "tts.ps1"
    script_path.write_text(script, encoding="utf-8")
    cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script_path), str(spec_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(f"TTS synthesis failed: {proc.stdout[-400:]} {proc.stderr[-400:]}")
    for item in items:
        path = Path(item["path"])
        if not path.is_file() or path.stat().st_size < 1000:
            raise RuntimeError(f"TTS produced no audio for {path}")


def _read(path: Path) -> np.ndarray:
    data, sr = sf.read(str(path), dtype="float32")
    if sr != SR:
        raise RuntimeError(f"unexpected sample rate {sr} for {path}")
    if data.ndim == 2:
        data = data.mean(axis=1)
    return np.ascontiguousarray(data, dtype=np.float32)


def _trim(x: np.ndarray, threshold: float = 0.01, margin_s: float = 0.05) -> np.ndarray:
    loud = np.flatnonzero(np.abs(x) > threshold)
    if len(loud) == 0:
        return x
    margin = int(margin_s * SR)
    return x[max(0, loud[0] - margin): min(len(x), loud[-1] + margin)]


def _fixture() -> dict:
    """Synthesises everything once: the two-voice meeting wav with exact turn bounds and the enrollment samples."""
    global _FIXTURE, _TTS_ERROR
    if _FIXTURE is not None:
        return _FIXTURE
    if _TTS_ERROR is not None:
        _skip(_TTS_ERROR)
    if not speaker_embedder.available:
        _TTS_ERROR = f"speaker embedder unavailable: {speaker_embedder.load_error}"
        _skip(_TTS_ERROR)
    tts_dir = _ROOT / "tts"
    tts_dir.mkdir(parents=True, exist_ok=True)
    items = []
    for i, (voice, text) in enumerate(MEETING_TURNS):
        items.append({"voice": VOICES[voice], "text": text, "path": str(tts_dir / f"turn_{i:02d}_{voice}.wav")})
    for voice, prompts in ENROLL_PROMPTS.items():
        for j, text in enumerate(prompts):
            items.append({"voice": VOICES[voice], "text": text, "path": str(tts_dir / f"enroll_{voice}_{j}.wav")})
    try:
        synthesize(items, tts_dir)
    except Exception as exc:  # noqa: BLE001
        _TTS_ERROR = f"SAPI synthesis unavailable: {exc}"
        _skip(_TTS_ERROR)

    pieces = [np.zeros(int(GAP_S * SR), dtype=np.float32)]
    cursor = GAP_S
    turns = []
    for i, (voice, text) in enumerate(MEETING_TURNS):
        clip = _trim(_read(tts_dir / f"turn_{i:02d}_{voice}.wav"))
        if text == SHORT_TURN_TEXT:
            clip = clip[: int(SHORT_TURN_SECONDS * SR)]
        start = cursor
        end = cursor + len(clip) / SR
        pieces.append(clip)
        pieces.append(np.zeros(int(GAP_S * SR), dtype=np.float32))
        turns.append({"voice": voice, "text": text, "start": round(start, 3), "end": round(end, 3)})
        cursor = end + GAP_S
    meeting_wav = np.concatenate(pieces)
    meeting_path = _ROOT / "uploads" / "groundtruth_meeting_16k.wav"
    meeting_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(meeting_path), meeting_wav, SR, subtype="PCM_16")

    samples = {voice: [tts_dir / f"enroll_{voice}_{j}.wav" for j in range(len(prompts))] for voice, prompts in ENROLL_PROMPTS.items()}
    _FIXTURE = {"meeting_path": meeting_path, "turns": turns, "samples": samples, "duration": len(meeting_wav) / SR}
    return _FIXTURE


def _segments_from_turns(turns: list[dict]) -> list[TranscriptSegment]:
    """ASR-like segments: one per turn, with 50 ms slop; the diarizer only sees start/end/text."""
    segments = []
    for turn in turns:
        segments.append(TranscriptSegment(
            id=uuid.uuid4().hex[:8], start=max(0.0, turn["start"] - 0.05), end=turn["end"] + 0.05,
            raw_text=turn["text"], language="en",
        ))
    return segments


def _split_first_long_turn(turns: list[dict], voice: str, head_seconds: float = 1.0) -> list[dict]:
    """
    ASR regularly cuts a continuous turn into a sub-second fragment plus the rest ("Да." / "Okay, so").
    Splits the first long turn of `voice` into a head of `head_seconds` and a tail so the fixture contains
    a 1.0 s segment INSIDE a long speaker's cluster (the standalone short turn forms its own cluster).
    """
    out = []
    done = False
    for turn in turns:
        if not done and turn["voice"] == voice and turn["text"] != SHORT_TURN_TEXT and turn["end"] - turn["start"] > 4.0:
            cut = round(turn["start"] + head_seconds, 3)
            words = turn["text"].split()
            out.append({**turn, "end": cut, "text": " ".join(words[:2])})
            out.append({**turn, "start": cut, "text": " ".join(words[2:])})
            done = True
        else:
            out.append(turn)
    assert done, f"no long {voice} turn to split"
    return out


def _diarize(
    people: Optional[list[Person]] = None,
    meeting_id: Optional[str] = None,
    turns: Optional[list[dict]] = None,
) -> tuple[list[TranscriptSegment], list[dict]]:
    fx = _fixture()
    turns = turns if turns is not None else fx["turns"]
    segments = _segments_from_turns(turns)
    out = diarization_engine.assign_speakers(fx["meeting_path"], segments, None, meeting_id=meeting_id, people=people or [])
    assert len(out) == len(turns)
    return out, turns


def _cluster_speech(segments: list[TranscriptSegment]) -> dict[str, float]:
    speech: dict[str, float] = defaultdict(float)
    for seg in segments:
        speech[seg.cluster_id or "NONE"] += float(seg.speech_seconds or 0.0)
    return dict(speech)


def _cluster_to_voice(segments: list[TranscriptSegment], turns: list[dict]) -> dict[str, str]:
    """Majority (by speech time) ground-truth voice of each cluster."""
    tally: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for seg, turn in zip(segments, turns):
        tally[seg.cluster_id or "NONE"][turn["voice"]] += float(seg.speech_seconds or 0.0) or 0.001
    return {cluster: max(v.items(), key=lambda kv: kv[1])[0] for cluster, v in tally.items()}


def _dominant_clusters(segments: list[TranscriptSegment]) -> list[str]:
    ranked = sorted(_cluster_speech(segments).items(), key=lambda kv: -kv[1])
    return [cluster for cluster, _ in ranked[:2]]


def _enroll(voice: str) -> Person:
    """Explicit enrollment from prompted samples (never from meeting audio), stored like the people API does."""
    from app.services.diarization.enrollment import assess_sample, build_voiceprint

    fx = _fixture()
    person = Person(full_name=NAMES[voice], role="Medic", email=f"{voice}@example.invalid",
                    consent=ConsentRecord(given=True, given_at=datetime.now(timezone.utc)))
    for path in fx["samples"][voice]:
        quality = assess_sample(_read(path))
        assert quality.verdict in ("good", "usable"), f"{path.name}: {quality.verdict} {quality.reasons}"
        assert quality.speech_seconds >= settings.SPEAKER_MIN_SAMPLE_SPEECH_S
    voiceprint, embeddings = build_voiceprint(person.id, list(fx["samples"][voice]))
    assert voiceprint.space_id == speaker_embedder.space_id and voiceprint.dim == speaker_embedder.dim
    assert voiceprint.sample_count == len(fx["samples"][voice])
    assert voiceprint.total_speech_seconds >= settings.SPEAKER_MIN_ENROLL_SPEECH_S, voiceprint.total_speech_seconds
    assert voiceprint.cohesion is not None and voiceprint.cohesion >= settings.SPEAKER_MIN_COHESION, voiceprint.cohesion
    vector = np.asarray(embeddings, dtype=np.float32)
    if vector.ndim == 2:
        vector = vector.mean(axis=0)
    vector = vector / max(float(np.linalg.norm(vector)), 1e-12)
    artifact = file_manager.get_voiceprint_path(person.id, voiceprint.id)
    file_manager.save_embedding_matrix(artifact, vector)
    voiceprint.artifact_path = artifact.relative_to(settings.VOICEPRINTS_DIR).as_posix()
    voiceprint.is_active = True
    person.voiceprints = [voiceprint]
    repository.save_person(person)
    return person


# ---------------------------------------------------------------- anonymous diarization
def test_two_sapi_voices_are_recovered_with_at_least_95_percent_segment_accuracy():
    segments, turns = _diarize()
    mapping = _cluster_to_voice(segments, turns)
    correct = sum(1 for seg, turn in zip(segments, turns) if mapping.get(seg.cluster_id) == turn["voice"])
    accuracy = correct / len(segments)
    print(f"    segment-cluster accuracy {accuracy:.3f} ({correct}/{len(segments)}); clusters={_cluster_speech(segments)}")
    assert accuracy >= 0.95, f"accuracy {accuracy:.3f}"
    for seg in segments:
        assert seg.attribution_state == "anonymous" and seg.suggestion is None and seg.speaker_id is None
        assert seg.cluster_id and seg.cluster_id.startswith("SPEAKER_") and seg.speaker.startswith("Speaker ")
        assert seg.speech_seconds is not None and seg.speech_seconds >= 0.0
        assert seg.display_speaker == seg.speaker
    assert segments[0].speaker == "Speaker 1", "numbered by first appearance"


def test_two_dominant_clusters_map_to_the_two_voices():
    segments, turns = _diarize()
    speech = _cluster_speech(segments)
    dominant = _dominant_clusters(segments)
    assert len(dominant) == 2, speech
    share = sum(speech[c] for c in dominant) / max(sum(speech.values()), 1e-9)
    assert share >= 0.90, f"top-2 clusters hold only {share:.0%} of the speech: {speech}"
    mapping = _cluster_to_voice(segments, turns)
    assert {mapping[dominant[0]], mapping[dominant[1]]} == {"david", "zira"}
    assert not any(seg.is_flagged and seg.flag_reason and "mid-segment" in seg.flag_reason for seg in segments), "clean turns must not straddle"


def test_short_turn_carries_less_speech_than_the_printable_floor():
    segments, turns = _diarize()
    short = [seg for seg, turn in zip(segments, turns) if turn["text"] == SHORT_TURN_TEXT]
    assert len(short) == 1
    assert short[0].end - short[0].start <= SHORT_TURN_SECONDS + 0.11
    assert short[0].speech_seconds is not None and short[0].speech_seconds < settings.SPEAKER_MIN_PRINTABLE_SPEECH_S
    long_turns = [seg for seg, turn in zip(segments, turns) if turn["text"] != SHORT_TURN_TEXT]
    assert all((seg.speech_seconds or 0.0) >= settings.SPEAKER_MIN_PRINTABLE_SPEECH_S for seg in long_turns)


# ---------------------------------------------------------------- enrollment + suggestions
def test_enrolling_both_voices_yields_correct_suggestions_with_margin():
    david, zira = _enroll("david"), _enroll("zira")
    segments, turns = _diarize(people=[david, zira])
    mapping = _cluster_to_voice(segments, turns)
    expected_name = {"david": NAMES["david"], "zira": NAMES["zira"]}
    dominant = _dominant_clusters(segments)
    checked = 0
    for seg in segments:
        if seg.cluster_id not in dominant:
            continue
        checked += 1
        assert seg.attribution_state == "suggested" and seg.suggestion is not None, (seg.cluster_id, seg.raw_text)
        assert seg.suggestion.person_name == expected_name[mapping[seg.cluster_id]], (seg.suggestion, mapping[seg.cluster_id])
        assert seg.suggested_identity == seg.suggestion.person_name
        assert seg.suggestion.margin >= settings.SPEAKER_MATCH_MIN_MARGIN and seg.suggestion.score >= settings.SPEAKER_MATCH_MIN_SCORE
        assert seg.suggestion.band in ("strong", "moderate", "weak") and seg.suggestion.space_id == speaker_embedder.space_id
        assert seg.speaker_id is None and seg.confirmed_display_name is None and seg.printable_name is False
        assert seg.display_speaker == seg.speaker, "a suggestion never prints"
    assert checked >= len(segments) - 2
    scores = sorted({seg.suggestion.score for seg in segments if seg.suggestion})
    print(f"    suggestion scores {scores[0]:.3f}..{scores[-1]:.3f}")


def test_unenrolled_voice_gets_no_suggestion():
    david = _enroll("david")
    segments, turns = _diarize(people=[david])
    mapping = _cluster_to_voice(segments, turns)
    for seg in segments:
        if seg.cluster_id not in _dominant_clusters(segments):
            continue
        if mapping[seg.cluster_id] == "zira":
            assert seg.attribution_state == "anonymous" and seg.suggestion is None, f"unenrolled Zira got {seg.suggestion}"
        else:
            assert seg.suggestion is not None and seg.suggestion.person_name == NAMES["david"]


def test_auto_confirm_speakers_when_flag_enabled():
    """When ALLOW_AUTO_CONFIRM_SPEAKERS is enabled, high-confidence matches are auto-confirmed directly."""
    david, zira = _enroll("david"), _enroll("zira")
    old_flag = settings.ALLOW_AUTO_CONFIRM_SPEAKERS
    try:
        settings.ALLOW_AUTO_CONFIRM_SPEAKERS = True
        segments, turns = _diarize(people=[david, zira])
        mapping = _cluster_to_voice(segments, turns)
        expected_name = {"david": NAMES["david"], "zira": NAMES["zira"]}
        dominant = _dominant_clusters(segments)
        confirmed_count = 0
        for seg in segments:
            if seg.cluster_id not in dominant:
                continue
            assert seg.attribution_state == "confirmed", f"expected confirmed, got {seg.attribution_state}"
            assert seg.confirmed_display_name == expected_name[mapping[seg.cluster_id]]
            assert seg.confirmed_by == "Auto Voice Match (CAM++)"
            assert seg.suggestion is not None
            assert seg.suggestion.score >= 0.70
            confirmed_count += 1
        assert confirmed_count >= len(segments) - 2
    finally:
        settings.ALLOW_AUTO_CONFIRM_SPEAKERS = old_flag


# ---------------------------------------------------------------- confirm write path on the real diarization
def test_confirming_cluster_a_respects_the_floor_and_never_touches_cluster_b():
    from fastapi.testclient import TestClient
    from app.main import app

    david, zira = _enroll("david"), _enroll("zira")
    meeting = Meeting(title="Ground-truth two-voice meeting", workflow_mode=WorkflowMode.SUPERVISED,
                      processing_status=ProcessingStatus.COMPLETED, processing_progress=100,
                      review_status=ReviewStatus.PENDING_REVIEW, current_revision=1,
                      distribution_list=["outbox@example.invalid"])
    repository.save_meeting(meeting)
    turns = _split_first_long_turn(_fixture()["turns"], "david", head_seconds=SHORT_TURN_SECONDS)
    segments, turns = _diarize(people=[david, zira], meeting_id=meeting.id, turns=turns)
    matrix_path, sidecar_path = file_manager.get_segment_embedding_paths(meeting.id)
    assert matrix_path.is_file() and sidecar_path.is_file(), "the diarizer caches the segment embeddings"
    transcript = Transcript(meeting_id=meeting.id, segments=segments)
    transcript.compute_stats()
    repository.save_transcript(transcript)
    mapping = _cluster_to_voice(segments, turns)
    cluster_a = next(c for c in _dominant_clusters(segments) if mapping[c] == "david")
    cluster_b = next(c for c in _dominant_clusters(segments) if mapping[c] == "zira")
    label_a = next(seg.speaker for seg in segments if seg.cluster_id == cluster_a)
    long_a = next(seg for seg in segments if seg.cluster_id == cluster_a and (seg.speech_seconds or 0) >= 4.0)
    # the 1.0 s head fragment of David's first long turn: inside cluster A, below the printable floor
    short_a = next(seg for seg in segments if seg.cluster_id == cluster_a and (seg.end - seg.start) <= SHORT_TURN_SECONDS + 0.11)
    assert short_a.speech_seconds is not None and short_a.speech_seconds < settings.SPEAKER_MIN_PRINTABLE_SPEECH_S

    minutes = MinutesOfMeeting(
        meeting_id=meeting.id, title=meeting.title, meeting_type="medical", summary_ro="Rezumat de test.",
        action_items=[ActionItem(id="act-long", task="Purchase request.", owner=label_a, owner_source="speaker",
                                 evidence=[EvidenceQuote(segment_id=long_a.id, start=long_a.start, end=long_a.end, quote=long_a.raw_text, speaker=label_a)]),
                      ActionItem(id="act-short", task="Acknowledgement.", owner=label_a, owner_source="speaker",
                                 evidence=[EvidenceQuote(segment_id=short_a.id, start=short_a.start, end=short_a.end, quote=short_a.raw_text, speaker=label_a)])],
        model_version="test-fixture",
    )
    pdf_path, docx_path = file_manager.get_export_paths(meeting.id, revision=1)
    document_generator.generate_all(meeting, minutes, pdf_path, docx_path)
    minutes.pdf_path, minutes.docx_path = str(pdf_path), str(docx_path)
    repository.save_minutes(minutes)
    before_b = {seg.id: seg.model_dump(mode="json") for seg in segments if seg.cluster_id == cluster_b}

    with TestClient(app) as client:
        listing = client.get(f"/api/v1/meetings/{meeting.id}/speakers")
        assert listing.status_code == 200, listing.text
        cards = {c["cluster_id"]: c for c in listing.json()["clusters"]}
        assert cards[cluster_a]["suggested_name"] == NAMES["david"] and cards[cluster_b]["suggested_name"] == NAMES["zira"]
        assert cards[cluster_a]["blocking_reasons"] == [], cards[cluster_a]["blocking_reasons"]
        assert cards[cluster_a]["unprintable_turns"] >= 1
        res = client.post(f"/api/v1/meetings/{meeting.id}/speakers/{cluster_a}/confirm",
                          json={"action": "confirm", "profile_id": david.id, "expected_revision": 1,
                                "reviewer_name": "Dr. Rev", "reviewer_role": "Reviewer"})
        assert res.status_code == 200, res.text
        assert res.json()["state"] == "confirmed" and res.json()["confirmed_name"] == NAMES["david"]

    stored = {seg.id: seg for seg in repository.get_transcript(meeting.id).segments}
    assert stored[long_a.id].attribution_state == "confirmed" and stored[long_a.id].printable_name is True
    assert stored[long_a.id].display_speaker == NAMES["david"] and stored[long_a.id].speaker == label_a
    assert stored[short_a.id].attribution_state == "confirmed" and stored[short_a.id].speaker_id == david.id
    assert stored[short_a.id].printable_name is False and stored[short_a.id].display_speaker == label_a, "1.0 s segment must not print"
    for seg_id, snapshot in before_b.items():
        assert stored[seg_id].model_dump(mode="json") == snapshot, f"cluster B segment {seg_id} changed"
    actions = {item.id: item for item in repository.get_minutes(meeting.id).action_items}
    assert actions["act-long"].owner == NAMES["david"] and actions["act-long"].owner_source == "confirmed_speaker"
    assert actions["act-short"].owner == label_a and actions["act-short"].owner_source == "speaker"
    assert NAMES["zira"] not in repository.get_transcript(meeting.id).to_full_text(use_display_names=True)


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
    print(f"{len(tests) - failed}/{len(tests)} passed (root: {_ROOT})")
    sys.exit(1 if failed else 0)
