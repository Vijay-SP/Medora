"""
Offline unit tests for the code-switching ASR helpers (contracts K3/K6, docs/ASR_CODE_SWITCHING.md).

No CUDA, no WhisperModel: text LID, window packing, the clinical lexicon and the hotword token budget are
pure functions. The hotword budget is measured with the cached large-v3-turbo snapshot's tokenizer.json
(faster_whisper.tokenizer.Tokenizer over tokenizers.Tokenizer.from_file); the test is skipped, not failed,
when the snapshot is absent.

    PYTHONPATH=backend .venv\\Scripts\\python.exe backend\\tests\\test_asr_text_lid_and_windowing.py

Storage and SMTP are isolated through environment variables BEFORE any app import (the repository singleton
binds DATA_DIR at import). MODELS_DIR is left alone: only the tokenizer.json of the cached snapshot is read.
"""

import json
import os
import tempfile
from pathlib import Path

_ISOLATED_ROOT = Path(os.environ.get("DATA_DIR") or os.path.join(tempfile.mkdtemp(prefix="medpark_test_asr_"), "data"))
os.environ.setdefault("DATA_DIR", str(_ISOLATED_ROOT))
os.environ.setdefault("UPLOADS_DIR", str(_ISOLATED_ROOT / "uploads"))
os.environ.setdefault("EXPORTS_DIR", str(_ISOLATED_ROOT / "exports"))
os.environ.setdefault("FIXTURES_DIR", str(_ISOLATED_ROOT / "fixtures"))
os.environ.setdefault("VOICEPRINTS_DIR", str(_ISOLATED_ROOT / "voiceprints"))
os.environ["SMTP_HOST"] = "127.0.0.1"
os.environ["SMTP_PORT"] = "9"
os.environ["ALLOW_SIMULATED_DELIVERY"] = "false"
os.environ["LLM_API_BASE_URL"] = "http://127.0.0.1:9"
os.environ.setdefault("WHISPER_DEVICE", "cpu")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

import warnings  # noqa: E402

import numpy as np  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.models.transcript import Correction, LanguageSpan, Transcript, TranscriptSegment  # noqa: E402
from app.services.asr import glossary  # noqa: E402
from app.services.asr.glossary import HOTWORDS_BY_LANG, HOTWORDS_MAX_TOKENS, MEDPARK_MEDICAL_VOCABULARY  # noqa: E402
from app.services.asr.lexicon import CLINICAL_LEXICON, correct_segment  # noqa: E402
from app.services.asr.text_lid import detect_text_language, language_spans  # noqa: E402
from app.services.asr.windowing import VAD_OPTIONS, DecodeWindow, pack_windows  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_TOKENIZER = (
    REPO_ROOT / "data" / "models" / "models--mobiuslabsgmbh--faster-whisper-large-v3-turbo"
    / "snapshots" / "0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf" / "tokenizer.json"
)
AUDIT_TRANSCRIPTS = REPO_ROOT / ".audit" / "real-run" / "store" / "transcripts.json"

# Window sizes exactly as configured (the engine passes these settings to pack_windows)
_SIZES = dict(min_s=settings.ASR_WINDOW_MIN_S, target_s=settings.ASR_WINDOW_TARGET_S,
              max_s=settings.ASR_WINDOW_MAX_S, hard_cap_s=settings.ASR_WINDOW_HARD_CAP_S)


# ----------------------------------------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------------------------------------

def _lid(text: str) -> tuple[str, float]:
    """(language, confidence) from detect_text_language's TextLID result."""
    result = detect_text_language(text)
    lang, conf = result.language, float(result.confidence)
    assert lang in {"ro", "ru", "en", "mixed", "und"}, lang
    assert 0.0 <= conf <= 1.0, conf
    assert result.is_concrete == (lang in {"ro", "ru", "en"})
    return lang, conf


def _span_tuple(span) -> tuple[float, float, str]:
    if isinstance(span, dict):
        return float(span["start"]), float(span["end"]), span["language"]
    return float(span.start), float(span.end), span.language


def _bounds(windows) -> list[tuple[float, float]]:
    return [(float(w.start), float(w.end)) for w in windows]


