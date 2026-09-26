"""
Offline tests for FasterWhisperEngine's per-window code-switching decode (contracts K3/K6).

No CUDA and no WhisperModel: a FakeModel stands in for faster-whisper's model object and exposes only the
seams the engine's windowed strategy touches (feature_extractor, encode, model.detect_language,
model.is_multilingual, hf_tokenizer, generate_segments). Silero VAD is replaced by scripted speech regions
so the REAL pack_windows() yields deterministic windows; everything downstream (restricted LID, forced
language token, absolute-time stitching, rescoring queue, garbage flags, lexicon, stats) is the real code.

The hf_tokenizer is the cached large-v3-turbo snapshot's tokenizer.json (tokenizers.Tokenizer.from_file);
the whole file is skipped, not failed, when the snapshot is absent.

    PYTHONPATH=backend .venv\\Scripts\\python.exe backend\\tests\\test_asr_engine_options.py
"""

import os
import tempfile
from pathlib import Path

_ISOLATED_ROOT = Path(os.environ.get("DATA_DIR") or os.path.join(tempfile.mkdtemp(prefix="medpark_test_asr_engine_"), "data"))
os.environ.setdefault("DATA_DIR", str(_ISOLATED_ROOT))
os.environ.setdefault("UPLOADS_DIR", str(_ISOLATED_ROOT / "uploads"))
os.environ.setdefault("EXPORTS_DIR", str(_ISOLATED_ROOT / "exports"))
os.environ.setdefault("FIXTURES_DIR", str(_ISOLATED_ROOT / "fixtures"))
os.environ.setdefault("VOICEPRINTS_DIR", str(_ISOLATED_ROOT / "voiceprints"))
os.environ["SMTP_HOST"] = "127.0.0.1"
os.environ["SMTP_PORT"] = "9"
os.environ["ALLOW_SIMULATED_DELIVERY"] = "false"
os.environ["LLM_API_BASE_URL"] = "http://127.0.0.1:9"
os.environ["WHISPER_DEVICE"] = "cpu"  # the module-level singleton resolves its device at import; never touch CUDA here
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

import copy  # noqa: E402
import sys  # noqa: E402
from contextlib import ExitStack  # noqa: E402
from typing import Optional  # noqa: E402
from unittest.mock import patch  # noqa: E402

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402
try:
    from faster_whisper.transcribe import Segment, TranscriptionOptions, Word
except ImportError:
    print("SKIP: faster_whisper is not installed on this platform; skipping faster-whisper option tests.")
    sys.exit(0)

from app.core.config import settings  # noqa: E402
from app.core.exceptions import ASREngineError  # noqa: E402
from app.models.transcript import Transcript  # noqa: E402
from app.services.asr import whisper_engine as engine_module  # noqa: E402
from app.services.asr.glossary import HOTWORDS_BY_LANG  # noqa: E402
from app.services.asr.text_lid import detect_text_language  # noqa: E402
from app.services.asr.whisper_engine import (  # noqa: E402
    DECODE_OPTIONS, GARBAGE_FLAG_REASON, LID_MIN_WINDOW_S, FasterWhisperEngine, garbage_reason,
    needs_rescoring, restrict_language_probs, stitch_segments,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_TOKENIZER = (
    REPO_ROOT / "data" / "models" / "models--mobiuslabsgmbh--faster-whisper-large-v3-turbo"
    / "snapshots" / "0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf" / "tokenizer.json"
)
SR = 16000

# The contract's decode options, verbatim (docs/ASR_CODE_SWITCHING.md section 3)
CONTRACT_DECODE_OPTIONS = {
    "beam_size": 5, "best_of": 5, "patience": 1.0, "length_penalty": 1.0, "repetition_penalty": 1.1,
    "no_repeat_ngram_size": 4, "temperatures": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0], "compression_ratio_threshold": 2.0,
    "log_prob_threshold": -1.0, "no_speech_threshold": 0.6, "prompt_reset_on_temperature": 0.5,
    "condition_on_previous_text": False, "initial_prompt": None, "prefix": None, "word_timestamps": True,
    "hallucination_silence_threshold": 2.0, "without_timestamps": False, "max_initial_timestamp": 1.0,
    "suppress_blank": True, "suppress_tokens": [-1], "multilingual": False, "max_new_tokens": None,
    "clip_timestamps": "0",
}


