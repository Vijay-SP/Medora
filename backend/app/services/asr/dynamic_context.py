"""
Medpark Meeting Intelligence System - Dynamic Meeting ASR Context
Builds deterministic, immutable ASRContext from meeting metadata and clinical vocabulary
to bias speech recognition engines honestly towards doctor names, department procedures,
and verified hospital terminology.
"""

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Literal, Optional

from app.core.config import settings
from app.core.logging import logger
from app.models.meeting import Attendee, MeetingBase
from app.services.learning.store import AdaptationStore, adaptation_store

CategoryType = Literal["attendee", "medication", "procedure", "department", "term"]


@dataclass(frozen=True)
class ContextTerm:
    """Immutable context entry with provenance and prioritization weight."""
    text: str
    category: CategoryType
    source: str
    weight: float = 1.0


@dataclass(frozen=True)
class ASRContext:
    """Immutable deterministic meeting context passed to ASR engines."""
    terms: tuple[ContextTerm, ...] = ()
    prompt_seed: str = ""
    hotwords: tuple[str, ...] = ()


# Common honorific prefixes stripped from attendee names
HONORIFIC_PREFIX_RE = re.compile(
    r"^(?:dr\.?|prof\.?|dna\.?|dl\.?|doctor|medic|asistent|conf\.?|academician)\s+",
    re.IGNORECASE,
)

# Cyrillic to Latin transliteration table (standard Moldovan / Romanian medical transcript standard)
CYRILLIC_TO_LATIN: dict[str, str] = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "А": "A", "Б": "B", "В": "V", "Г": "G", "Д": "D", "Е": "E", "Ё": "Yo",
    "Ж": "Zh", "З": "Z", "И": "I", "Й": "Y", "К": "K", "Л": "L", "М": "M",
    "Н": "N", "О": "O", "П": "P", "Р": "R", "С": "S", "Т": "T", "У": "U",
    "Ф": "F", "Х": "Kh", "Ц": "Ts", "Ч": "Ch", "Ш": "Sh", "Щ": "Shch",
    "Ъ": "", "Ы": "Y", "Ь": "", "Э": "E", "Ю": "Yu", "Я": "Ya",
}

# Latin digraphs and characters for Latin-to-Cyrillic transliteration
LATIN_TO_CYRILLIC_MULTI = [
    ("shch", "щ"), ("yo", "ё"), ("zh", "ж"), ("kh", "х"),
    ("ts", "ц"), ("ch", "ч"), ("sh", "ш"), ("yu", "ю"), ("ya", "я"),
]
LATIN_TO_CYRILLIC_SINGLE = {
    "a": "а", "b": "б", "v": "в", "g": "г", "d": "д", "e": "е",
    "z": "з", "i": "и", "y": "й", "k": "к", "l": "л", "m": "м",
    "n": "н", "o": "о", "p": "п", "r": "р", "s": "с", "t": "т",
    "u": "у", "f": "ф",
}

RUSSIAN_SURNAME_SUFFIXES = ("ov", "ova", "ev", "eva", "in", "ina", "sky", "skiy", "skaya", "ich")

STOPWORDS = {
    # Romanian stopwords
    "si", "și", "in", "în", "la", "de", "cu", "din", "pe", "pentru", "o", "un", "unui",
    "unei", "despre", "comitet", "sedinta", "ședință", "raport", "proces", "verbal",
    "director", "medical", "al", "ale", "ai", "ale", "sau", "dar", "iar", "sub", "spre",
    "catre", "către", "peste", "prin", "fara", "fără", "contra", "intre", "între",
    # Russian stopwords
    "и", "в", "на", "с", "по", "о", "об", "для", "от", "до", "из", "к", "за",
    "собрание", "заседание", "отчет", "протокол", "или", "но", "как", "так", "все",
    "это", "при", "после", "перед", "под", "над", "между",
    # English stopwords
    "and", "in", "on", "with", "for", "of", "to", "the", "a", "an", "meeting",
    "report", "minutes", "by", "at", "from", "into", "about", "over", "after",
    "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
}