def _assert_well_formed(windows, *, min_s: float, target_s: float, max_s: float, hard_cap_s: float):
    bounds = _bounds(windows)
    last_end = -1.0
    for start, end in bounds:
        assert start >= 0 and end > start, (start, end)
        assert start >= last_end, f"overlap or non-monotonic: {bounds}"
        assert end - start <= hard_cap_s + 1e-6, f"window exceeds hard cap: {(start, end)}"
        last_end = end
    assert [w.index for w in windows] == list(range(len(windows)))
    return bounds


def _regions(*pairs: tuple[float, float]) -> list[tuple[float, float]]:
    """VAD speech regions in seconds, the shape windowing.speech_regions() hands to pack_windows()."""
    return [(float(s), float(e)) for s, e in pairs]


class _Word:
    """Minimal stand-in for faster_whisper.transcribe.Word (only the fields text_lid reads)."""

    def __init__(self, start: float, end: float, word: str, probability: float = 0.9):
        self.start = start
        self.end = end
        self.word = word
        self.probability = probability


def _correct(text: str, language: str = "ro") -> tuple[str, list[Correction]]:
    """correct_segment returns (text, [{"was","now","score"}]); every dict must validate as a stored Correction."""
    new_text, raw = correct_segment(text, language)
    corrections = [Correction(**c) for c in raw]
    for c in corrections:
        assert c.was != c.now and 0.0 <= c.score <= 1.0, c
    return new_text, corrections


# ----------------------------------------------------------------------------------------------------------
# Text / script language identification
# ----------------------------------------------------------------------------------------------------------

def test_text_lid_romanian_diacritics_and_stopwords():
    lang, conf = _lid("Așa, transferat acolo, pacientul a fost descărcat volemic și rămâne în terapie intensivă.")
    assert lang == "ro", (lang, conf)
    assert conf >= 0.7, conf
    # Without diacritics the stop-words alone must still carry it
    lang2, _ = _lid("Pacientul este stabil si nu are nevoie de transfer in alta sectie.")
    assert lang2 == "ro", lang2
    print("PASSED: test_text_lid_romanian_diacritics_and_stopwords")


def test_text_lid_russian_cyrillic():
    lang, conf = _lid("Пациент гемодинамически нестабилен, переводим в реанимацию по протоколу.")
    assert lang == "ru", (lang, conf)
    assert conf >= 0.7, conf
    # Cyrillic gibberish from a wrong forced decode is still "ru" to this module: it cannot FIX a decode
    lang2, _ = _lid("Хемодинамик, инстабил.")
    assert lang2 == "ru", lang2
    print("PASSED: test_text_lid_russian_cyrillic")


def test_text_lid_english_stopwords():
    lang, conf = _lid("We need to follow the discharge guidelines and the compliance checklist before the audit.")
    assert lang == "en", (lang, conf)
    assert conf >= 0.5, conf
    print("PASSED: test_text_lid_english_stopwords")


def test_text_lid_mixed_ro_ru_in_one_sentence():
    # ~41% Cyrillic letters: inside the 0.15-0.60 "mixed" band
    lang, conf = _lid("Pacientul din salonul trei, давай решим перевод сегодня, după consult.")
    assert lang == "mixed", lang
    assert conf >= 0.5, conf
    # A lone Cyrillic word in a Romanian sentence stays below the band -> ro, not mixed
    lang2, _ = _lid("Pacientul este stabil și rămâne în secție, да.")
    assert lang2 == "ro", lang2
    print("PASSED: test_text_lid_mixed_ro_ru_in_one_sentence")


def test_text_lid_undetermined_on_digits_and_punctuation():
    # No letters at all: "und" with full confidence (the garbage filter flags such a segment anyway)
    for text in ("12.5 / 80 - 120", "...", "", "2024-09-26 14:30"):
        lang, conf = _lid(text)
        assert lang == "und", (text, lang)
        assert conf == 1.0, (text, conf)
    # Latin letters without any stop-word / diacritic evidence: "und" with ZERO confidence, so the
    # acoustic decision stands and no re-decode is queued on the strength of the text alone
    lang, conf = _lid("propofol midazolam fentanil")
    assert lang == "und" and conf == 0.0, (lang, conf)
    print("PASSED: test_text_lid_undetermined_on_digits_and_punctuation")