# ----------------------------------------------------------------------------------------------------------
# Fake model: the audio is a ramp (sample i = i / (SR * 1000)) so a window's first sample encodes its absolute
# start in seconds; the fake feature extractor stores that in features[0, 0], encode() reads it back, and the
# LID / decode scripts are keyed by (window_start, language). pad_or_trim only appends zeros, so the key survives.
# ----------------------------------------------------------------------------------------------------------

def _seg(rel_start: float, rel_end: float, text: str, *, logprob: float = -0.3, cr: float = 1.2, nsp: float = 0.05,
         words: Optional[list[tuple[float, float, str]]] = None, idx: int = 0) -> Segment:
    word_objs = [Word(start=s, end=e, word=w, probability=0.9) for s, e, w in words] if words else None
    return Segment(id=idx, seek=0, start=rel_start, end=rel_end, text=text, tokens=[1, 2, 3], avg_logprob=logprob,
                   compression_ratio=cr, no_speech_prob=nsp, words=word_objs, temperature=0.0)


def _words(rel_start: float, tokens: list[str], step: float = 0.4) -> list[tuple[float, float, str]]:
    return [(round(rel_start + i * step, 2), round(rel_start + (i + 1) * step, 2), " " + tok) for i, tok in enumerate(tokens)]


DEFAULT_DECODE = {
    "ro": [_seg(0.2, 1.4, "Da, bine.", logprob=-0.6)],
    "ru": [_seg(0.2, 1.4, "Да, хорошо.", logprob=-0.6)],
    "en": [_seg(0.2, 1.4, "Yes, okay.", logprob=-0.6)],
}


class FakeFeatureExtractor:
    nb_max_frames = 3000
    time_per_frame = 0.02

    def __call__(self, pcm: np.ndarray) -> np.ndarray:
        assert pcm.ndim == 1 and pcm.dtype == np.float32, (pcm.ndim, pcm.dtype)
        feats = np.zeros((128, int(len(pcm) / 160) + 1), dtype=np.float32)
        feats[0, 0] = float(pcm[0]) * 1000.0 if len(pcm) else -1.0
        return feats


class FakeEncoderOutput:
    def __init__(self, start: float):
        self.start = start


class FakeCT2Model:
    is_multilingual = True

    def __init__(self, outer: "FakeModel"):
        self.outer = outer

    def detect_language(self, encoder_output: FakeEncoderOutput):
        self.outer.detect_calls.append(encoder_output.start)
        script = self.outer.lid_script.get(encoder_output.start)
        assert script is not None, f"no LID script for window starting at {encoder_output.start}"
        return [[(f"<|{lang}|>", p) for lang, p in script]]


class FakeModel:
    """Only the attributes FasterWhisperEngine._decode_windowed / _decode_hypothesis read."""

    def __init__(self, hf_tokenizer, lid_script: dict, decode_script: dict):
        self.hf_tokenizer = hf_tokenizer
        self.feature_extractor = FakeFeatureExtractor()
        self.model = FakeCT2Model(self)
        self.lid_script = lid_script
        self.decode_script = decode_script
        self.encode_calls: list[float] = []
        self.detect_calls: list[float] = []
        self.decode_calls: list[tuple[float, str, TranscriptionOptions]] = []

    def encode(self, features: np.ndarray) -> FakeEncoderOutput:
        assert features.shape[-1] == self.feature_extractor.nb_max_frames, features.shape  # pad_or_trim applied
        start = round(float(features[0, 0]), 2)
        self.encode_calls.append(start)
        return FakeEncoderOutput(start)

    def generate_segments(self, features, tokenizer, options, log_progress, encoder_output=None):
        assert encoder_output is not None, "the cached encoder output must be reused for the decode"
        assert log_progress is False
        language = tokenizer.language_code
        assert tokenizer.language == self.hf_tokenizer.token_to_id(f"<|{language}|>"), "language token not forced"
        self.decode_calls.append((encoder_output.start, language, options))
        specs = self.decode_script.get((encoder_output.start, language), DEFAULT_DECODE[language])
        for spec in specs:
            yield copy.deepcopy(spec)  # fresh Segment AND Word objects: stitch_segments mutates both in place