# Predefined high-frequency clinical vocabulary by department
DEPARTMENT_TERMS: dict[str, list[tuple[str, CategoryType, float]]] = {
    "cardiologie": [
        ("stent", "procedure", 2.2),
        ("angioplastie", "procedure", 2.2),
        ("cateterism", "procedure", 2.0),
        ("bypass coronarian", "procedure", 2.0),
        ("coronarografie", "procedure", 2.0),
        ("troponină", "medication", 1.9),
        ("infarct", "term", 1.8),
        ("ecocardiografie", "procedure", 1.8),
        ("fibrilație atrială", "term", 1.7),
        ("Cardiologie", "department", 2.0),
    ],
    "cardiology": [
        ("stent", "procedure", 2.2),
        ("angioplastie", "procedure", 2.2),
        ("angioplasty", "procedure", 2.2),
        ("cateterism", "procedure", 2.0),
        ("catheterization", "procedure", 2.0),
        ("bypass coronarian", "procedure", 2.0),
        ("coronarografie", "procedure", 2.0),
        ("troponină", "medication", 1.9),
        ("infarct", "term", 1.8),
        ("Cardiology", "department", 2.0),
    ],
    "chirurgie": [
        ("laparoscopie", "procedure", 2.2),
        ("hemostază", "procedure", 2.1),
        ("sutură", "procedure", 2.1),
        ("bloc operator", "term", 2.0),
        ("incizie", "procedure", 1.9),
        ("drenaj", "procedure", 1.9),
        ("apendicectomie", "procedure", 1.8),
        ("colecistectomie", "procedure", 1.8),
        ("Chirurgie", "department", 2.0),
    ],
    "surgery": [
        ("laparoscopie", "procedure", 2.2),
        ("laparoscopy", "procedure", 2.2),
        ("hemostază", "procedure", 2.1),
        ("hemostasis", "procedure", 2.1),
        ("sutură", "procedure", 2.1),
        ("operating room", "term", 2.0),
        ("incizie", "procedure", 1.9),
        ("drenaj", "procedure", 1.9),
        ("Surgery", "department", 2.0),
    ],
    "terapie intensiva": [
        ("ATI", "department", 2.2),
        ("intubație", "procedure", 2.1),
        ("ventilație mecanică", "procedure", 2.1),
        ("noradrenalină", "medication", 2.0),
        ("PEEP", "term", 2.0),
        ("CPAP", "term", 1.9),
        ("sedare", "medication", 1.9),
        ("Terapie Intensivă", "department", 2.0),
    ],
    "terapie intensivă": [
        ("ATI", "department", 2.2),
        ("intubație", "procedure", 2.1),
        ("ventilație mecanică", "procedure", 2.1),
        ("noradrenalină", "medication", 2.0),
        ("PEEP", "term", 2.0),
        ("CPAP", "term", 1.9),
        ("sedare", "medication", 1.9),
        ("Terapie Intensivă", "department", 2.0),
    ],
    "ati": [
        ("ATI", "department", 2.2),
        ("intubație", "procedure", 2.1),
        ("ventilație mecanică", "procedure", 2.1),
        ("noradrenalină", "medication", 2.0),
        ("PEEP", "term", 2.0),
        ("CPAP", "term", 1.9),
        ("sedare", "medication", 1.9),
    ],
    "icu": [
        ("ICU", "department", 2.2),
        ("intubation", "procedure", 2.1),
        ("mechanical ventilation", "procedure", 2.1),
        ("norepinephrine", "medication", 2.0),
        ("PEEP", "term", 2.0),
        ("CPAP", "term", 1.9),
    ],
    "neurologie": [
        ("accident vascular cerebral", "term", 2.2),
        ("AVC", "term", 2.2),
        ("tromboliză", "procedure", 2.1),
        ("ischemie", "term", 2.0),
        ("RMN", "procedure", 2.0),
        ("electroencefalogramă", "procedure", 1.9),
        ("Neurologie", "department", 2.0),
    ],
    "neurology": [
        ("stroke", "term", 2.2),
        ("thrombolysis", "procedure", 2.1),
        ("ischemia", "term", 2.0),
        ("MRI", "procedure", 2.0),
        ("EEG", "procedure", 1.9),
        ("Neurology", "department", 2.0),
    ],
    "oncologie": [
        ("chimioterapie", "procedure", 2.2),
        ("biopsie", "procedure", 2.1),
        ("radioterapie", "procedure", 2.1),
        ("metastază", "term", 2.0),
        ("marker tumoral", "term", 1.9),
        ("citostatic", "medication", 1.9),
        ("Oncologie", "department", 2.0),
    ],
    "oncology": [
        ("chemotherapy", "procedure", 2.2),
        ("biopsy", "procedure", 2.1),
        ("radiotherapy", "procedure", 2.1),
        ("metastasis", "term", 2.0),
        ("tumor marker", "term", 1.9),
        ("Oncology", "department", 2.0),
    ],
}


