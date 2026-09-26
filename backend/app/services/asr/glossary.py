"""
Medpark Meeting Intelligence System - Multilingual Medical Glossary
Provides per-language decoder hotwords for Romanian/Russian/English code-switched clinical speech.

History (docs/ASR_CODE_SWITCHING.md): the previous `build_code_switch_prompt()` produced a 257-token
initial_prompt. Whisper's prompt slot holds 223 tokens, so the trilingual framing sentence was cut and,
with condition_on_previous_text=True, the truncated term list stayed in decoder context for the whole
file - the model then continued the comma-list as if it had been spoken (the 27.7 s hallucinated
opening on the real recording). Prompt conditioning is therefore gone; each decode window receives a
short `hotwords` hint in the language chosen for that window instead.
"""

import warnings
from typing import Optional

from app.core.logging import logger


# High-frequency medical terms across Romanian, Russian, and English in Moldovan hospital meetings.
# Kept as three named blocks so a consumer can never slice across a language boundary.
MEDPARK_ROMANIAN_TERMS = [
    # Romanian Clinical & Administrative Terms
    "Medpark", "Spitalul Internațional Medpark", "Consiliul Medical", "Comitetul Director",
    "terapie intensivă", "ATI", "anestezie", "bloc operator", "chirurgie laparoscopică",
    "hemostază", "sutură", "protocol clinic", "analize de laborator", "hemoleucogramă",
    "tomografie computerizată", "CT", "RMN", "rezonanță magnetică", "cateterism",
    "angioplastie", "stent", "bypass coronarian", "cardiologie intervențională",
    "secția internare", "farmacie spitalicească", "antibioticoterapie", "consimțământ informat",
    "transfer interclinic", "raport de gardă", "termen limită", "responsabil", "aprobare buget",
]

MEDPARK_RUSSIAN_TERMS = [
    # Russian Clinical & Conversational Terms (Moldovan dialectal code-switching)
    "пациент", "история болезни", "назначение", "реанимация", "дежурный врач",
    "заведующий отделением", "срочно", "согласовать", "дозировка", "операционный блок",
    "анализы", "выписка", "консилиум", "перевод в палату", "давление", "препарат",
    "капельница", "рентген", "кардиограмма", "по протоколу", "давай решим",
]

MEDPARK_ENGLISH_TERMS = [
    # English Clinical, IT & Management Jargon
    "guidelines", "workflow", "Standard Operating Procedure", "SOP", "compliance",
    "quality assurance", "KPI", "follow-up", "triage", "emergency room", "screening",
    "discharge summary", "monitoring", "checkpoint", "feedback", "roadmap", "audit"
]

# Flat view consumed by the ASR engine's review-flag heuristics (whisper_engine uses the first 20 entries
# as "critical term" patterns). 318 tokens with the turbo tokenizer: NEVER send it to the decoder as a
# prompt or as hotwords, it would be truncated and pollute the context.
MEDPARK_MEDICAL_VOCABULARY = MEDPARK_ROMANIAN_TERMS + MEDPARK_RUSSIAN_TERMS + MEDPARK_ENGLISH_TERMS

# Hotword budget: faster-whisper truncates hotwords at max_length // 2 - 1 = 223 tokens, but every hotword
# token competes with the audio for decoder attention, so the lists stay far below that. Verified with
# the cached large-v3-turbo tokenizer (tokenizer.json in the snapshot): ro 78, ru 73, en 74 tokens.
HOTWORDS_MAX_TOKENS = 80

# Proper nouns, drug names and site abbreviations that Whisper plausibly misses or respells; deliberately
# NOT common words (those the model already knows and a hint only biases the decoder towards them).
# Each list is spelled in the script of the language whose decode it accompanies.
HOTWORDS_BY_LANG: dict[str, str] = {
    "ro": (
        "Medpark, Chișinău, ATI, UPU, RMN, ECG, PEEP, CPAP, noradrenalină, dobutamină, propofol, "
        "midazolam, fentanil, heparină, enoxaparină, meropenem, furosemid, coronarografie, stent"
    ),
    "ru": (
        "Медпарк, Кишинёв, реанимация, ИВЛ, КТ, МРТ, ЭКГ, норадреналин, добутамин, пропофол, "
        "мидазолам, фентанил, гепарин, меропенем, фуросемид"
    ),
    "en": (
        "Medpark, Chisinau, ICU, ECMO, CPAP, PEEP, norepinephrine, dobutamine, propofol, midazolam, "
        "fentanyl, heparin, enoxaparin, ceftriaxone, meropenem, furosemide, stent, SOP, KPI"
    ),
}


def hotwords_for(language: Optional[str]) -> Optional[str]:
    """Hotword hint for a decode window; None for languages without a list (or when hints are disabled)."""
    if not language:
        return None
    return HOTWORDS_BY_LANG.get(language)


def hotword_token_counts(tokenizer) -> dict[str, int]:
    """
    Token count of each hotword list exactly as faster-whisper encodes it (`" " + hotwords.strip()`).
    `tokenizer` is a `tokenizers.Tokenizer` (WhisperModel.hf_tokenizer or the snapshot's tokenizer.json).
    """
    return {
        lang: len(tokenizer.encode(" " + words.strip(), add_special_tokens=False).ids)
        for lang, words in HOTWORDS_BY_LANG.items()
    }


_deprecation_logged = False


def build_code_switch_prompt(
    agenda: Optional[str] = None,
    attendee_names: Optional[list[str]] = None,
    custom_terms: Optional[list[str]] = None
) -> str:
    """
    Deprecated: returns "" so no caller can re-introduce prompt conditioning by accident.

    The 257-token trilingual prompt this used to build overflowed Whisper's 223-token prompt slot and
    was the direct cause of the hallucinated comma-list opening on the real recording. Per-window
    hotwords (HOTWORDS_BY_LANG) replace it; the arguments are accepted and ignored.
    """
    global _deprecation_logged
    if not _deprecation_logged:
        logger.warning(
            "build_code_switch_prompt() is deprecated and returns an empty prompt: initial_prompt "
            "conditioning was removed on purpose (see docs/ASR_CODE_SWITCHING.md); use HOTWORDS_BY_LANG."
        )
        _deprecation_logged = True
    warnings.warn(
        "build_code_switch_prompt() is deprecated; Whisper no longer receives an initial_prompt.",
        DeprecationWarning,
        stacklevel=2,
    )
    return ""