def _write_ramp_wav(path: Path, seconds: float) -> None:
    audio = (np.arange(int(seconds * SR), dtype=np.float64) / (SR * 1000.0)).astype(np.float32)
    sf.write(str(path), audio, SR, subtype="FLOAT")


def _engine_with(fake: FakeModel) -> FasterWhisperEngine:
    engine = FasterWhisperEngine()
    assert engine.device == "cpu"
    engine._model = fake  # load_model() returns it untouched; WhisperModel is never constructed
    return engine


# ----------------------------------------------------------------------------------------------------------
# Scenario: five windows, WHISPER_LANGUAGES restricted to ["ro", "ru"]
#   W0 [0, 10]      LID en 0.9 / ro 0.4 / ru 0.1  -> restricted argmax ro (0.8); Romanian text; lexicon + digit flag
#   W1 [10.5, 22]   LID ro 0.5 / ru 0.45          -> p1 0.53 < 0.70 queued; ro decode is Cyrillic -> ru wins on logprob
#   W2 [23, 25]     2 s (< 4 s), LID ro 0.8       -> inherits W1's "ru"; p1 of ru 0.2 -> queued; ru keeps
#   W3 [30, 42]     LID ru 0.95                   -> four garbage segments (compression / no letters / logprob / no_speech)
#   W4 [43, 55]     LID ro 0.9                    -> RO/RU text in one window -> "mixed" with spans
# ----------------------------------------------------------------------------------------------------------

REGIONS = [(0.0, 10.0), (10.5, 22.0), (23.0, 25.0), (30.0, 42.0), (43.0, 55.0)]
LID_SCRIPT = {
    0.0: [("en", 0.9), ("ro", 0.4), ("ru", 0.1)],
    10.5: [("ro", 0.5), ("ru", 0.45), ("en", 0.05)],
    23.0: [("ro", 0.8), ("ru", 0.2)],
    30.0: [("ru", 0.95), ("ro", 0.03), ("en", 0.02)],
    43.0: [("ro", 0.9), ("ru", 0.1)],
}
MIXED_TOKENS = ["Pacientul", "din", "salonul", "trei,", "давай", "решим", "перевод", "сегодня,", "după", "consult."]
DECODE_SCRIPT = {
    (0.0, "ro"): [
        _seg(0.5, 4.0, "Pacientul este stabil și rămâne în secție.", logprob=-0.3,
             words=_words(0.5, ["Pacientul", "este", "stabil", "și", "rămâne", "în", "secție."])),
        _seg(4.5, 9.7, "Am administrat noradrenalina 4 mg.", logprob=-0.5, idx=1),
    ],
    (10.5, "ro"): [_seg(0.3, 4.0, "Хемодинамик инстабил.", logprob=-0.9)],
    (10.5, "ru"): [_seg(0.3, 4.0, "Гемодинамически нестабилен, переводим.", logprob=-0.4)],
    (23.0, "ru"): [_seg(0.2, 1.8, "Да.", logprob=-0.5)],
    (23.0, "ro"): [_seg(0.2, 1.8, "Da.", logprob=-1.2)],
    (30.0, "ru"): [
        _seg(0.0, 3.0, "Так так так так так так так так так.", logprob=-0.5, cr=3.1),
        _seg(3.0, 6.0, "...", logprob=-0.5, idx=1),
        _seg(6.0, 9.0, "Перевод согласован.", logprob=-2.0, idx=2),
        _seg(9.0, 12.0, "Хорошо.", logprob=-0.5, nsp=0.9, idx=3),
    ],
    (43.0, "ro"): [_seg(0.5, 5.0, " ".join(MIXED_TOKENS), logprob=-0.45, words=_words(0.5, MIXED_TOKENS))],
}