def cyrillic_to_latin(text: str) -> str:
    """Deterministic transliteration from Cyrillic to Latin."""
    return "".join(CYRILLIC_TO_LATIN.get(c, c) for c in text)


def latin_to_cyrillic(text: str) -> str:
    """Deterministic transliteration from Latin to Cyrillic for Russian surnames."""
    low = text.lower()
    for m, c in LATIN_TO_CYRILLIC_MULTI:
        low = low.replace(m, c)
    res = [LATIN_TO_CYRILLIC_SINGLE.get(ch, ch) for ch in low]
    out = "".join(res)
    if text and text[0].isupper():
        out = out.capitalize()
    return out


_TOKENIZER_INSTANCE: Any = None


def get_whisper_tokenizer() -> Any:
    """Loads Whisper tokenizer if available, caching the instance."""
    global _TOKENIZER_INSTANCE
    if _TOKENIZER_INSTANCE is not None:
        return _TOKENIZER_INSTANCE
    try:
        import tokenizers
        # Check standard large-v3-turbo snapshot
        candidate = Path("data/models/models--mobiuslabsgmbh--faster-whisper-large-v3-turbo/snapshots/0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf/tokenizer.json")
        if candidate.exists():
            _TOKENIZER_INSTANCE = tokenizers.Tokenizer.from_file(str(candidate))
            return _TOKENIZER_INSTANCE
        if settings.MODELS_DIR and settings.MODELS_DIR.exists():
            for p in settings.MODELS_DIR.glob("**/tokenizer.json"):
                _TOKENIZER_INSTANCE = tokenizers.Tokenizer.from_file(str(p))
                return _TOKENIZER_INSTANCE
    except Exception:
        pass
    return None


def count_tokens(text: str, tokenizer: Any = None) -> int:
    """
    Counts tokens for a text string using Whisper tokenizer or conservative offline fallback.
    """
    if not text or not text.strip():
        return 0
    if tokenizer is None:
        tokenizer = get_whisper_tokenizer()
    if tokenizer is not None:
        try:
            return len(tokenizer.encode(" " + text.strip(), add_special_tokens=False).ids)
        except Exception:
            pass
    # Offline fallback estimation
    tokens = 0
    words = text.split()
    for w in words:
        clean = w.strip(".,;:?!\"'()[]{}")
        if not clean:
            continue
        has_cyr = any("\u0400" <= ch <= "\u04FF" for ch in clean)
        if has_cyr:
            tokens += max(1, int(len(clean) / 2.0 + 0.5))
        else:
            tokens += max(1, int(len(clean) / 3.5 + 0.5))
    tokens += text.count(",") + text.count(".")
    return max(1, tokens)