def test_language_spans_merge_short_runs():
    # Words without their own evidence ("stabil", "consultul", "cardiologic") inherit the previous decided
    # word; adjacent equal-language words merge into one span. A single Cyrillic word between Romanian runs
    # is either kept as a one-word "ru" span or absorbed (both acceptable; a gap, an overlap, a
    # non-monotonic span or an unknown language is not).
    words = [
        _Word(10.0, 10.4, " Pacientul"), _Word(10.4, 10.8, " este"), _Word(10.8, 11.3, " stabil"),
        _Word(11.3, 11.6, " давай"),
        _Word(11.6, 12.0, " după"), _Word(12.0, 12.5, " consultul"), _Word(12.5, 13.0, " cardiologic"),
    ]
    spans = [_span_tuple(s) for s in language_spans(words)]
    assert spans, "spans must not be empty"
    assert all(lang in {"ro", "ru", "en"} for _, _, lang in spans), spans
    assert spans[0][0] == 10.0 and spans[-1][1] == 13.0, spans
    assert [lang for _, _, lang in spans] in (["ro"], ["ro", "ru", "ro"]), spans
    assert spans[0][2] == "ro" and spans[0][1] >= 11.3, spans  # the three leading RO words are ONE span
    for (s0, e0, _), (s1, e1, _) in zip(spans, spans[1:]):
        assert e0 <= s1 and s0 < e0 and s1 < e1

    # A real code switch (>= 3 words per language) yields exactly two spans, in order, absolute times
    words2 = [
        _Word(20.0, 20.4, " Pacientul"), _Word(20.4, 20.8, " este"), _Word(20.8, 21.3, " stabil"),
        _Word(21.3, 21.6, " давай"), _Word(21.6, 22.0, " решим"), _Word(22.0, 22.5, " перевод"), _Word(22.5, 23.0, " сегодня"),
    ]
    spans2 = [_span_tuple(s) for s in language_spans(words2)]
    assert spans2 == [(20.0, 21.3, "ro"), (21.3, 23.0, "ru")], spans2
    for s in spans2:
        LanguageSpan(start=s[0], end=s[1], language=s[2])  # validates as the stored model
    # Dict words (what the engine stores) are accepted too
    assert [_span_tuple(s) for s in language_spans([{"start": 1.0, "end": 1.5, "word": " și"}])] == [(1.0, 1.5, "ro")]

    # All-Latin words without evidence inherit the next decided word / the default language; nothing is invented
    only_plain = [_Word(0.0, 0.5, " propofol"), _Word(0.5, 1.0, " midazolam"), _Word(1.0, 1.5, " și")]
    assert [_span_tuple(s) for s in language_spans(only_plain)] == [(0.0, 1.5, "ro")]
    assert [_span_tuple(s) for s in language_spans(only_plain[:2], default_language="en")] == [(0.0, 1.0, "en")]
    assert language_spans(only_plain[:2]) == []
    assert language_spans([]) == []
    print("PASSED: test_language_spans_merge_short_runs")


# ----------------------------------------------------------------------------------------------------------
# Window packing over synthetic VAD regions
# ----------------------------------------------------------------------------------------------------------

def test_vad_options_match_contract():
    assert VAD_OPTIONS.threshold == 0.5
    assert VAD_OPTIONS.neg_threshold == 0.35
    assert VAD_OPTIONS.min_speech_duration_ms == 250
    assert VAD_OPTIONS.max_speech_duration_s == 20.0
    assert VAD_OPTIONS.min_silence_duration_ms == 400
    assert VAD_OPTIONS.speech_pad_ms == 200
    assert _SIZES == dict(min_s=1.5, target_s=12.0, max_s=20.0, hard_cap_s=28.0), _SIZES
    print("PASSED: test_vad_options_match_contract")