def _run_scenario(tmp: Path, hf, *, languages=("ro", "ru"), forced: Optional[str] = None, initial_prompt: Optional[str] = None,
                  hotwords: bool = True, lexicon: bool = True):
    wav = tmp / "ramp.wav"
    if not wav.exists():
        _write_ramp_wav(wav, 60.0)
    fake = FakeModel(hf, LID_SCRIPT, DECODE_SCRIPT)
    engine = _engine_with(fake)
    with ExitStack() as stack:
        stack.enter_context(patch.object(engine_module, "speech_regions", lambda audio, *a, **k: list(REGIONS)))
        stack.enter_context(patch.object(settings, "WHISPER_LANGUAGES", list(languages)))
        stack.enter_context(patch.object(settings, "WHISPER_STRATEGY", "windowed"))
        stack.enter_context(patch.object(settings, "ASR_HOTWORDS_ENABLED", hotwords))
        stack.enter_context(patch.object(settings, "ASR_LEXICON_ENABLED", lexicon))
        warning = stack.enter_context(patch.object(engine_module.logger, "warning"))
        segments = engine.transcribe(wav, initial_prompt=initial_prompt, language=forced)
    return engine, fake, segments, warning


def _by_window(segments):
    out: dict[int, list] = {}
    for s in segments:
        out.setdefault(s.window_index, []).append(s)
    return out


# ----------------------------------------------------------------------------------------------------------
# Pure helpers
# ----------------------------------------------------------------------------------------------------------

def test_decode_options_match_contract():
    for key, value in CONTRACT_DECODE_OPTIONS.items():
        assert DECODE_OPTIONS.get(key) == value, (key, DECODE_OPTIONS.get(key), value)
    # Every field TranscriptionOptions needs is either in DECODE_OPTIONS or supplied per decode (hotwords)
    missing = set(TranscriptionOptions.__dataclass_fields__) - set(DECODE_OPTIONS) - {"hotwords"}
    assert not missing, missing
    assert LID_MIN_WINDOW_S == 4.0 and GARBAGE_FLAG_REASON == "low_confidence_asr"
    print("PASSED: test_decode_options_match_contract")


def test_restrict_language_probs_argmax():
    raw = [("<|en|>", 0.9), ("<|ro|>", 0.4), ("<|ru|>", 0.1), ("<|de|>", 0.05)]
    ranking = restrict_language_probs(raw, ["ro", "ru"])
    assert [lang for lang, _ in ranking] == ["ro", "ru"], ranking
    assert abs(ranking[0][1] - 0.8) < 1e-9 and abs(ranking[1][1] - 0.2) < 1e-9, ranking
    assert abs(sum(p for _, p in ranking) - 1.0) < 1e-9
    # With English allowed the unrestricted argmax is honoured
    assert restrict_language_probs(raw, ["ro", "ru", "en"])[0][0] == "en"
    # No mass on any allowed language: uniform, never a crash and never a language outside the list
    uniform = restrict_language_probs([("<|de|>", 1.0)], ["ro", "ru", "en"])
    assert {lang for lang, _ in uniform} == {"ro", "ru", "en"} and all(abs(p - 1 / 3) < 1e-9 for _, p in uniform)
    print("PASSED: test_restrict_language_probs_argmax")


def test_needs_rescoring_rule():
    ro_text = detect_text_language("Pacientul este stabil și rămâne în secție.")
    ru_text = detect_text_language("Гемодинамически нестабилен.")
    weak_text = detect_text_language("propofol midazolam")  # und, confidence 0
    assert needs_rescoring("ro", 0.69, ro_text, 0.70) is True      # weak acoustic LID
    assert needs_rescoring("ro", 0.70, ro_text, 0.70) is False     # exactly at the threshold: not queued
    assert needs_rescoring("ro", 0.95, ro_text, 0.70) is False     # confident and agreeing
    assert needs_rescoring("ro", 0.95, ru_text, 0.70) is True      # confident text disagreement (>= 0.7)
    assert needs_rescoring("ro", 0.95, weak_text, 0.70) is False   # no text evidence: acoustic stands
    print("PASSED: test_needs_rescoring_rule")