def extract_attendee_terms(attendee: Attendee) -> list[ContextTerm]:
    """
    Extracts high-priority attendee terms, preserving and transliterating Russian/Romanian doctor names.
    Priority 1: Attendee family names present in meeting (highest confusion risk: doctor names).
    """
    raw_name = (attendee.name or "").strip()
    if not raw_name:
        return []
    clean_name = HONORIFIC_PREFIX_RE.sub("", raw_name).strip()
    if not clean_name:
        clean_name = raw_name

    parts = clean_name.split()
    family_name = parts[-1] if parts else clean_name

    terms: list[ContextTerm] = []
    has_cyrillic = any("\u0400" <= ch <= "\u04FF" for ch in clean_name)

    # 1. Family name (highest confusion risk: weight 3.0)
    terms.append(ContextTerm(
        text=family_name,
        category="attendee",
        source="attendee_family_name",
        weight=3.0,
    ))

    # Full name if distinct from family name
    if len(parts) > 1:
        terms.append(ContextTerm(
            text=clean_name,
            category="attendee",
            source="attendee_full_name",
            weight=2.5,
        ))

    # Transliteration support (Cyrillic <-> Latin preservation)
    if has_cyrillic:
        lat_family = cyrillic_to_latin(family_name)
        if lat_family and lat_family != family_name:
            terms.append(ContextTerm(
                text=lat_family,
                category="attendee",
                source="attendee_family_name_translit",
                weight=3.0,
            ))
        if len(parts) > 1:
            lat_full = cyrillic_to_latin(clean_name)
            if lat_full and lat_full != clean_name:
                terms.append(ContextTerm(
                    text=lat_full,
                    category="attendee",
                    source="attendee_full_name_translit",
                    weight=2.5,
                ))
    elif attendee.primary_language == "ru" or family_name.lower().endswith(RUSSIAN_SURNAME_SUFFIXES):
        cyr_family = latin_to_cyrillic(family_name)
        if cyr_family and cyr_family != family_name:
            terms.append(ContextTerm(
                text=cyr_family,
                category="attendee",
                source="attendee_family_name_translit",
                weight=3.0,
            ))

    return terms


def extract_department_terms(department: str) -> list[ContextTerm]:
    """
    Extracts terms for meeting department (Priority 2).
    E.g., "Cardiologie" -> "stent", "angioplastie", etc.
    """
    clean_dept = department.strip()
    if not clean_dept:
        return []

    dept_key = clean_dept.lower()
    terms: list[ContextTerm] = []

    # Check exact or partial match in predefined department vocabularies
    matched = False
    for k, term_list in DEPARTMENT_TERMS.items():
        if k in dept_key or dept_key in k:
            matched = True
            for text, cat, weight in term_list:
                terms.append(ContextTerm(
                    text=text,
                    category=cat,
                    source=f"department_vocab:{k}",
                    weight=weight,
                ))

    # Always include department name itself
    terms.append(ContextTerm(
        text=clean_dept,
        category="department",
        source="meeting_department",
        weight=2.0,
    ))

    return terms


def extract_verified_terms(
    store: Optional[AdaptationStore] = None,
    department: Optional[str] = None,
) -> list[ContextTerm]:
    """
    Extracts verified vocabulary terms approved for this department from Task 4 verified pool (Priority 3).
    """
    if not department or not department.strip():
        return []
    if store is None:
        store = adaptation_store
    try:
        events = store.list_events(verification_status="verified", limit=50)
        terms: list[ContextTerm] = []
        for ev in events:
            text = (ev.get("new_text") or "").strip()
            if text and len(text.split()) <= 4:
                kind = ev.get("edit_kind", "term")
                cat: CategoryType = "term"
                if kind in ("medication", "drug"):
                    cat = "medication"
                elif kind in ("procedure", "surgery"):
                    cat = "procedure"
                terms.append(ContextTerm(
                    text=text,
                    category=cat,
                    source="verified_catalog",
                    weight=1.5,
                ))
        return terms
    except Exception as exc:
        logger.debug(f"Could not load verified terms from adaptation catalog: {exc}")
        return []