def test_pack_windows_merges_short_chunks_into_previous():
    # 6 s of speech, a 0.8 s blip (< MIN 1.5 s), then 5 s: the blip joins the first window (span 7.3 s);
    # the 5 s region would push the span past the 12 s target, so it opens the second window.
    windows = pack_windows(_regions((0.0, 6.0), (6.5, 7.3), (8.0, 13.0)), **_SIZES)
    bounds = _assert_well_formed(windows, **_SIZES)
    assert bounds == [(0.0, 7.3), (8.0, 13.0)], bounds
    assert not any(e - s < 1.5 for s, e in bounds), bounds
    # A trailing blip after a closed window merges BACK into it (the post-pass), never its own window
    windows1 = pack_windows(_regions((0.0, 11.0), (11.5, 12.3)), **_SIZES)
    assert _assert_well_formed(windows1, **_SIZES) == [(0.0, 12.3)]
    # A leading short region has no previous window: it must still be covered (merged forward), never dropped
    windows2 = pack_windows(_regions((0.0, 0.8), (1.2, 7.0)), **_SIZES)
    assert _assert_well_formed(windows2, **_SIZES) == [(0.0, 7.0)]
    # The speech regions inside a window are kept (the engine's short-window guard uses speech_seconds)
    assert windows[0].speech_regions == [(0.0, 6.0), (6.5, 7.3)] and abs(windows[0].speech_seconds - 6.8) < 1e-9
    print("PASSED: test_pack_windows_merges_short_chunks_into_previous")


def test_pack_windows_packs_towards_target_and_respects_max():
    # Eight 3 s regions with 0.5 s gaps: the 12 s target packs three per window (span 10 s), never over 20 s
    pairs = [(i * 3.5, i * 3.5 + 3.0) for i in range(8)]
    windows = pack_windows(_regions(*pairs), **_SIZES)
    bounds = _assert_well_formed(windows, **_SIZES)
    assert bounds == [(0.0, 10.0), (10.5, 20.5), (21.0, 27.5)], bounds
    for start, end in bounds:
        assert 6.0 <= end - start <= settings.ASR_WINDOW_MAX_S + 1e-6  # packing happened; not one window per region
    # A region that would push the span past the target opens a new window (13 + 8 > 12)
    windows3 = pack_windows(_regions((0.0, 13.0), (13.4, 21.4)), **_SIZES)
    assert _assert_well_formed(windows3, **_SIZES) == [(0.0, 13.0), (13.4, 21.4)]
    # A window still under MIN may stretch up to MAX (but not beyond) to become usable
    windows4 = pack_windows(_regions((0.0, 1.0), (1.3, 19.0)), **_SIZES)
    assert _assert_well_formed(windows4, **_SIZES) == [(0.0, 19.0)]
    # Known edge (documented, not hidden): a LEADING sub-minimum window has no predecessor to merge into and
    # a following region that cannot stretch (21 s > MAX) opens its own window, so the 1 s window survives.
    # It is still covered (never dropped) and the engine's short-window guard gives it its neighbour's language.
    windows5 = pack_windows(_regions((0.0, 1.0), (1.3, 21.0)), **_SIZES)
    assert _assert_well_formed(windows5, **_SIZES) == [(0.0, 1.0), (1.3, 21.0)]
    # A silence longer than the gap limit closes the window even when the span would still fit
    windows6 = pack_windows(_regions((0.0, 3.0), (8.0, 11.0)), **_SIZES)
    assert _assert_well_formed(windows6, **_SIZES) == [(0.0, 3.0), (8.0, 11.0)]
    # Inconsistent sizes are refused loudly
    try:
        pack_windows(_regions((0.0, 3.0)), min_s=5.0, target_s=4.0, max_s=20.0, hard_cap_s=28.0)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
    print("PASSED: test_pack_windows_packs_towards_target_and_respects_max")


def test_pack_windows_hard_cap_splits_long_chunk_without_overlap():
    # One uninterrupted 65 s region: cut into ceil(65/28) = 3 equal pieces covering the span, no overlap
    windows = pack_windows(_regions((10.0, 75.0)), **_SIZES)
    bounds = _assert_well_formed(windows, **_SIZES)
    assert len(bounds) == 3, bounds
    assert bounds[0][0] == 10.0 and abs(bounds[-1][1] - 75.0) < 1e-6, bounds
    covered = sum(e - s for s, e in bounds)
    assert abs(covered - 65.0) < 1e-2, covered  # exact coverage (to ms rounding): no overlap, no loss
    for s, e in bounds:
        assert 1.5 <= e - s <= 28.0 + 1e-6, (s, e)
    for (_, e0), (s1, _) in zip(bounds, bounds[1:]):
        assert abs(e0 - s1) < 1e-6, bounds  # pieces abut exactly
    # Exactly at the cap: untouched
    assert _assert_well_formed(pack_windows(_regions((0.0, 28.0)), **_SIZES), **_SIZES) == [(0.0, 28.0)]
    print("PASSED: test_pack_windows_hard_cap_splits_long_chunk_without_overlap")