def test_garbage_reason_thresholds():
    assert garbage_reason("Text normal.", -0.5, 1.5, 0.1) is None
    assert garbage_reason("Text normal.", -0.5, 2.41, 0.1) == GARBAGE_FLAG_REASON
    assert garbage_reason("Text normal.", -1.51, 1.5, 0.1) == GARBAGE_FLAG_REASON
    assert garbage_reason("Text normal.", -0.5, 1.5, 0.86) == GARBAGE_FLAG_REASON
    assert garbage_reason("... 12 ---", -0.5, 1.5, 0.1) == GARBAGE_FLAG_REASON
    assert garbage_reason("Text normal.", -1.5, 2.4, 0.85) is None  # boundaries are inclusive-keep
    print("PASSED: test_garbage_reason_thresholds")


def test_stitch_segments_shifts_words_too():
    seg = _seg(0.3, 4.0, "x", words=[(0.3, 1.0, " a"), (1.0, 4.0, " b")])
    stitch_segments([seg], 10.5)
    assert (seg.start, seg.end) == (10.8, 14.5)
    assert [(w.start, w.end) for w in seg.words] == [(10.8, 11.5), (11.5, 14.5)]
    print("PASSED: test_stitch_segments_shifts_words_too")


# ----------------------------------------------------------------------------------------------------------
# Engine scenario
# ----------------------------------------------------------------------------------------------------------

def test_engine_restricts_lid_forces_token_and_stitches(tmp: Path, hf):
    engine, fake, segments, warning = _run_scenario(tmp, hf)
    per_window = _by_window(segments)
    assert sorted(per_window) == [0, 1, 2, 3, 4], sorted(per_window)
    assert len(segments) == 9, len(segments)
    # One encoder pass and one LID call per window; the cached encoder output feeds every decode
    assert fake.encode_calls == [0.0, 10.5, 23.0, 30.0, 43.0]
    assert fake.detect_calls == [0.0, 10.5, 23.0, 30.0, 43.0]
    calls = [(start, lang) for start, lang, _ in fake.decode_calls]
    assert calls == [(0.0, "ro"), (10.5, "ro"), (10.5, "ru"), (23.0, "ru"), (23.0, "ro"), (30.0, "ru"), (43.0, "ro")], calls

    # W0: en=0.9 is not allowed -> ro (0.8) picked, token forced, acoustic source
    w0 = per_window[0]
    assert [s.language for s in w0] == ["ro", "ro"] and all(s.language_source == "acoustic" for s in w0)
    assert all(abs(s.language_confidence - 0.8) < 1e-6 for s in w0), [s.language_confidence for s in w0]
    # absolute times (window start 0) and the raw_text / confidence mapping
    assert (w0[0].start, w0[0].end) == (0.5, 4.0) and w0[0].raw_text == "Pacientul este stabil și rămâne în secție."
    assert w0[0].confidence == 0.94 and w0[0].asr_avg_logprob == -0.3 and w0[0].asr_compression_ratio == 1.2
    assert w0[0].is_flagged is False and w0[0].flag_reason is None
    # lexicon applied, original recoverable, digit review-flag from the existing rules (not garbage)
    assert w0[1].raw_text == "Am administrat noradrenalină 4 mg."
    assert [(c.was, c.now) for c in w0[1].corrections] == [("noradrenalina", "noradrenalină")]
    assert w0[1].is_flagged and "numerical" in w0[1].flag_reason
    assert all(s.speaker == "Speaker 1" and s.attribution_state == "anonymous" for s in segments)

    # W1: absolute stitching (10.5 + 0.3 / 4.0) and the rescoring outcome
    w1 = per_window[1]
    assert len(w1) == 1 and (w1[0].start, w1[0].end) == (10.8, 14.5), (w1[0].start, w1[0].end)
    assert w1[0].language == "ru" and w1[0].language_source == "rescored", (w1[0].language, w1[0].language_source)
    assert w1[0].raw_text == "Гемодинамически нестабилен, переводим."  # the better-logprob hypothesis
    assert w1[0].language_confidence == 1.0  # margin 0.5 -> min(1, 0.5 + 0.5)

    # Monotonic absolute timeline across windows
    starts = [s.start for s in segments]
    assert starts == sorted(starts) and starts[0] == 0.5 and segments[-1].end == 48.0
    print("PASSED: test_engine_restricts_lid_forces_token_and_stitches")


