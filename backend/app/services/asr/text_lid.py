"""
Medpark Meeting Intelligence System - Text / Script Language Identification
Free, offline check of the DECODED text that gates a second decode when it disagrees with acoustic LID.

It cannot fix a wrong decode: Romanian speech forced through the Russian token comes out as Cyrillic
gibberish that this module will happily call "ru". Its value is the disagreement signal (validated at
5/27 windows on the real recording) and the word-level language spans inside genuinely mixed windows.
"""

from dataclasses import dataclass
import re
from typing import Iterable, Literal, Optional

TextLanguage = Literal["ro", "ru", "en", "mixed", "und"]

CYRILLIC_RE = re.compile(r"[Ѐ-ӿ]")
LATIN_RE = re.compile(r"[A-Za-zÀ-ɏ]")
ROMANIAN_DIACRITICS_RE = re.compile(r"[ăâîșțĂÂÎȘȚşţŞŢ]")
WORD_RE = re.compile(r"[^\W\d_]+(?:[-'][^\W\d_]+)*", re.UNICODE)

RU_RATIO_MIN = 0.60     # Cyrillic share above this -> "ru"
MIXED_RATIO_MIN = 0.15  # between MIXED_RATIO_MIN and RU_RATIO_MIN -> "mixed"
DIACRITIC_WEIGHT = 2.0  # each Romanian diacritic counts double against English stopwords

# Function words that are unambiguous between Romanian and English. Words that occur in both
# ("care", "am", "mai", "a", "un"/"o" article vs. sound) are deliberately absent from both lists.
ROMANIAN_STOPWORDS = frozenset("""
și si este sunt pentru la de cu nu să sa că ca în pe din dacă daca avem fost acolo aici cum noi ce se dar
foarte trebuie au lui acest această aceasta deja unde când cand tot așa asa sau după dupa până pana între
intre fără fara doar acum atunci încă inca fiecare toate toți toti nimic ceva altceva pacient pacientul
pacienta pacientii pacienții secția sectia spital spitalul domnul doamna medicul doctorul suntem aveți aveti
puteți puteti facem făcut facut vom vor mă ma vă va îl il le lor lui ei ele este era erau fie fiind decât decat
adică adica bine da ca să
""".split())

ENGLISH_STOPWORDS = frozenset("""
the and is are to of for with that this we you it in on not have has be was were do does what how about from
will can should our they there if so but at by an or as all he she his her would could then them their been
than into which when where who why because also just very more most some any each other patient patients
hospital doctor please okay
""".split())

# Ambiguous tokens removed from both sets even if listed above (defensive against edits).
_AMBIGUOUS = frozenset({"a", "am", "care", "mai", "o", "un", "no", "me", "i"})
ROMANIAN_STOPWORDS = ROMANIAN_STOPWORDS - _AMBIGUOUS
ENGLISH_STOPWORDS = ENGLISH_STOPWORDS - _AMBIGUOUS

# Cyrillic text is not necessarily Russian: Romanian speech forced through <|ru|> comes out as Romanian
# TRANSLITERATED into Cyrillic ("инфаркт миокардика, тромбо-аспирация", "ди трансфер, ла моменту" -
# measured on the real recording), and its avg_logprob can beat the correct Romanian decode. Romanian
# function words in Cyrillic spelling betray it; Russian function words confirm real Russian.
RUSSIAN_STOPWORDS = frozenset("""
и в не на что это он она они мы вы я с по как так но у же уже есть был была было были быть для от до из к об
за при или если то тоже также только здесь там где когда потом сейчас нужно надо можно будет будем хорошо
давай давайте его ее её их нет ещё еще чтобы потому значит всё все этот эта который которая конечно правильно
сегодня завтра пациент пациента пациенту больной перевод
""".split())
ROMANIAN_CYRILLIC_STOPWORDS = frozenset("""
де ку ши ла ын ун есте сунт пентру дакэ дака аколо ачум акум авем каре сэ кэ фоарте требуе дупэ пынэ аша аса
пе дин чева ной ел еа ей ел момент моменту трансфер деч адикэ чи фост ынкэ атунч доар тоате унде кынд кум че се
лор луй песте фэрэ ынтре спре кэтре бине поате путем авець путець ачест ачаста ачеста аич ноастрэ ностру
пачиент пачиентул спитал сунтем авем факем ку
""".split())
_CYRILLIC_AMBIGUOUS = frozenset({"а", "о", "да", "ну", "тот", "май", "дар", "нет"})
RUSSIAN_STOPWORDS = RUSSIAN_STOPWORDS - _CYRILLIC_AMBIGUOUS
ROMANIAN_CYRILLIC_STOPWORDS = ROMANIAN_CYRILLIC_STOPWORDS - _CYRILLIC_AMBIGUOUS
TRANSLIT_MIN_HITS = 2


