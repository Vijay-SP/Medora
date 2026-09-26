"""
Medpark Meeting Intelligence System - Clinical Lexicon Corrections
Conservative post-decode normalisation of proper nouns and site abbreviations that Whisper respells.

Every correction is recorded (was / now / score) on the segment so the decoder output stays
recoverable and the reviewer can see what was touched. The lexicon is deliberately small: fuzzy
matching only runs against proper nouns, never against ordinary clinical vocabulary, because a
false correction is worse than a respelled hospital name.
"""

from dataclasses import dataclass
from difflib import SequenceMatcher
import re
from typing import Optional


@dataclass(frozen=True)
class LexiconEntry:
    canonical: str
    variants: tuple[str, ...]   # exact (case-insensitive, word-bounded) respellings
    languages: tuple[str, ...]  # scripts this entry applies to
    fuzzy: bool = False         # also accept near-misses of the canonical form (proper nouns only)


CLINICAL_LEXICON: tuple[LexiconEntry, ...] = (
    # Site and proper nouns (Latin script)
    LexiconEntry("Medpark", ("Med Park", "Med-Park", "Medparc", "Medpac", "Metpark", "Madpark", "Mad Park", "Med Parc"), ("ro", "en"), fuzzy=True),
    LexiconEntry("Chișinău", ("Chisinau", "Chișinau", "Chisinău", "Kishinev", "Kishinau"), ("ro",), fuzzy=False),
    # Site and proper nouns (Cyrillic)
    LexiconEntry("Медпарк", ("Мед Парк", "Мед-Парк", "Мэдпарк", "Медпак", "Мэд Парк"), ("ru",), fuzzy=True),
    LexiconEntry("Кишинёв", ("Кишинев", "Кишинэу"), ("ru",), fuzzy=False),
    # Dotted / spaced abbreviations that Whisper emits for spelled-out acronyms
    LexiconEntry("ATI", ("A.T.I.", "A.T.I", "A T I"), ("ro",)),
    LexiconEntry("UPU", ("U.P.U.", "U.P.U", "U P U"), ("ro",)),
    LexiconEntry("RMN", ("R.M.N.", "R.M.N", "R M N"), ("ro",)),
    LexiconEntry("CT", ("C.T.", "C.T"), ("ro", "en")),
    LexiconEntry("ECG", ("E.C.G.", "E.C.G", "E C G", "EKG"), ("ro", "en")),
    LexiconEntry("CPAP", ("C-PAP", "C PAP", "Sipap", "Si-PAP"), ("ro", "en")),
    LexiconEntry("PEEP", ("P.E.E.P.", "P.E.E.P"), ("ro", "en")),
    LexiconEntry("ICU", ("I.C.U.", "I.C.U"), ("en",)),
    LexiconEntry("ECMO", ("E.C.M.O.", "Ekmo", "Ecmo"), ("ro", "en")),
    LexiconEntry("ИВЛ", ("И.В.Л.", "И.В.Л", "И В Л"), ("ru",)),
    LexiconEntry("КТ", ("К.Т.", "К.Т"), ("ru",)),
    LexiconEntry("МРТ", ("М.Р.Т.", "М.Р.Т", "М Р Т"), ("ru",)),
    LexiconEntry("ЭКГ", ("Э.К.Г.", "Э.К.Г", "Э К Г"), ("ru",)),
    # Drug names commonly respelled across the Romanian/English boundary
    LexiconEntry("noradrenalină", ("noradrenalina", "nor-adrenalină", "nor adrenalină"), ("ro",)),
    LexiconEntry("dobutamină", ("dobutamina", "dobutamin"), ("ro",)),
    LexiconEntry("enoxaparină", ("enoxaparina", "enoxaparin"), ("ro",)),
    LexiconEntry("heparină", ("heparina",), ("ro",)),
    LexiconEntry("norepinephrine", ("nor-epinephrine", "nor epinephrine", "noradrenaline"), ("en",)),
)

FUZZY_MIN_RATIO = 0.80  # SequenceMatcher ratio for proper-noun near-misses ("Metpark" -> 0.86)
FUZZY_MIN_LEN = 5       # never fuzz short tokens
WORD_RE = re.compile(r"[^\W\d_]+(?:[-'][^\W\d_]+)*", re.UNICODE)

_variant_patterns: list[tuple[LexiconEntry, re.Pattern]] = [
    (
        entry,
        re.compile(
            r"(?<!\w)(?:" + "|".join(re.escape(v) for v in sorted(entry.variants, key=len, reverse=True)) + r")(?!\w)",
            re.IGNORECASE,
        ),
    )
    for entry in CLINICAL_LEXICON
    if entry.variants
]
_fuzzy_entries = [entry for entry in CLINICAL_LEXICON if entry.fuzzy]
_canonical_lower = {entry.canonical.lower() for entry in CLINICAL_LEXICON}


def _applies(entry: LexiconEntry, language: Optional[str]) -> bool:
    return language in entry.languages


def _fuzzy_match(token: str, language: Optional[str]) -> Optional[tuple[LexiconEntry, float]]:
    if len(token) < FUZZY_MIN_LEN or token.lower() in _canonical_lower:
        return None
    best: Optional[tuple[LexiconEntry, float]] = None
    for entry in _fuzzy_entries:
        if not _applies(entry, language):
            continue
        ratio = SequenceMatcher(None, token.lower(), entry.canonical.lower()).ratio()
        if ratio >= FUZZY_MIN_RATIO and (best is None or ratio > best[1]):
            best = (entry, ratio)
    return best


def correct_segment(text: str, language: Optional[str]) -> tuple[str, list[dict]]:
    """
    Applies the lexicon to one segment's text.

    Returns (corrected_text, corrections) where each correction is {"was", "now", "score"}; score is
    1.0 for an exact variant and the similarity ratio for a fuzzy proper-noun match. Only entries whose
    `languages` contain `language` are applied: "mixed" and "und" segments are returned unchanged so a
    Latin correction never lands inside a Cyrillic run.
    """
    if not text or language not in ("ro", "ru", "en"):
        return text, []

    corrections: list[dict] = []
    result = text
    for entry, pattern in _variant_patterns:
        if not _applies(entry, language):
            continue

        def _replace(match: re.Match, entry=entry) -> str:
            was = match.group(0)
            if was == entry.canonical:
                return was
            corrections.append({"was": was, "now": entry.canonical, "score": 1.0})
            return entry.canonical

        result = pattern.sub(_replace, result)

    if _fuzzy_entries:
        def _fuzzy_replace(match: re.Match) -> str:
            token = match.group(0)
            hit = _fuzzy_match(token, language)
            if hit is None:
                return token
            entry, ratio = hit
            corrections.append({"was": token, "now": entry.canonical, "score": round(ratio, 3)})
            return entry.canonical

        result = WORD_RE.sub(_fuzzy_replace, result)

    return result, corrections