def test_engine_inherits_language_on_short_window(tmp: Path, hf):
    engine, fake, segments, _ = _run_scenario(tmp, hf)
    w2 = _by_window(segments)[2]
    assert len(w2) == 1 and (w2[0].start, w2[0].end) == (23.2, 24.8)
    # The 2 s window's own argmax was "ro" (0.8) but the FIRST decode used the inherited "ru"
    first_decode = next(lang for start, lang, _ in fake.decode_calls if start == 23.0)
    assert first_decode == "ru", first_decode
    assert engine.last_run_stats["inherited_windows"] == 1
    # The inherited language carries the runner-up's probability (0.2 < 0.70), so the window is rescored
    # against "ro"; "Da." at -1.2 loses to "Да." at -0.5 and the inherited language stands
    assert w2[0].language == "ru" and w2[0].language_source == "rescored" and w2[0].raw_text == "Да."
    print("PASSED: test_engine_inherits_language_on_short_window")


def test_engine_flags_garbage_without_deleting(tmp: Path, hf):
    engine, fake, segments, _ = _run_scenario(tmp, hf)
    w3 = _by_window(segments)[3]
    assert len(w3) == 4, [s.raw_text for s in w3]  # nothing deleted
    assert all(s.is_flagged and s.flag_reason == GARBAGE_FLAG_REASON for s in w3), [(s.raw_text, s.flag_reason) for s in w3]
    assert [s.raw_text for s in w3][1] == "..."  # no alphabetic character: kept and flagged
    assert all(s.language == "ru" and s.language_source == "acoustic" for s in w3)
    assert [(s.start, s.end) for s in w3] == [(30.0, 33.0), (33.0, 36.0), (36.0, 39.0), (39.0, 42.0)]
    stats = engine.last_run_stats
    assert stats["garbage_flagged"] == 4, stats
    assert stats["integer_second_durations"] == 4 and stats["zero_gaps"] == 3, stats
    print("PASSED: test_engine_flags_garbage_without_deleting")


def test_engine_mixed_window_gets_spans_and_stats(tmp: Path, hf):
    engine, fake, segments, _ = _run_scenario(tmp, hf)
    w4 = _by_window(segments)[4]
    assert len(w4) == 1 and w4[0].language == "mixed" and w4[0].language_source == "text"
    assert [span.language for span in w4[0].language_spans] == ["ro", "ru", "ro"], w4[0].language_spans
    assert w4[0].language_spans[0].start == 43.5 and w4[0].language_spans[-1].end == 47.5  # absolute
    assert 0.5 <= w4[0].language_confidence <= 1.0

    stats = engine.last_run_stats
    for key in ("strategy", "device", "compute_type", "windows", "window_languages", "rescored_windows", "garbage_flagged",
                "integer_second_durations", "zero_gaps", "seconds_vad", "seconds_encode_decode", "seconds_total",
                "audio_seconds", "rtf"):
        assert key in stats, key
    assert stats["strategy"] == "windowed" and stats["device"] == "cpu" and stats["compute_type"] == "int8"
    assert stats["windows"] == 5 and stats["segments"] == 9
    assert stats["window_languages"] == {"ro": 1, "ru": 3, "mixed": 1}, stats["window_languages"]
    assert stats["rescored_windows"] == 2 and stats["corrections"] == 1
    assert stats["audio_seconds"] == 60.0 and stats["rtf"] is not None and stats["rtf"] > 0
    assert stats["text_acoustic_agreement"] == 1.0  # every decided window's text agrees with its final language

    transcript = Transcript(meeting_id="fake", segments=segments)
    transcript.compute_stats()
    assert transcript.languages_detected == ["ro", "ru"], transcript.languages_detected  # mixed expanded, no "und"
    print("PASSED: test_engine_mixed_window_gets_spans_and_stats")