@dataclass(frozen=True)
class TextLID:
    language: TextLanguage
    confidence: float          # 0..1; 0 means "no evidence" (und with letters present)
    cyrillic_ratio: float
    ro_score: float
    en_score: float
    letters: int

    @property
    def is_concrete(self) -> bool:
        return self.language in ("ro", "ru", "en")


def _letters(text: str) -> tuple[int, int]:
    cyr = len(CYRILLIC_RE.findall(text))
    lat = len(LATIN_RE.findall(text))
    return cyr, lat


def _latin_scores(words: Iterable[str], text: str) -> tuple[float, float]:
    ro = float(sum(1 for w in words if w in ROMANIAN_STOPWORDS))
    en = float(sum(1 for w in words if w in ENGLISH_STOPWORDS))
    ro += DIACRITIC_WEIGHT * len(ROMANIAN_DIACRITICS_RE.findall(text))
    return ro, en


def detect_text_language(text: str) -> TextLID:
    """
    Script-first language guess for a decoded window.

    Cyrillic ratio > 0.60 -> ru; 0.15..0.60 -> mixed; otherwise Romanian vs English by stopword hits
    with Romanian diacritics counted twice. "und" when the text has no letters at all (confidence 1.0,
    the garbage filter will flag it) or when Latin text carries no stopword/diacritic evidence
    (confidence 0.0: the acoustic decision stands).
    """
    cyr, lat = _letters(text)
    letters = cyr + lat
    if letters == 0:
        return TextLID("und", 1.0, 0.0, 0.0, 0.0, 0)
    ratio = cyr / letters
    if ratio > RU_RATIO_MIN:
        return TextLID("ru", round(min(1.0, 0.5 + ratio / 2), 3), ratio, 0.0, 0.0, letters)
    if ratio >= MIXED_RATIO_MIN:
        # Confidence grows with the balance of the two scripts.
        balance = 1.0 - abs(ratio - (RU_RATIO_MIN + MIXED_RATIO_MIN) / 2) / ((RU_RATIO_MIN - MIXED_RATIO_MIN) / 2)
        return TextLID("mixed", round(max(0.5, min(1.0, 0.5 + balance / 2)), 3), ratio, 0.0, 0.0, letters)

    words = [w.lower() for w in WORD_RE.findall(text)]
    ro, en = _latin_scores(words, text)
    total = ro + en
    if total == 0:
        return TextLID("und", 0.0, ratio, ro, en, letters)
    margin = abs(ro - en) / total
    # Evidence saturation: 4+ scoring tokens with a clear margin is a confident call.
    evidence = min(1.0, total / 4.0)
    confidence = round(margin * (0.5 + 0.5 * evidence), 3)
    return TextLID("ro" if ro >= en else "en", confidence, ratio, ro, en, letters)


def _word_language(word: str) -> Optional[str]:
    cyr, lat = _letters(word)
    if cyr and not lat:
        return "ru"
    if cyr and lat:
        return None
    if not lat:
        return None
    lowered = word.lower()
    if ROMANIAN_DIACRITICS_RE.search(word) or lowered in ROMANIAN_STOPWORDS:
        return "ro"
    if lowered in ENGLISH_STOPWORDS:
        return "en"
    return None


def language_spans(words: Iterable, default_language: Optional[str] = None) -> list[dict]:
    """
    Word-level language runs as [{"start", "end", "language"}] for a (mixed) segment.

    `words` are faster-whisper Word objects or dicts with start/end/word (absolute times). Cyrillic
    words are "ru"; Latin words are "ro"/"en" only on diacritic/stopword evidence, otherwise they
    inherit the previous decided word (or `default_language`, or the next decided word). Words that
    never resolve are dropped from the spans; adjacent equal-language runs are merged.
    """
    items = []
    for w in words:
        if isinstance(w, dict):
            start, end, token = w["start"], w["end"], w["word"]
        else:
            start, end, token = w.start, w.end, w.word
        items.append([float(start), float(end), _word_language(token.strip())])
    if not items:
        return []

    # Forward fill from the previous decided word, then backward fill leading unknowns.
    last = default_language if default_language in ("ro", "ru", "en") else None
    for item in items:
        if item[2] is None:
            item[2] = last
        else:
            last = item[2]
    nxt = None
    for item in reversed(items):
        if item[2] is None:
            item[2] = nxt
        else:
            nxt = item[2]

    spans: list[dict] = []
    for start, end, lang in items:
        if lang is None:
            continue
        if spans and spans[-1]["language"] == lang:
            spans[-1]["end"] = max(spans[-1]["end"], round(end, 2))
        else:
            spans.append({"start": round(start, 2), "end": round(end, 2), "language": lang})
    return spans