def test_pack_windows_absolute_monotonic_and_indexed():
    pairs = [(100.0, 104.0), (104.6, 111.0), (112.0, 130.0), (130.3, 131.0), (140.0, 141.2)]
    windows = pack_windows(_regions(*pairs), **_SIZES)
    bounds = _assert_well_formed(windows, **_SIZES)
    # (130.3, 131.0) is 0.7 s: merged back into the 112-130 window (span 19 s <= cap); (140, 141.2) is 1.2 s
    # but merging it would make a 29.2 s span, so it stays its own (short) window rather than be lost
    assert bounds == [(100.0, 111.0), (112.0, 131.0), (140.0, 141.2)], bounds
    assert [w.index for w in windows] == [0, 1, 2]
    assert all(isinstance(w, DecodeWindow) and abs(w.duration - (w.end - w.start)) < 1e-9 for w in windows)
    # Empty / degenerate input -> no windows, no exception
    assert pack_windows([], **_SIZES) == []
    assert pack_windows(_regions((5.0, 5.0), (7.0, 6.0)), **_SIZES) == []
    # slice() maps the window back onto 16 kHz samples
    audio = np.zeros(16000 * 150, dtype=np.float32)
    assert windows[0].slice(audio).shape[0] == int(round(11.0 * 16000))
    print("PASSED: test_pack_windows_absolute_monotonic_and_indexed")


# ----------------------------------------------------------------------------------------------------------
# Clinical lexicon
# ----------------------------------------------------------------------------------------------------------

def test_lexicon_fixes_near_miss_drug_name_and_records_correction():
    assert CLINICAL_LEXICON, "lexicon must not be empty"
    # Drug names are exact, word-bounded respellings (score 1.0); the diacritic-less form is the common miss
    text = "Am administrat noradrenalina pacientului dimineața, apoi dobutamina."
    new_text, corrections = _correct(text)
    assert new_text == "Am administrat noradrenalină pacientului dimineața, apoi dobutamină.", new_text
    assert [(c.was, c.now, c.score) for c in corrections] == [
        ("noradrenalina", "noradrenalină", 1.0), ("dobutamina", "dobutamină", 1.0)], corrections
    # The decoder output is recoverable from `was`
    recovered = new_text
    for c in corrections:
        recovered = recovered.replace(c.now, c.was, 1)
    assert recovered == text
    # Case-insensitive, and an already-canonical token is not "corrected" to itself
    assert _correct("Noradrenalină și noradrenalină.") == ("Noradrenalină și noradrenalină.", [])
    upper, ups = _correct("NORADRENALINA 0.1")
    assert upper.startswith("noradrenalină") and ups[0].was == "NORADRENALINA"
    # Proper nouns accept fuzzy near-misses with the similarity as score; the entry's languages gate it
    exact_text, exact = _correct("Transferul la Metpark este aprobat.", "ro")  # listed variant: score 1.0
    assert exact_text == "Transferul la Medpark este aprobat." and [(c.was, c.score) for c in exact] == [("Metpark", 1.0)]
    fuzzy_text, fuzzy = _correct("Transferul la Medparck este aprobat.", "ro")  # unlisted near-miss: similarity score
    assert fuzzy_text == "Transferul la Medpark este aprobat." and fuzzy[0].was == "Medparck"
    assert fuzzy[0].now == "Medpark" and 0.80 <= fuzzy[0].score < 1.0, fuzzy
    ru_text, ru_corr = _correct("Перевод в Мед Парк согласован.", "ru")
    assert ru_text == "Перевод в Медпарк согласован." and ru_corr[0].was == "Мед Парк"
    # A Romanian-only entry does not fire on an English or a mixed/und segment
    assert _correct("we gave noradrenalina", "en") == ("we gave noradrenalina", [])
    assert _correct("noradrenalina давай", "mixed") == ("noradrenalina давай", [])
    assert _correct("noradrenalina", "und") == ("noradrenalina", [])
    print("PASSED: test_lexicon_fixes_near_miss_drug_name_and_records_correction")