def extract_agenda_title_terms(title: str, agenda: Optional[str] = None) -> list[ContextTerm]:
    """
    Extracts title and agenda keywords filtered for stopwords (Priority 4).
    """
    combined = f"{title or ''} {agenda or ''}".strip()
    if not combined:
        return []

    words = re.findall(r"\b[A-Za-zĂăÂâÎîȘșȚțА-Яа-яЁё]{3,}\b", combined)
    terms: list[ContextTerm] = []
    seen = set()
    for w in words:
        low = w.lower()
        if low not in STOPWORDS and low not in seen:
            seen.add(low)
            terms.append(ContextTerm(
                text=w,
                category="term",
                source="meeting_title_or_agenda",
                weight=1.0,
            ))
    return terms


def deduplicate_and_sort_terms(terms: list[ContextTerm]) -> list[ContextTerm]:
    """
    Deduplicates terms preserving the highest weight, and sorts deterministically:
    weight descending, then text ascending (case-insensitive).
    """
    by_text: dict[str, ContextTerm] = {}
    for t in terms:
        clean_text = t.text.strip()
        if not clean_text:
            continue
        key = clean_text.lower()
        if key not in by_text:
            by_text[key] = t
        else:
            existing = by_text[key]
            if t.weight > existing.weight:
                by_text[key] = t
            elif t.weight == existing.weight and t.text < existing.text:
                by_text[key] = t

    sorted_terms = sorted(by_text.values(), key=lambda t: (-t.weight, t.text.lower()))
    return sorted_terms


def budget_hotwords(
    terms: list[ContextTerm],
    max_hotwords: int = 40,
    max_tokens: int = 80,
    tokenizer: Any = None,
) -> tuple[tuple[str, ...], str]:
    """
    Budgets hotwords (max 40) and prompt_seed (max 80 tokens).
    Prioritization order is preserved during truncation.
    """
    if not terms:
        return (), ""

    # 1. Hotwords: up to max_hotwords items
    hotwords = tuple(t.text for t in terms[:max_hotwords])

    # 2. Prompt seed: up to max_tokens tokens
    selected_seed_terms: list[str] = []
    current_seed = ""
    for t in terms:
        candidate = f"{current_seed}, {t.text}" if current_seed else t.text
        if count_tokens(candidate, tokenizer) <= max_tokens:
            selected_seed_terms.append(t.text)
            current_seed = candidate
        else:
            # Token budget reached
            break

    return hotwords, current_seed


def build_context(
    meeting: MeetingBase,
    *,
    enabled: Optional[bool] = None,
    store: Optional[AdaptationStore] = None,
    tokenizer: Any = None,
    max_hotwords: int = 40,
    max_tokens: int = 80,
) -> ASRContext:
    """
    Builds deterministic, immutable ASRContext from meeting metadata and clinical vocabulary.
    Returns empty ASRContext if dynamic context is disabled or meeting contains no context.
    """
    if enabled is None:
        enabled = getattr(settings, "ASR_DYNAMIC_CONTEXT_ENABLED", False)

    if not enabled or meeting is None:
        return ASRContext()

    all_terms: list[ContextTerm] = []

    # Priority 1: Attendee family names & full names
    for att in getattr(meeting, "attendees", []):
        all_terms.extend(extract_attendee_terms(att))

    # Priority 2: Meeting department terms
    dept = getattr(meeting, "asr_department", None)
    if not dept:
        for att in getattr(meeting, "attendees", []):
            if getattr(att, "department", None):
                dept = att.department
                break
    if dept:
        all_terms.extend(extract_department_terms(dept))

    # Priority 3: Verified vocabulary terms approved for this department (Task 4 verified pool)
    all_terms.extend(extract_verified_terms(store=store, department=dept))

    # Priority 4: Agenda title words (filtered for stopwords)
    all_terms.extend(extract_agenda_title_terms(
        getattr(meeting, "title", "") or "",
        getattr(meeting, "agenda", None),
    ))

    if not all_terms:
        return ASRContext()

    sorted_terms = deduplicate_and_sort_terms(all_terms)
    hotwords, prompt_seed = budget_hotwords(
        sorted_terms,
        max_hotwords=max_hotwords,
        max_tokens=max_tokens,
        tokenizer=tokenizer,
    )

    return ASRContext(
        terms=tuple(sorted_terms),
        prompt_seed=prompt_seed,
        hotwords=hotwords,
    )