def test_engine_passes_contract_options_and_hotwords(tmp: Path, hf):
    engine, fake, segments, _ = _run_scenario(tmp, hf)
    assert fake.decode_calls
    for start, language, options in fake.decode_calls:
        assert isinstance(options, TranscriptionOptions)
        for key, value in CONTRACT_DECODE_OPTIONS.items():
            if key in ("beam_size", "suppress_tokens"):
                continue
            assert getattr(options, key) == value, (start, language, key, getattr(options, key))
        assert options.beam_size == settings.WHISPER_BEAM_SIZE
        # suppress_tokens: -1 expanded into the tokenizer's non-speech tokens plus the special tokens
        assert isinstance(options.suppress_tokens, tuple) and -1 not in options.suppress_tokens
        assert hf.token_to_id("<|startoftranscript|>") in options.suppress_tokens
        assert hf.token_to_id("<|nospeech|>") in options.suppress_tokens
        # hotwords are the per-language hint, never the full vocabulary, never a prompt
        assert options.hotwords == HOTWORDS_BY_LANG[language], (language, options.hotwords)
        assert options.initial_prompt is None and options.prefix is None
    # A fresh TranscriptionOptions per decode (generate_segments mutates clip_timestamps in place)
    ids = {id(options) for _, _, options in fake.decode_calls}
    assert len(ids) == len(fake.decode_calls)
    # Hotwords off -> None
    _, fake_off, _, _ = _run_scenario(tmp, hf, hotwords=False)
    assert all(options.hotwords is None for _, _, options in fake_off.decode_calls)
    print("PASSED: test_engine_passes_contract_options_and_hotwords")


def test_engine_ignores_initial_prompt_with_one_warning(tmp: Path, hf):
    wav = tmp / "ramp.wav"
    if not wav.exists():
        _write_ramp_wav(wav, 60.0)
    fake = FakeModel(hf, LID_SCRIPT, DECODE_SCRIPT)
    engine = _engine_with(fake)
    with patch.object(engine_module, "speech_regions", lambda audio, *a, **k: list(REGIONS)), \
            patch.object(settings, "WHISPER_LANGUAGES", ["ro", "ru"]), \
            patch.object(engine_module.logger, "warning") as warning:
        engine.transcribe(wav, initial_prompt="Ședință medicală Medpark. Termeni: " + ", ".join(["stent"] * 100))
        engine.transcribe(wav, initial_prompt="again")
        engine.transcribe(wav)
    prompt_warnings = [c for c in warning.call_args_list if "initial_prompt is ignored" in str(c)]
    assert len(prompt_warnings) == 1, warning.call_args_list  # logged once, not per call
    assert all(options.initial_prompt is None for _, _, options in fake.decode_calls)
    assert fake.decode_calls and all("stent" not in (options.hotwords or "") or options.hotwords == HOTWORDS_BY_LANG[lang]
                                     for _, lang, options in fake.decode_calls)
    print("PASSED: test_engine_ignores_initial_prompt_with_one_warning")


def test_engine_forced_language_and_rejected_language(tmp: Path, hf):
    engine, fake, segments, _ = _run_scenario(tmp, hf, forced="ru")
    assert fake.detect_calls == [], fake.detect_calls  # no LID at all when the language is forced
    assert [lang for _, lang, _ in fake.decode_calls] == ["ru"] * 5  # one decode per window, no rescoring
    assert all(s.language in ("ru", "mixed") for s in segments)
    assert engine.last_run_stats["rescored_windows"] == 0 and engine.last_run_stats["inherited_windows"] == 0
    ru_only = [s for s in segments if s.language == "ru"]
    assert ru_only and all(s.language_source == "acoustic" and s.language_confidence == 1.0 for s in ru_only)
    # W1 forced to ru gets the scripted ru hypothesis directly (no ro attempt)
    assert _by_window(segments)[1][0].raw_text == "Гемодинамически нестабилен, переводим."

    # A language outside WHISPER_LANGUAGES is refused loudly (Romanian user-facing message)
    try:
        _run_scenario(tmp, hf, forced="de")
        raise AssertionError("expected ASREngineError")
    except ASREngineError as error:
        assert "nu este acceptată" in str(error), error
    # A forced language that is valid for Whisper but not configured is refused too
    try:
        _run_scenario(tmp, hf, languages=("ro", "ru"), forced="en")
        raise AssertionError("expected ASREngineError")
    except ASREngineError:
        pass
    print("PASSED: test_engine_forced_language_and_rejected_language")