def test_lexicon_never_touches_tokens_with_digits():
    # Doses, dates and codes must survive untouched: a digit glued to a token disqualifies it
    for text in ("noradrenalina5 mg", "doza 2xnoradrenalina", "PEEP 8, FiO2 40%, noradrenalin4 0.3",
                 "12.5 mg de 3 ori pe zi", "Metpark2024 raport", "cod A.T.I.7"):
        new_text, corrections = _correct(text)
        assert new_text == text, (text, new_text)
        assert corrections == [], (text, corrections)
    # ...while the same tokens separated from the digits are corrected (the digit rule is per token)
    new_text, corrections = _correct("noradrenalina 5 mg")
    assert new_text == "noradrenalină 5 mg" and len(corrections) == 1
    print("PASSED: test_lexicon_never_touches_tokens_with_digits")


def test_lexicon_leaves_unrelated_text_alone():
    for text, lang in (
        ("Ședința de mâine începe la ora nouă în sala mare.", "ro"),
        ("Давайте решим перевод пациента сегодня после консилиума.", "ru"),
        ("We will review the discharge summary on Friday.", "en"),
        ("Pacientul are heparină și enoxaparină conform protocolului.", "ro"),  # already canonical
        ("Parcul de lângă spital este mare.", "ro"),  # "Parcul" must not fuzz into "Medpark"
        ("", "ro"),
    ):
        new_text, corrections = _correct(text, lang)
        assert new_text == text, (text, new_text)
        assert corrections == [], (text, corrections)
    print("PASSED: test_lexicon_leaves_unrelated_text_alone")


# ----------------------------------------------------------------------------------------------------------
# Hotword budget and the retired prompt
# ----------------------------------------------------------------------------------------------------------

def test_hotwords_within_token_budget_with_cached_tokenizer():
    if not SNAPSHOT_TOKENIZER.exists():
        print(f"SKIPPED: test_hotwords_within_token_budget_with_cached_tokenizer (no snapshot at {SNAPSHOT_TOKENIZER})")
        return
    import tokenizers
    from faster_whisper.tokenizer import Tokenizer

    hf = tokenizers.Tokenizer.from_file(str(SNAPSHOT_TOKENIZER))
    assert set(HOTWORDS_BY_LANG) == {"ro", "ru", "en"}, HOTWORDS_BY_LANG.keys()
    counts = {}
    for lang, words in HOTWORDS_BY_LANG.items():
        tok = Tokenizer(hf, True, task="transcribe", language=lang)  # the engine's wrapper; no WhisperModel
        # faster-whisper encodes hotwords as " " + hotwords.strip() (transcribe.py, get_prompt)
        counts[lang] = len(tok.encode(" " + words.strip()))
        assert 0 < counts[lang] <= HOTWORDS_MAX_TOKENS <= 80, (lang, counts[lang])
        assert glossary.hotwords_for(lang) == words
    assert glossary.hotwords_for(None) is None and glossary.hotwords_for("mixed") is None
    # The glossary's own helper must agree with the direct measurement
    assert glossary.hotword_token_counts(hf) == counts, (glossary.hotword_token_counts(hf), counts)
    # The full vocabulary is over the 223-token prompt slot and must never be sent as a hint
    full = len(tok.encode(" " + ", ".join(MEDPARK_MEDICAL_VOCABULARY)))
    assert full > 223, full
    # Script hygiene: the Russian hint is Cyrillic, the Romanian/English hints are Latin
    assert any("Ѐ" <= ch <= "ӿ" for ch in HOTWORDS_BY_LANG["ru"])
    assert not any("Ѐ" <= ch <= "ӿ" for ch in HOTWORDS_BY_LANG["ro"] + HOTWORDS_BY_LANG["en"])
    print(f"PASSED: test_hotwords_within_token_budget_with_cached_tokenizer {counts}, full vocabulary {full} tokens")


def test_build_code_switch_prompt_is_a_deprecated_empty_stub():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        out = glossary.build_code_switch_prompt(agenda="Ordinea de zi", attendee_names=["Dr. X"], custom_terms=["stent"])
    assert out == "", repr(out)
    assert any(issubclass(w.category, DeprecationWarning) for w in caught), [w.category for w in caught]
    # The review-flag vocabulary the engine slices [:20] is still intact
    assert len(MEDPARK_MEDICAL_VOCABULARY) >= 20 and "Medpark" in MEDPARK_MEDICAL_VOCABULARY
    print("PASSED: test_build_code_switch_prompt_is_a_deprecated_empty_stub")


