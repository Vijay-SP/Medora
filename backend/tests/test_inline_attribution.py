"""
Offline tests for inline speaker attribution in the minutes (contracts N1-N3):

  N1  the map/synthesis prompts attribute prose to anonymous labels ("S3 a propus ..."), every map item
      carries `speakers`, new extractions are stamped speaker_label_style="labels";
  N2  `ground_speaker_labels` repairs any S<n> token that no cited segment can vouch for, the engine flags
      the repair (needs_name_review + ONE medium-severity "NOTĂ AUDIT" item) and grounds the summary too;
  N3  `attribution_render` maps "S1" / "Speaker 1" to a reviewer-confirmed name only when the cluster has a
      printable confirmed/corrected segment, else to the localized anonymous form; render_minutes is a deep
      copy that never mutates the stored object and is a no-op on impersonal minutes.

    PYTHONPATH=backend .venv\\Scripts\\python.exe backend\\tests\\test_inline_attribution.py

No Whisper, no Ollama (dead port; the extraction run uses a FakeClient), isolated storage, dead SMTP port.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_ROOT = Path(tempfile.mkdtemp(prefix="medpark_test_inline_attr_"))
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

import asyncio  # noqa: E402
import re  # noqa: E402
import sys  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from typing import Any  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.models.extraction import ActionItem, DecisionItem, EvidenceQuote, MinutesOfMeeting, RiskOrQuestionItem  # noqa: E402
from app.models.meeting import Attendee, Meeting, MeetingType  # noqa: E402
from app.models.transcript import SpeakerSuggestion, Transcript, TranscriptSegment  # noqa: E402
from app.services.extraction.attribution_render import ANON, LABEL_RE, SPEAKER_RE, build_label_map, render_minutes, render_text  # noqa: E402
from app.services.extraction.llm_engine import LocalLLMExtractor  # noqa: E402
from app.services.extraction.prompt_templates import EXTRACTION_MAP_SYSTEM_PROMPT, SYNTHESIS_SYSTEM_PROMPT  # noqa: E402
from app.services.extraction.schemas import MAP_SCHEMA  # noqa: E402
from app.services.extraction.validator import ground_speaker_labels  # noqa: E402
from app.storage.repository import repository  # noqa: E402

NAME_A = "Dr. Ana Popescu"
NAME_R = "Dr. Ion Rusu"
LABEL_GUEST = "Consultant extern"
ROSTER = "Dr. Elena Ceban"
FLOOR = float(settings.SPEAKER_MIN_PRINTABLE_SPEECH_S)
_RANGE_PATTERN = re.compile(r"liniile (\d+)-(\d+)")
_AUDIT_REPAIR_TEXT = "atribuirea vorbitorilor a fost corectată automat"


# ---------------------------------------------------------------- fixtures
def _seg(seg_id: str, start: float, end: float, label: str, text: str, speech: float, **extra) -> TranscriptSegment:
    fields: dict[str, Any] = dict(id=seg_id, start=start, end=end, speaker=label, raw_text=text, speech_seconds=speech,
                                  cluster_id="SPEAKER_%02d" % int(label.split()[1]))
    fields.update(extra)
    return TranscriptSegment(**fields)


def _named(name: str, state: str = "confirmed", printable: bool = True, **extra) -> dict[str, Any]:
    fields = dict(attribution_state=state, speaker_id="person-" + name.split()[-1].lower(), confirmed_display_name=name,
                  confirmed_by="Dr. Rev (Reviewer)", confirmed_at=datetime.now(timezone.utc), confirmed_for_revision=1,
                  printable_name=printable)
    fields.update(extra)
    return fields


def render_transcript() -> Transcript:
    """
    Five clusters covering every state the render layer must distinguish:
      Speaker 1  confirmed (voiceprint), one printable turn + one 1.0 s turn below the floor  -> name
      Speaker 2  anonymous                                                                    -> anonymous
      Speaker 3  confirmed but ONLY turns below the printable floor                           -> anonymous
      Speaker 4  suggested (a voiceprint match nobody confirmed)                              -> anonymous
      Speaker 5  corrected with a reviewer LABEL (no Person record), printable                -> label
    """
    suggestion = SpeakerSuggestion(person_id="person-x", person_name="Dr. Never Printed", score=0.9, margin=0.4, band="strong", space_id="s")
    segments = [
        _seg("s1", 0.0, 6.0, "Speaker 1", "Aprobăm protocolul de anticoagulare.", 5.5, **_named(NAME_A)),
        _seg("s2", 6.5, 7.7, "Speaker 1", "Da.", 1.0, **_named(NAME_A, printable=False)),
        _seg("s3", 8.0, 13.0, "Speaker 2", "Propun actualizarea listei de medicamente până vineri.", 4.5),
        _seg("s4", 15.0, 16.2, "Speaker 3", "Okей.", 1.0, **_named(NAME_R, printable=False)),
        _seg("s5", 17.0, 22.0, "Speaker 4", "Rămâne deschisă întrebarea privind bugetul.", 4.0,
             attribution_state="suggested", suggestion=suggestion, suggested_identity=suggestion.person_name),
        _seg("s6", 23.0, 28.0, "Speaker 5", "Semnalez riscul epuizării stocului de meropenem.", 4.5,
             **_named(LABEL_GUEST, state="corrected", speaker_id=None, attribution_basis="reviewer_label")),
    ]
    transcript = Transcript(meeting_id="render-test", segments=segments)
    transcript.compute_stats()
    return transcript


def _quote(seg: TranscriptSegment) -> EvidenceQuote:
    return EvidenceQuote(segment_id=seg.id, start=seg.start, end=seg.end, quote=seg.display_text, speaker=seg.speaker)


def labelled_minutes(transcript: Transcript) -> MinutesOfMeeting:
    by_id = {seg.id: seg for seg in transcript.segments}
    return MinutesOfMeeting(
        meeting_id=transcript.meeting_id, title="Ședință test", meeting_type="medical", speaker_label_style="labels",
        summary_ro="S1 a deschis ședința. S2 a propus actualizarea listei; S1 a aprobat. S5 a semnalat un risc. S3 și S4 nu au decis nimic.",
        summary_ru="S1 открыл заседание. S2 предложил обновить список; S1 одобрил. S5 отметил риск.",
        summary_en="S1 opened the meeting. S2 proposed updating the list; S1 approved. S5 flagged a risk.",
        agenda_topics=["Protocol anticoagulare (S1)", "Lista de medicamente (S2)"],
        agenda_topics_ru=["Протокол (S1)"], agenda_topics_en=["Protocol (S1)"],
        decisions=[DecisionItem(topic="Protocoale ATI", decision="S1 a aprobat protocolul de anticoagulare.",
                                topic_ru="Протоколы", decision_ru="S1 одобрил протокол.", topic_en="ICU protocols", decision_en="S1 approved the protocol.",
                                evidence=[_quote(by_id["s1"]), _quote(by_id["s2"])])],
        action_items=[
            ActionItem(id="act-s1", task="S1 va actualiza lista de medicamente.", task_ru="S1 обновит список.", task_en="S1 will update the list.",
                       owner="Speaker 1", owner_source="speaker", deadline_phrase="până vineri", evidence=[_quote(by_id["s1"])]),
            ActionItem(id="act-s2", task="S2 va pregăti lista.", task_ru="S2 подготовит список.", task_en="S2 will prepare the list.",
                       owner="Speaker 2", owner_source="speaker", evidence=[_quote(by_id["s3"])]),
            ActionItem(id="act-roster", task="Verificarea dozajului conform S2.", owner=ROSTER, owner_source="roster", evidence=[_quote(by_id["s3"])]),
            ActionItem(id="act-none", task="Sarcină fără responsabil.", owner="Unassigned", owner_source="unassigned", evidence=[_quote(by_id["s5"])]),
            ActionItem(id="act-s5", task="S5 va verifica stocul.", owner="Speaker 5", owner_source="speaker", evidence=[_quote(by_id["s6"])]),
        ],
        risks_and_questions=[RiskOrQuestionItem(item_type="risk", description="S5 a semnalat riscul epuizării stocului.",
                                                description_ru="S5 отметил риск.", description_en="S5 flagged the stock risk.",
                                                evidence=[_quote(by_id["s6"])])],
        model_version="test-fixture",
    )


# ---------------------------------------------------------------- N3 label map
def test_build_label_map_respects_floor_states_and_locales():
    transcript = render_transcript()
    for locale in ("ro", "en", "ru"):
        label_map = build_label_map(transcript, locale)
        anon = lambda n: ANON[locale].format(n=n)  # noqa: E731
        # both token forms of every cluster are present and agree
        for n in range(1, 6):
            assert label_map[f"S{n}"] == label_map[f"Speaker {n}"], (locale, n)
        assert label_map["S1"] == NAME_A, "confirmed cluster with a printable turn prints its name"
        assert label_map["S2"] == anon(2), "anonymous cluster"
        assert label_map["S3"] == anon(3), "confirmed cluster whose every turn is below the printable floor stays anonymous"
        assert label_map["S4"] == anon(4), "a suggestion never renders as a name"
        assert label_map["S5"] == LABEL_GUEST, "a reviewer label without a Person record prints like a confirmed name"
        assert "Dr. Never Printed" not in label_map.values()
        assert NAME_R not in label_map.values()
    assert build_label_map(render_transcript(), "ro")["Speaker 2"] == "Vorbitorul 2"
    assert build_label_map(render_transcript(), "en")["Speaker 2"] == "Speaker 2"
    assert build_label_map(render_transcript(), "ru")["Speaker 2"] == "Участник 2"
    # the floor itself: exactly SPEAKER_MIN_PRINTABLE_SPEECH_S of speech is printable, a hair less is not
    assert FLOOR == 2.0
    empty = Transcript(meeting_id="x", segments=[])
    assert build_label_map(empty, "ro") == {}
    print("PASS test_build_label_map_respects_floor_states_and_locales")


def test_render_text_substitutes_both_forms_idempotently():
    transcript = render_transcript()
    ro = build_label_map(transcript, "ro")
    text = "S1 a propus; Speaker 2 a aprobat; S5 a semnalat; S3 a tăcut."
    once = render_text(text, ro, "ro")
    assert once == f"{NAME_A} a propus; Vorbitorul 2 a aprobat; {LABEL_GUEST} a semnalat; Vorbitorul 3 a tăcut.", once
    assert render_text(once, ro, "ro") == once, "idempotent"
    assert render_text(None, ro, "ro") is None
    assert render_text("", ro, "ro") == ""
    # a token of a cluster the transcript does not know is left exactly as written: never a name, never re-attributed
    # (extraction-time grounding keeps such tokens out of stored prose, see test_extraction_repairs_fabricated_label_and_flags_it);
    # non-tokens stay untouched, and so does the "Speaker n" form of an unknown cluster
    unknown = "S10 și S12 lipsesc; IS1 și S1a și S123 rămân; Speaker 10 lipsește."
    assert render_text(unknown, ro, "ro") == unknown, render_text(unknown, ro, "ro")
    assert "S10" not in ro and "Speaker 10" not in ro
    # a known label next to an unknown one: only the known one is substituted
    assert render_text("S10 și S1 au propus.", ro, "ro") == f"S10 și {NAME_A} au propus."
    # clinical S<n> notation is never rendered, even though S1/S2 are clusters of this transcript (S1 is named)
    clinical = "Hernie de disc L5-S1; zgomotele cardiace S1 și S2; S1-S2 și S1/S2; S1.5; radiculopatie S1."
    assert render_text(clinical, ro, "ro") == clinical, render_text(clinical, ro, "ro")
    assert render_text("zgomotele S1 și S2 sunt normale; S1 a aprobat.", ro, "ro") == f"zgomotele S1 și S2 sunt normale; {NAME_A} a aprobat."
    en = build_label_map(transcript, "en")
    assert render_text("S2 will; Speaker 2 will", en, "en") == "Speaker 2 will; Speaker 2 will"
    assert render_text(render_text("S2 will", en, "en"), en, "en") == "Speaker 2 will"
    ru = build_label_map(transcript, "ru")
    assert render_text("S2 предложил, S1 одобрил", ru, "ru") == f"Участник 2 предложил, {NAME_A} одобрил"
    # the exported regexes: SPEAKER_RE is the contract pattern; LABEL_RE matches the contract token S<1-2 digits> standing
    # alone, with the clinical-safe lookarounds so ranges, codes and decimals are not tokens
    assert SPEAKER_RE.pattern == r"\bSpeaker (\d{1,2})\b"
    for standalone in ("S1", "S12", "(S3)", "S2,", "S4.", "S1; S2", "S3 a propus"):
        assert LABEL_RE.search(standalone), standalone
    for not_a_token in ("IS1", "S1a", "S123", "L5-S1", "S1-S2", "C7/S1", "S1/S2", "S1–S2", "S1.5", "S2,5", "s1"):
        assert not LABEL_RE.search(not_a_token), not_a_token
    print("PASS test_render_text_substitutes_both_forms_idempotently")


def test_render_minutes_is_a_deep_copy_with_per_locale_forms():
    transcript = render_transcript()
    stored = labelled_minutes(transcript)
    before = stored.model_dump(mode="json")
    rendered = render_minutes(stored, transcript)
    assert rendered is not stored
    assert stored.model_dump(mode="json") == before, "the stored object is never mutated"

    # Romanian prose -> "ro" forms; the confirmed and the labelled clusters print their names
    assert rendered.summary_ro == (
        f"{NAME_A} a deschis ședința. Vorbitorul 2 a propus actualizarea listei; {NAME_A} a aprobat. "
        f"{LABEL_GUEST} a semnalat un risc. Vorbitorul 3 și Vorbitorul 4 nu au decis nimic."
    ), rendered.summary_ro
    assert rendered.summary_ru == f"{NAME_A} открыл заседание. Участник 2 предложил обновить список; {NAME_A} одобрил. {LABEL_GUEST} отметил риск."
    assert rendered.summary_en == f"{NAME_A} opened the meeting. Speaker 2 proposed updating the list; {NAME_A} approved. {LABEL_GUEST} flagged a risk."
    assert rendered.agenda_topics == [f"Protocol anticoagulare ({NAME_A})", "Lista de medicamente (Vorbitorul 2)"]
    assert rendered.agenda_topics_ru == [f"Протокол ({NAME_A})"] and rendered.agenda_topics_en == [f"Protocol ({NAME_A})"]
    dec = rendered.decisions[0]
    assert dec.decision == f"{NAME_A} a aprobat protocolul de anticoagulare."
    assert dec.decision_ru == f"{NAME_A} одобрил протокол." and dec.decision_en == f"{NAME_A} approved the protocol."
    assert dec.topic == "Protocoale ATI" and dec.topic_ru == "Протоколы"
    actions = {a.id: a for a in rendered.action_items}
    assert actions["act-s1"].task == f"{NAME_A} va actualiza lista de medicamente."
    assert actions["act-s1"].task_ru == f"{NAME_A} обновит список." and actions["act-s1"].task_en == f"{NAME_A} will update the list."
    assert actions["act-s2"].task == "Vorbitorul 2 va pregăti lista."
    assert actions["act-s2"].task_ru == "Участник 2 подготовит список." and actions["act-s2"].task_en == "Speaker 2 will prepare the list."
    assert actions["act-s1"].deadline_phrase == "până vineri"
    risk = rendered.risks_and_questions[0]
    assert risk.description == f"{LABEL_GUEST} a semnalat riscul epuizării stocului."
    assert risk.description_ru == f"{LABEL_GUEST} отметил риск." and risk.description_en == f"{LABEL_GUEST} flagged the stock risk."

    # owners follow the map only for speaker-derived owners; roster / unassigned owners are untouched
    assert actions["act-s1"].owner == NAME_A and actions["act-s1"].owner_source == "speaker"
    assert actions["act-s2"].owner in ("Speaker 2", "Vorbitorul 2"), "an anonymous owner stays anonymous"
    assert actions["act-roster"].owner == ROSTER and actions["act-none"].owner == "Unassigned"
    assert actions["act-s5"].owner == LABEL_GUEST
    # evidence speakers follow the map (a printable confirmed cluster) or stay anonymous
    assert dec.evidence[0].speaker == NAME_A
    assert actions["act-s2"].evidence[0].speaker in ("Speaker 2", "Vorbitorul 2")
    assert risk.evidence[0].speaker == LABEL_GUEST
    assert dec.evidence[1].segment_id == "s2" and dec.evidence[1].speaker == "Speaker 1", "a sub-floor quote of a named cluster stays anonymous"
    # nothing that may not print does: no suggestion, no sub-floor-only confirmation, no stray label token
    dump = rendered.model_dump_json()
    assert "Dr. Never Printed" not in dump and NAME_R not in dump
    for field in (rendered.summary_ro, rendered.summary_ru, rendered.summary_en, dec.decision, dec.decision_ru, dec.decision_en, risk.description):
        assert not LABEL_RE.search(field or ""), field
    # rendering twice is stable
    assert render_minutes(rendered, transcript).model_dump(mode="json") == rendered.model_dump(mode="json")
    print("PASS test_render_minutes_is_a_deep_copy_with_per_locale_forms")


def test_render_minutes_leaves_impersonal_minutes_unchanged():
    # A pre-label document: impersonal prose, anonymous owners, anonymous transcript -> byte-identical output
    transcript = Transcript(meeting_id="impersonal", segments=[
        _seg("i1", 0.0, 5.0, "Speaker 1", "Aprobăm protocolul.", 4.5),
        _seg("i2", 6.0, 11.0, "Speaker 2", "Eu pregătesc raportul.", 4.5),
    ])
    minutes = MinutesOfMeeting(
        meeting_id="impersonal", title="Vechi", summary_ro="Se aprobă protocolul; se pregătește raportul.",
        summary_en="The protocol is approved; the report will be prepared.",
        decisions=[DecisionItem(topic="Protocol", decision="Se aprobă protocolul.", evidence=[_quote(transcript.segments[0])])],
        action_items=[ActionItem(task="Pregătirea raportului.", owner="Speaker 2", owner_source="speaker", evidence=[_quote(transcript.segments[1])])],
        model_version="old",
    )
    assert minutes.speaker_label_style == "impersonal", "default keeps old stored minutes impersonal"
    rendered = render_minutes(minutes, transcript)
    assert rendered.model_dump(mode="json") == minutes.model_dump(mode="json")
    # ... and even with a confirmed cluster the impersonal prose has no token to rewrite
    transcript.segments[1] = _seg("i2", 6.0, 11.0, "Speaker 2", "Eu pregătesc raportul.", 4.5, **_named(NAME_A))
    rendered = render_minutes(minutes, transcript)
    assert rendered.summary_ro == minutes.summary_ro and rendered.decisions[0].decision == minutes.decisions[0].decision
    assert rendered.action_items[0].owner == NAME_A, "a speaker-derived owner still follows the confirmed cluster"
    print("PASS test_render_minutes_leaves_impersonal_minutes_unchanged")


def test_render_minutes_honours_the_printable_floor_per_segment():
    """
    Prose attributes the whole cluster, but structured fields are per segment (invariant 4): an evidence quote
    prints a name only when ITS segment is confirmed/corrected and printable, and a speaker-derived owner resolves
    to the name only when every evidence segment is printable and in that owner's cluster (the rule
    speakers._apply_attribution_to_minutes applies at decision time). Speaker 1: s1 printable, s2 1.0 s.
    """
    transcript = render_transcript()
    by_id = {seg.id: seg for seg in transcript.segments}
    stored = MinutesOfMeeting(
        meeting_id=transcript.meeting_id, title="Prag", speaker_label_style="labels", summary_ro="S1 a vorbit.",
        decisions=[DecisionItem(topic="T", decision="S1 a confirmat.", evidence=[_quote(by_id["s2"])])],
        action_items=[
            ActionItem(id="sub-floor-only", task="S1 va confirma.", task_en="S1 will confirm.", owner="Speaker 1",
                       owner_source="speaker", evidence=[_quote(by_id["s2"])]),
            ActionItem(id="mixed-floor", task="S1 va actualiza lista.", owner="Speaker 1", owner_source="speaker",
                       evidence=[_quote(by_id["s1"]), _quote(by_id["s2"])]),
            ActionItem(id="other-cluster", task="S1 va discuta cu S2.", owner="Speaker 1", owner_source="speaker",
                       evidence=[_quote(by_id["s1"]), _quote(by_id["s3"])]),
            ActionItem(id="printable", task="S1 va aproba.", owner="Speaker 1", owner_source="speaker", evidence=[_quote(by_id["s1"])]),
            ActionItem(id="label-short", task="S3 va verifica.", owner="Speaker 3", owner_source="speaker", evidence=[_quote(by_id["s4"])]),
        ],
        model_version="test-fixture",
    )
    before = stored.model_dump(mode="json")
    rendered = render_minutes(stored, transcript)
    assert stored.model_dump(mode="json") == before
    actions = {a.id: a for a in rendered.action_items}

    # prose still follows the cluster map (s1 is printable, so S1 renders the name everywhere in the narrative)
    assert rendered.decisions[0].decision == f"{NAME_A} a confirmat."
    assert actions["sub-floor-only"].task == f"{NAME_A} va confirma." and actions["sub-floor-only"].task_en == f"{NAME_A} will confirm."
    # ... but a quote of the 1.0 s turn and every owner that depends on it stay anonymous
    assert rendered.decisions[0].evidence[0].speaker == "Speaker 1", rendered.decisions[0].evidence[0]
    assert actions["sub-floor-only"].evidence[0].speaker == "Speaker 1"
    assert actions["sub-floor-only"].owner == "Speaker 1" and actions["sub-floor-only"].owner_source == "speaker", actions["sub-floor-only"]
    assert actions["mixed-floor"].owner == "Speaker 1", "one sub-floor evidence turn keeps the owner anonymous"
    assert [ev.speaker for ev in actions["mixed-floor"].evidence] == [NAME_A, "Speaker 1"], actions["mixed-floor"].evidence
    assert actions["other-cluster"].owner == "Speaker 1", "evidence outside the owner's cluster keeps the owner anonymous"
    assert [ev.speaker for ev in actions["other-cluster"].evidence] == [NAME_A, "Speaker 2"]
    assert actions["printable"].owner == NAME_A and actions["printable"].evidence[0].speaker == NAME_A
    # a confirmed cluster whose only turn is below the floor never prints, in prose or structure
    assert actions["label-short"].task == "Vorbitorul 3 va verifica." and actions["label-short"].owner == "Speaker 3"
    assert actions["label-short"].evidence[0].speaker == "Speaker 3" and NAME_R not in rendered.model_dump_json()
    # rendering the rendered copy again changes nothing
    assert render_minutes(rendered, transcript).model_dump(mode="json") == rendered.model_dump(mode="json")
    print("PASS test_render_minutes_honours_the_printable_floor_per_segment")


# ---------------------------------------------------------------- N2 grounding
def test_ground_speaker_labels_repairs_fabricated_tokens():
    cited = [
        _seg("g1", 0.0, 6.0, "Speaker 1", "Aprobăm protocolul de anticoagulare.", 5.5),   # most cited speech -> replacement label
        _seg("g2", 8.0, 12.0, "Speaker 2", "Eu pregătesc lista de medicamente.", 3.5),
    ]
    # nothing to repair
    text, speakers, repaired = ground_speaker_labels("S1 a propus; S2 a aprobat.", ["S1", "S2"], cited)
    assert (text, speakers, repaired) == ("S1 a propus; S2 a aprobat.", ["S1", "S2"], False)
    text, speakers, repaired = ground_speaker_labels("Se aprobă protocolul.", [], cited)
    assert (text, repaired) == ("Se aprobă protocolul.", False) and speakers == []
    # a label no cited segment spoke is replaced in the text by the allowed label with the most cited speech
    text, speakers, repaired = ground_speaker_labels("S7 a propus; S2 a aprobat.", ["S7", "S2"], cited)
    assert repaired is True
    assert text == "S1 a propus; S2 a aprobat.", text
    assert "S7" not in speakers and set(speakers) <= {"S1", "S2"} and "S2" in speakers
    # ... and dropped/replaced in the speakers list even when the text is clean
    text, speakers, repaired = ground_speaker_labels("S2 va pregăti lista.", ["S9"], cited)
    assert repaired is True and text == "S2 va pregăti lista."
    assert "S9" not in speakers and set(speakers) <= {"S1", "S2"}
    # two-digit and repeated fabrications, tokens inside words untouched
    text, speakers, repaired = ground_speaker_labels("S12 și S12 au propus; IS1 rămâne.", ["S12"], cited)
    assert repaired is True and text == "S1 și S1 au propus; IS1 rămâne." and "S12" not in speakers
    print("PASS test_ground_speaker_labels_repairs_fabricated_tokens")


# ---------------------------------------------------------------- N1/N2 through the engine with a FakeClient
LINES = [
    ("Speaker 1", "Bună dimineața. Deschidem ședința comitetului medical."),
    ("Speaker 2", "Propun să aprobăm protocolul de anticoagulare de la 1 octombrie."),
    ("Speaker 1", "De acord, aprobăm protocolul de anticoagulare de la 1 octombrie."),
    ("Speaker 3", "Eu voi pregăti raportul lunar de calitate până luni."),
    ("Speaker 2", "Există riscul ca stocul de meropenem să se epuizeze săptămâna viitoare."),
    ("Speaker 1", "Rămâne deschisă întrebarea privind bugetul secției."),
]


def extraction_meeting_and_transcript() -> tuple[Meeting, Transcript]:
    meeting = Meeting(id="inline-attr-extract", title="Ședință test atribuire", meeting_type=MeetingType.MEDICAL,
                      scheduled_at=datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc),
                      attendees=[Attendee(name=ROSTER, email="ceban@example.invalid")])
    segments = [
        TranscriptSegment(id=f"e{i}", start=float(i * 6), end=float(i * 6 + 5), speaker=label, raw_text=text, speech_seconds=4.5,
                          cluster_id="SPEAKER_%02d" % int(label.split()[1]))
        for i, (label, text) in enumerate(LINES)
    ]
    transcript = Transcript(meeting_id=meeting.id, segments=segments)
    transcript.compute_stats()
    return meeting, transcript


CLEAN_MAP: dict[str, Any] = {
    "decisions": [{"topic": "Protocol anticoagulare", "decision": "S2 a propus aprobarea protocolului de anticoagulare de la 1 octombrie; S1 a aprobat.",
                   "category": "protocol", "speakers": ["S2", "S1"], "evidence_idx": [1, 2]}],
    "action_items": [{"task": "Va pregăti raportul lunar de calitate.", "owner_mention": None, "owner_speaker": "S3",
                      "deadline_phrase": "până luni", "priority": "medium", "speakers": ["S3"], "evidence_idx": [3]}],
    "risks_and_questions": [{"item_type": "risk", "description": "S2 a semnalat riscul epuizării stocului de meropenem săptămâna viitoare.",
                             "severity": "high", "speakers": ["S2"], "evidence_idx": [4]}],
}
CLEAN_SYNTHESIS: dict[str, Any] = {
    "summary_ro": "S1 a deschis ședința. S2 a propus protocolul de anticoagulare, S1 a aprobat. S3 va pregăti raportul lunar până luni. S2 a semnalat riscul stocului de meropenem.",
    "summary_en": "S1 opened the meeting. S2 proposed the anticoagulation protocol and S1 approved it. S3 will prepare the monthly report by Monday. S2 flagged the meropenem stock risk.",
    "agenda_topics": ["Protocol anticoagulare", "Raport lunar de calitate", "Stoc meropenem"],
}


class FakeClient:
    """Stands in for OllamaClient: canned MAP answer (filtered to the chunk's line range) and canned synthesis answer."""

    def __init__(self, map_answer: dict[str, Any], synthesis_answer: dict[str, Any]):
        self.map_answer = map_answer
        self.synthesis_answer = synthesis_answer
        self.calls: list[dict[str, Any]] = []
        self.unload_calls = 0

    async def health(self) -> tuple[bool, str]:
        return True, "fake"

    async def assert_ready(self) -> str:
        return "ollama 0.34.4 / medpark-extractor / Q4_K_M / ctx4096 (FAKE)"

    async def complete_json(self, system: str, user: str, schema: dict, max_tokens: int, seed: int, keep_alive: str) -> tuple[dict, dict]:
        is_synthesis = "summary_ro" in schema.get("properties", {})
        self.calls.append({"kind": "synthesis" if is_synthesis else "map", "system": system, "user": user, "schema": schema})
        stats = {"prompt_tokens": max(1, len(user) // 4), "completion_tokens": 40, "seconds": 0.01}
        assert ROSTER.split()[-1] not in user and ROSTER.split()[-1] not in system, "the roster never reaches the model"
        if is_synthesis:
            return dict(self.synthesis_answer), stats
        m = _RANGE_PATTERN.search(user)
        assert m, "map prompt must state the line range"
        first, last = int(m.group(1)), int(m.group(2))
        answer: dict[str, Any] = {}
        for key in ("decisions", "action_items", "risks_and_questions"):
            answer[key] = [dict(item) for item in self.map_answer.get(key, []) if any(first <= i <= last for i in item["evidence_idx"])]
        return answer, stats

    async def unload(self) -> None:
        self.unload_calls += 1


def _cited_labels(item, transcript: Transcript) -> set[str]:
    by_id = {seg.id: seg for seg in transcript.segments}
    return {"S" + by_id[ev.segment_id].speaker.split()[1] for ev in item.evidence if ev.segment_id in by_id}


def _tokens(text: str | None) -> set[str]:
    return {"S" + m.group(1) for m in LABEL_RE.finditer(text or "")}


def test_prompts_and_schema_switch_to_labelled_prose():
    assert "Nu folosi etichetele vorbitorilor" not in EXTRACTION_MAP_SYSTEM_PROMPT, "the impersonal rule is reversed"
    for key in ("decisions", "action_items", "risks_and_questions"):
        item_schema = MAP_SCHEMA["properties"][key]["items"]
        assert "speakers" in item_schema["required"], key
        speakers = item_schema["properties"]["speakers"]
        assert speakers["type"] == "array" and speakers["items"]["type"] == "string" and speakers.get("maxItems") == 3, (key, speakers)
    assert "S1" in EXTRACTION_MAP_SYSTEM_PROMPT or "S<" in EXTRACTION_MAP_SYSTEM_PROMPT, "the map prompt names the label form"
    assert "S1" in SYNTHESIS_SYSTEM_PROMPT or "etichet" in SYNTHESIS_SYSTEM_PROMPT.lower(), "the synthesis prompt asks for labelled narrative"
    print("PASS test_prompts_and_schema_switch_to_labelled_prose")


def test_extraction_items_carry_grounded_speakers_and_summary_labels() -> MinutesOfMeeting:
    meeting, transcript = extraction_meeting_and_transcript()
    fake = FakeClient(CLEAN_MAP, CLEAN_SYNTHESIS)
    minutes = asyncio.run(LocalLLMExtractor(client=fake).extract_minutes(meeting, transcript))
    assert fake.unload_calls == 1 and [c["kind"] for c in fake.calls] == ["map", "synthesis"]
    assert minutes.speaker_label_style == "labels"
    assert minutes.is_degraded is False and minutes.failed_chunks == []

    # the synthesis call sees each item's speakers: S3 only exists as the action's speaker list, not in its text
    synthesis_user = fake.calls[1]["user"]
    assert "S3" in synthesis_user, synthesis_user
    assert "Bună dimineața" not in synthesis_user, "synthesis never sees the transcript"

    items = [*minutes.decisions, *minutes.action_items, *minutes.risks_and_questions]
    assert len(minutes.decisions) == 1 and len(minutes.action_items) == 1
    for item in items:
        if "NOTĂ AUDIT" in getattr(item, "description", ""):
            continue
        cited = _cited_labels(item, transcript)
        text = getattr(item, "decision", None) or getattr(item, "task", None) or getattr(item, "description", "")
        assert _tokens(text) <= cited, (text, cited)
        if hasattr(item, "speakers"):
            assert set(item.speakers) <= cited, (item.speakers, cited)
    assert minutes.action_items[0].owner == "Speaker 3" and minutes.action_items[0].owner_source == "speaker"
    assert minutes.action_items[0].deadline_date == "2026-09-28"
    assert minutes.needs_name_review is False
    assert not any("NOTĂ AUDIT" in r.description for r in minutes.risks_and_questions)

    # the narrative attributes to at least two distinct labels, all of them real clusters of this transcript
    transcript_labels = {"S" + seg.speaker.split()[1] for seg in transcript.segments}
    assert len(_tokens(minutes.summary_ro)) >= 2 and _tokens(minutes.summary_ro) <= transcript_labels
    assert len(_tokens(minutes.summary_en)) >= 2 and _tokens(minutes.summary_en) <= transcript_labels
    # the stored text carries no name: neither the roster nor a person is ever written by the engine
    dump = minutes.model_dump_json()
    assert "Ceban" not in dump
    # the RU/EN item translations produced during extraction (dead LLM -> deterministic fallback) keep the tokens
    assert minutes.decisions[0].decision_ru and _tokens(minutes.decisions[0].decision_ru) == _tokens(minutes.decisions[0].decision)
    assert minutes.decisions[0].decision_en and _tokens(minutes.decisions[0].decision_en) == _tokens(minutes.decisions[0].decision)
    print("PASS test_extraction_items_carry_grounded_speakers_and_summary_labels")
    return minutes


def test_extraction_repairs_fabricated_label_and_flags_it():
    meeting, transcript = extraction_meeting_and_transcript()
    fab_map = {
        "decisions": [{"topic": "Protocol anticoagulare", "decision": "S9 a propus aprobarea protocolului; S1 a aprobat.",
                       "category": "protocol", "speakers": ["S9", "S1"], "evidence_idx": [1, 2]}],
        "action_items": [dict(CLEAN_MAP["action_items"][0])],
        "risks_and_questions": [dict(CLEAN_MAP["risks_and_questions"][0])],
    }
    fab_synthesis = {
        "summary_ro": "S1 a deschis ședința. S9 a propus protocolul, S1 a aprobat. S3 va pregăti raportul. S2 a semnalat riscul.",
        "summary_en": "S1 opened the meeting. S9 proposed the protocol and S1 approved. S3 will prepare the report. S2 flagged the risk.",
        "agenda_topics": ["Protocol anticoagulare"],
    }
    fake = FakeClient(fab_map, fab_synthesis)
    minutes = asyncio.run(LocalLLMExtractor(client=fake).extract_minutes(meeting, transcript))

    dec = minutes.decisions[0]
    cited = _cited_labels(dec, transcript)            # {"S1", "S2"}: lines 1 (S2) and 2 (S1)
    assert cited == {"S1", "S2"}
    assert "S9" not in dec.decision and _tokens(dec.decision) <= cited, dec.decision
    assert dec.decision.startswith("S1 a propus") or dec.decision.startswith("S2 a propus"), dec.decision
    if hasattr(dec, "speakers"):
        assert "S9" not in dec.speakers and set(dec.speakers) <= cited
    # exactly ONE medium-severity audit note about the repair, and the document is flagged for review
    notes = [r for r in minutes.risks_and_questions if _AUDIT_REPAIR_TEXT in r.description]
    assert len(notes) == 1, [r.description for r in minutes.risks_and_questions]
    assert notes[0].severity == "medium" and notes[0].description.startswith("NOTĂ AUDIT")
    assert "1 element" in notes[0].description, notes[0].description
    assert minutes.needs_name_review is True
    # the summary is grounded against the transcript's label set the same way
    transcript_labels = {"S1", "S2", "S3"}
    for summary in (minutes.summary_ro, minutes.summary_en):
        assert "S9" not in (summary or ""), summary
        assert _tokens(summary) <= transcript_labels, summary
    # the clean items are untouched by the repair of another item
    assert minutes.action_items[0].task == CLEAN_MAP["action_items"][0]["task"]
    assert minutes.risks_and_questions[0].description == CLEAN_MAP["risks_and_questions"][0]["description"]
    print("PASS test_extraction_repairs_fabricated_label_and_flags_it")


def test_rendered_extraction_end_to_end():
    """A labelled extraction rendered through the read layer: a confirmed cluster prints its name, the rest stay anonymous."""
    meeting, transcript = extraction_meeting_and_transcript()
    minutes = asyncio.run(LocalLLMExtractor(client=FakeClient(CLEAN_MAP, CLEAN_SYNTHESIS)).extract_minutes(meeting, transcript))
    for seg in transcript.segments:
        if seg.speaker == "Speaker 2":
            for key, value in _named(NAME_A).items():
                setattr(seg, key, value)
    rendered = render_minutes(minutes, transcript)
    assert rendered.summary_ro.startswith(f"Vorbitorul 1 a deschis ședința. {NAME_A} a propus")
    assert f"{NAME_A} proposed" in (rendered.summary_en or "") and "Speaker 1 opened" in (rendered.summary_en or "")
    assert rendered.decisions[0].decision.startswith(f"{NAME_A} a propus") and "Vorbitorul 1 a aprobat" in rendered.decisions[0].decision
    assert rendered.action_items[0].owner in ("Speaker 3", "Vorbitorul 3")
    assert rendered.risks_and_questions[0].evidence[0].speaker == NAME_A
    stored = repository.get_minutes(meeting.id)
    assert stored is not None and "S2 a propus" in stored.decisions[0].decision and NAME_A not in stored.model_dump_json(), "storage keeps labels"
    print("PASS test_rendered_extraction_end_to_end")


if __name__ == "__main__":
    import traceback

    assert Path(settings.DATA_DIR).is_relative_to(_ROOT) and repository.storage_dir.is_relative_to(_ROOT), "storage isolation"
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