def test_engine_default_languages_allow_english(tmp: Path, hf):
    # With the default ["ro","ru","en"], W0's argmax "en" IS allowed and is decoded first. Its restricted
    # probability is 0.9 / 1.4 = 0.64 < 0.70, so the window is queued; the runner-up "ro" hypothesis
    # (mean logprob -0.4) beats the English one (-0.6) and wins with source "rescored".
    engine, fake, segments, _ = _run_scenario(tmp, hf, languages=("ro", "ru", "en"))
    w0_calls = [lang for start, lang, _ in fake.decode_calls if start == 0.0]
    assert w0_calls == ["en", "ro"], w0_calls
    w0 = _by_window(segments)[0]
    assert w0[0].language == "ro" and w0[0].language_source == "rescored", (w0[0].language, w0[0].language_source)
    assert w0[0].raw_text == "Pacientul este stabil și rămâne în secție."
    assert engine.last_run_stats["window_languages"] == {"ro": 1, "ru": 3, "en": 0, "mixed": 1}
    print("PASSED: test_engine_default_languages_allow_english")


def test_engine_empty_audio_yields_no_segments(tmp: Path, hf):
    wav = tmp / "silence.wav"
    sf.write(str(wav), np.zeros(SR * 5, dtype=np.float32), SR, subtype="FLOAT")
    fake = FakeModel(hf, {}, {})
    engine = _engine_with(fake)
    with patch.object(engine_module, "speech_regions", lambda audio, *a, **k: []):
        segments = engine.transcribe(wav)
    assert segments == [] and fake.encode_calls == []
    assert engine.last_run_stats["windows"] == 0 and engine.last_run_stats["segments"] == 0
    assert engine.last_run_stats["rtf"] is not None
    print("PASSED: test_engine_empty_audio_yields_no_segments")


TESTS_PURE = [
    test_decode_options_match_contract,
    test_restrict_language_probs_argmax,
    test_needs_rescoring_rule,
    test_garbage_reason_thresholds,
    test_stitch_segments_shifts_words_too,
]
TESTS_ENGINE = [
    test_engine_restricts_lid_forces_token_and_stitches,
    test_engine_inherits_language_on_short_window,
    test_engine_flags_garbage_without_deleting,
    test_engine_mixed_window_gets_spans_and_stats,
    test_engine_passes_contract_options_and_hotwords,
    test_engine_ignores_initial_prompt_with_one_warning,
    test_engine_forced_language_and_rejected_language,
    test_engine_default_languages_allow_english,
    test_engine_empty_audio_yields_no_segments,
]


if __name__ == "__main__":
    assert Path(settings.DATA_DIR) == _ISOLATED_ROOT, "storage isolation must be in place before app import"
    assert os.environ.get("DATA_DIR"), "never the production data dir"
    assert engine_module.whisper_engine._model is None, "the singleton must never load a model in this test"

    failures: list[tuple[str, BaseException]] = []
    for test in TESTS_PURE:
        try:
            test()
        except BaseException as error:  # noqa: BLE001 - report every failure, then exit non-zero
            failures.append((test.__name__, error))
            print(f"FAILED: {test.__name__}: {error!r}")

    if not SNAPSHOT_TOKENIZER.exists():
        print(f"SKIPPED: engine scenario tests (no cached tokenizer at {SNAPSHOT_TOKENIZER})")
    else:
        import tokenizers
        hf_tokenizer = tokenizers.Tokenizer.from_file(str(SNAPSHOT_TOKENIZER))
        with tempfile.TemporaryDirectory(prefix="medpark_asr_engine_") as tmp_dir:
            for test in TESTS_ENGINE:
                try:
                    test(Path(tmp_dir), hf_tokenizer)
                except BaseException as error:  # noqa: BLE001
                    failures.append((test.__name__, error))
                    print(f"FAILED: {test.__name__}: {error!r}")

    assert engine_module.whisper_engine._model is None, "the singleton must never load a model in this test"
    if failures:
        print(f"{len(failures)} test(s) failed: {[name for name, _ in failures]}")
        sys.exit(1)
    print("All offline ASR engine option tests passed successfully!")