# ----------------------------------------------------------------------------------------------------------
# Model compatibility: stored transcripts keep validating, compute_stats semantics
# ----------------------------------------------------------------------------------------------------------

def test_stored_audit_transcripts_still_validate():
    if not AUDIT_TRANSCRIPTS.exists():
        print("SKIPPED: test_stored_audit_transcripts_still_validate (no .audit/real-run store)")
        return
    store = json.loads(AUDIT_TRANSCRIPTS.read_text(encoding="utf-8"))
    total = 0
    for meeting_id, payload in store.items():
        transcript = Transcript.model_validate(payload)
        assert transcript.meeting_id == meeting_id
        for seg in transcript.segments:
            assert seg.language_source == "legacy" and seg.language_confidence == 0.0
            assert seg.corrections == [] and seg.language_spans == [] and seg.window_index is None
        total += len(transcript.segments)
    assert total >= 1
    print(f"PASSED: test_stored_audit_transcripts_still_validate ({total} legacy segments)")


def test_compute_stats_language_semantics():
    t = Transcript(meeting_id="m1", segments=[
        TranscriptSegment(start=0.0, end=1.0, raw_text="Bună", language="ro"),
        TranscriptSegment(start=1.0, end=2.0, raw_text="12", language="und"),
        TranscriptSegment(start=2.0, end=4.0, raw_text="Pacientul давай", language="mixed",
                          language_spans=[LanguageSpan(start=2.0, end=3.0, language="ro"),
                                          LanguageSpan(start=3.0, end=4.0, language="ru")]),
    ])
    t.compute_stats()
    assert t.languages_detected == ["ro", "ru"], t.languages_detected
    only_und = Transcript(meeting_id="m2", segments=[TranscriptSegment(start=0.0, end=1.0, raw_text="12", language="und")])
    only_und.compute_stats()
    assert only_und.languages_detected == ["ro"], only_und.languages_detected
    # New fields round-trip through JSON with the corrections intact
    seg = TranscriptSegment(start=0.0, end=1.5, raw_text="noradrenalină", language="ro", language_confidence=0.91,
                            language_source="acoustic", window_index=3, asr_avg_logprob=-0.42,
                            asr_compression_ratio=1.3, asr_no_speech_prob=0.02,
                            corrections=[Correction(was="noradrenalina", now="noradrenalină", score=1.0)])
    again = TranscriptSegment.model_validate_json(seg.model_dump_json())
    assert again.corrections[0].was == "noradrenalina" and again.language_source == "acoustic" and again.window_index == 3
    print("PASSED: test_compute_stats_language_semantics")


TESTS = [
    test_text_lid_romanian_diacritics_and_stopwords,
    test_text_lid_russian_cyrillic,
    test_text_lid_english_stopwords,
    test_text_lid_mixed_ro_ru_in_one_sentence,
    test_text_lid_undetermined_on_digits_and_punctuation,
    test_language_spans_merge_short_runs,
    test_vad_options_match_contract,
    test_pack_windows_merges_short_chunks_into_previous,
    test_pack_windows_packs_towards_target_and_respects_max,
    test_pack_windows_hard_cap_splits_long_chunk_without_overlap,
    test_pack_windows_absolute_monotonic_and_indexed,
    test_lexicon_fixes_near_miss_drug_name_and_records_correction,
    test_lexicon_never_touches_tokens_with_digits,
    test_lexicon_leaves_unrelated_text_alone,
    test_hotwords_within_token_budget_with_cached_tokenizer,
    test_build_code_switch_prompt_is_a_deprecated_empty_stub,
    test_stored_audit_transcripts_still_validate,
    test_compute_stats_language_semantics,
]


if __name__ == "__main__":
    import sys

    assert Path(settings.DATA_DIR) == _ISOLATED_ROOT, "storage isolation must be in place before app import"
    assert os.environ.get("DATA_DIR"), "never the production data dir"
    failures: list[str] = []
    for test in TESTS:
        try:
            test()
        except BaseException as error:  # noqa: BLE001 - report every failure, then exit non-zero
            failures.append(test.__name__)
            print(f"FAILED: {test.__name__}: {error!r}")
    if failures:
        print(f"{len(failures)} test(s) failed: {failures}")
        sys.exit(1)
    print("All offline ASR text-LID / windowing / lexicon / hotword tests passed successfully!")
