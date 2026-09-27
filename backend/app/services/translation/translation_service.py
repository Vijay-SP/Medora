"""
Medpark Meeting Intelligence System - Translation Service
Translates structured Minutes of Meeting (agenda, decisions, action items, risks)
into Russian and English using the local air-gapped LLM with medical vocabulary preservation.
Translations are persisted permanently on the MinutesOfMeeting entity to avoid duplicate LLM load.
"""

from typing import Any, Literal
import json
import re
from app.core.config import settings
from app.core.logging import logger
from app.core.exceptions import LLMUnavailable, ExtractionError
from app.models.extraction import MinutesOfMeeting
from app.services.extraction.attribution_render import labels_in
from app.services.extraction.llm_client import OllamaClient
from app.storage.repository import repository

TargetLanguage = Literal["ro", "ru", "en"]

TRANSLATION_SYSTEM_PROMPT = """Ești asistentul de traducere medicală al Spitalului Internațional Medpark.
Traduci elementele oficiale de proces-verbal (subiecte agendă, decizii, sarcini, riscuri) din limba română în limba {target_name} ({target_code}).

REGULI MEDICALE ȘI DE STRUCTURĂ STRICTE:
1. Păstrează denumirile de medicamente, dozele medicale (mg, ml, UI, g/zi etc.), denumirile internaționale și numele proprii EXACT neschimbate.
2. Etichetele vorbitorilor (S1, S2, …) rămân EXACT neschimbate în traducere: nu le traduce, nu le omite, nu le renumerota și nu le înlocui cu nume.
3. Formulează concis, fidel și profesional, adecvat unui raport oficial de consiliu medical.
4. Păstrează identificatorii "id" identici pentru fiecare element din liste.
5. Răspunde EXCLUSIV cu un obiect JSON valid care respectă schema furnizată; fără text înainte sau după JSON."""

TRANSLATION_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": "Translated executive summary",
        },
        "agenda_topics": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Translated agenda topics",
        },
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "topic": {"type": "string"},
                    "decision": {"type": "string"},
                },
                "required": ["id", "topic", "decision"],
            },
        },
        "action_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "task": {"type": "string"},
                    "deadline_phrase": {"type": ["string", "null"]},
                },
                "required": ["id", "task"],
            },
        },
        "risks_and_questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["id", "description"],
            },
        },
    },
    "required": ["agenda_topics", "decisions", "action_items", "risks_and_questions"],
}


_SPEAKER_TOKEN_RE = re.compile(r"(?<![\w\-/.–])(?:Speaker\s+|S)(\d{1,2})(?![\w\-/–]|[.,]\d)", re.IGNORECASE)


def _labels_in(text: str | None) -> set[str]:
    # Speaker labels only: clinical S<n> notation ("L5-S1", "тоны S1 и S2") is content, not a label
    if not text:
        return set()
    found = set(labels_in(text))
    for m in _SPEAKER_TOKEN_RE.finditer(text):
        found.add(f"S{int(m.group(1))}")
    return found


def _keep_labels(source: str, translated: str, field: str, target_lang: str) -> str:
    """
    Token-preservation guard: a translation that drops, adds or renumbers a speaker label would attribute
    the wrong person once rendered, so the Romanian text is kept for that field and the loss is logged.
    """
    if _labels_in(source) == _labels_in(translated):
        return translated
    logger.warning(
        f"{target_lang.upper()} translation of {field} altered the speaker labels "
        f"({sorted(_labels_in(source))} -> {sorted(_labels_in(translated))}); keeping the Romanian text"
    )
    return source


class TranslationService:
    """
    Air-gapped translation service for Minutes of Meeting dynamic responses.

    Always translates the STORED label text ("S3 a propus ..."), never rendered names: the render layer
    substitutes names per locale afterwards, so the *_ru/*_en fields stay name-free like the Romanian ones.
    """

    def __init__(self):
        self._client: OllamaClient | None = None

    @property
    def client(self) -> OllamaClient:
        if self._client is None:
            self._client = OllamaClient(
                base_url=settings.LLM_API_BASE_URL,
                model=settings.LLM_MODEL_NAME,
                timeout_s=settings.LLM_REQUEST_TIMEOUT_S,
                health_timeout_s=settings.LLM_HEALTH_TIMEOUT_S,
            )
        return self._client

    def is_translated(self, minutes: MinutesOfMeeting, target_lang: TargetLanguage) -> bool:
        """Checks if dynamic content is already translated and cached for the target language."""
        if target_lang == "ro":
            return True  # Romanian is the primary extraction language
        if target_lang == "ru":
            has_topics = minutes.agenda_topics_ru is not None or not minutes.agenda_topics
            has_decisions = not minutes.decisions or any(d.decision_ru for d in minutes.decisions)
            has_actions = not minutes.action_items or any(a.task_ru for a in minutes.action_items)
            return bool(has_topics and has_decisions and has_actions)
        if target_lang == "en":
            has_topics = minutes.agenda_topics_en is not None or not minutes.agenda_topics
            has_decisions = not minutes.decisions or any(d.decision_en for d in minutes.decisions)
            has_actions = not minutes.action_items or any(a.task_en for a in minutes.action_items)
            return bool(has_topics and has_decisions and has_actions)
        return False

    async def translate_mom(
        self,
        minutes: MinutesOfMeeting,
        target_lang: TargetLanguage,
        force_refresh: bool = False,
    ) -> MinutesOfMeeting:
        """
        Translates dynamic MoM items into the target language (ru or en).
        If already translated and cached, returns immediately with 0 extra LLM calls.
        Saves updated minutes to repository upon completion.
        """
        if target_lang == "ro":
            return minutes

        if not force_refresh and self.is_translated(minutes, target_lang):
            logger.info(f"Using cached {target_lang.upper()} translation for meeting {minutes.meeting_id}")
            return minutes

        lang_meta = {
            "ru": {"name": "RUSĂ", "code": "RU"},
            "en": {"name": "ENGLEZĂ", "code": "EN"},
        }
        meta = lang_meta.get(target_lang, {"name": target_lang.upper(), "code": target_lang.upper()})

        # Check if there is anything to translate
        has_items = bool(
            minutes.summary_ro
            or minutes.agenda_topics
            or minutes.decisions
            or minutes.action_items
            or minutes.risks_and_questions
        )
        if not has_items:
            if target_lang == "ru":
                minutes.agenda_topics_ru = []
            elif target_lang == "en":
                minutes.agenda_topics_en = []
            repository.save_minutes(minutes)
            return minutes

        # Prepare extraction payload
        payload = {}
        if minutes.summary_ro:
            payload["summary"] = minutes.summary_ro
        payload["agenda_topics"] = minutes.agenda_topics
        payload["decisions"] = [
            {"id": d.id, "topic": d.topic, "decision": d.decision}
            for d in minutes.decisions
        ]
        payload["action_items"] = [
            {"id": a.id, "task": a.task, "deadline_phrase": a.deadline_phrase}
            for a in minutes.action_items
        ]
        payload["risks_and_questions"] = [
            {"id": r.id, "description": r.description}
            for r in minutes.risks_and_questions
        ]

        system_prompt = TRANSLATION_SYSTEM_PROMPT.format(
            target_name=meta["name"],
            target_code=meta["code"],
        )
        user_prompt = (
            f"Tradu următoarele elemente oficiale în limba {meta['name']} ({meta['code']}). "
            f"Răspunde DOAR cu JSON respectând schema:\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
        )

        try:
            raw_response, stats = await self.client.complete_json(
                system=system_prompt,
                user=user_prompt,
                schema=TRANSLATION_SCHEMA,
                max_tokens=min(settings.LLM_TRANSLATION_MAX_TOKENS, 3072),
                seed=settings.LLM_SEED,
                keep_alive=settings.LLM_KEEP_ALIVE,
            )
            self._apply_translation_result(minutes, raw_response, target_lang)
            logger.info(
                f"Successfully translated MoM to {target_lang.upper()} for meeting {minutes.meeting_id} "
                f"({stats.get('completion_tokens', 0)} tokens in {stats.get('seconds', 0)}s)"
            )
        except (LLMUnavailable, ExtractionError, Exception) as err:
            logger.warning(
                f"LLM translation failed for meeting {minutes.meeting_id} ({err}); "
                f"using deterministic fallback for {target_lang.upper()}."
            )
            self._apply_fallback_translation(minutes, target_lang)

        # Cache/persist permanently so we never translate repeatedly
        repository.save_minutes(minutes)
        return minutes

    def _apply_translation_result(
        self,
        minutes: MinutesOfMeeting,
        result: dict[str, Any],
        target_lang: TargetLanguage,
    ) -> None:
        """Maps LLM translation JSON back to MinutesOfMeeting entity."""
        # 0. Executive Summary
        trans_sum = result.get("summary")
        if trans_sum and isinstance(trans_sum, str) and trans_sum.strip():
            safe_sum = _keep_labels(minutes.summary_ro or "", trans_sum.strip(), "summary", target_lang)
            if target_lang == "ru":
                minutes.summary_ru = safe_sum
            elif target_lang == "en":
                minutes.summary_en = safe_sum

        # 1. Agenda Topics
        translated_topics = [t.strip() for t in result.get("agenda_topics", []) if isinstance(t, str) and t.strip()]
        if len(translated_topics) == len(minutes.agenda_topics):
            translated_topics = [
                _keep_labels(src, out, f"agenda_topics[{i}]", target_lang)
                for i, (src, out) in enumerate(zip(minutes.agenda_topics, translated_topics))
            ]
        if target_lang == "ru":
            minutes.agenda_topics_ru = translated_topics or minutes.agenda_topics
        elif target_lang == "en":
            minutes.agenda_topics_en = translated_topics or minutes.agenda_topics

        # 2. Decisions
        dec_map = {d.get("id"): d for d in result.get("decisions", []) if isinstance(d, dict) and d.get("id")}
        for idx, d in enumerate(minutes.decisions):
            match = dec_map.get(d.id)
            if not match and idx < len(result.get("decisions", [])):
                match = result["decisions"][idx]
            if match:
                topic_trans = _keep_labels(d.topic, match.get("topic", "").strip() or d.topic, f"decision {d.id} topic", target_lang)
                dec_trans = _keep_labels(d.decision, match.get("decision", "").strip() or d.decision, f"decision {d.id}", target_lang)
                if target_lang == "ru":
                    d.topic_ru = topic_trans
                    d.decision_ru = dec_trans
                elif target_lang == "en":
                    d.topic_en = topic_trans
                    d.decision_en = dec_trans

        # 3. Action Items
        act_map = {a.get("id"): a for a in result.get("action_items", []) if isinstance(a, dict) and a.get("id")}
        for idx, a in enumerate(minutes.action_items):
            match = act_map.get(a.id)
            if not match and idx < len(result.get("action_items", [])):
                match = result["action_items"][idx]
            if match:
                task_trans = _keep_labels(a.task, match.get("task", "").strip() or a.task, f"action {a.id}", target_lang)
                deadline_trans = match.get("deadline_phrase")
                if deadline_trans and a.deadline_phrase:
                    deadline_trans = _keep_labels(a.deadline_phrase, str(deadline_trans).strip(), f"action {a.id} deadline", target_lang)
                if target_lang == "ru":
                    a.task_ru = task_trans
                    if deadline_trans:
                        a.deadline_phrase_ru = str(deadline_trans).strip()
                elif target_lang == "en":
                    a.task_en = task_trans
                    if deadline_trans:
                        a.deadline_phrase_en = str(deadline_trans).strip()

        # 4. Risks & Questions
        risk_map = {r.get("id"): r for r in result.get("risks_and_questions", []) if isinstance(r, dict) and r.get("id")}
        for idx, r in enumerate(minutes.risks_and_questions):
            match = risk_map.get(r.id)
            if not match and idx < len(result.get("risks_and_questions", [])):
                match = result["risks_and_questions"][idx]
            if match:
                desc_trans = _keep_labels(r.description, match.get("description", "").strip() or r.description, f"risk {r.id}", target_lang)
                if target_lang == "ru":
                    r.description_ru = desc_trans
                elif target_lang == "en":
                    r.description_en = desc_trans

    def _apply_fallback_translation(
        self,
        minutes: MinutesOfMeeting,
        target_lang: TargetLanguage,
    ) -> None:
        """Deterministic fallback when LLM is unavailable: preserves text with clean metadata."""
        prefix = "[RU] " if target_lang == "ru" else "[EN] "
        if target_lang == "ru":
            if not minutes.summary_ru and minutes.summary_ro:
                minutes.summary_ru = f"{prefix}{minutes.summary_ro}"
            minutes.agenda_topics_ru = [f"{prefix}{t}" for t in minutes.agenda_topics]
            for d in minutes.decisions:
                d.topic_ru = d.topic
                d.decision_ru = f"{prefix}{d.decision}"
            for a in minutes.action_items:
                a.task_ru = f"{prefix}{a.task}"
                a.deadline_phrase_ru = a.deadline_phrase
            for r in minutes.risks_and_questions:
                r.description_ru = f"{prefix}{r.description}"
        elif target_lang == "en":
            if not minutes.summary_en and minutes.summary_ro:
                minutes.summary_en = f"{prefix}{minutes.summary_ro}"
            minutes.agenda_topics_en = [f"{prefix}{t}" for t in minutes.agenda_topics]
            for d in minutes.decisions:
                d.topic_en = d.topic
                d.decision_en = f"{prefix}{d.decision}"
            for a in minutes.action_items:
                a.task_en = f"{prefix}{a.task}"
                a.deadline_phrase_en = a.deadline_phrase
            for r in minutes.risks_and_questions:
                r.description_en = f"{prefix}{r.description}"

    @staticmethod
    def get_localized_mom(
        minutes: MinutesOfMeeting,
        language: TargetLanguage = "ro",
    ) -> dict[str, Any]:
        """
        Reusable helper for the email and document systems.
        Returns a clean dictionary containing the localized executive summary,
        agenda topics, decisions, action items, and risks without requiring LLM calls.
        """
        # Summary
        if language == "ru" and minutes.summary_ru:
            summary = minutes.summary_ru
        elif language == "en" and minutes.summary_en:
            summary = minutes.summary_en
        else:
            summary = minutes.summary_ro

        # Topics
        if language == "ru" and minutes.agenda_topics_ru:
            topics = minutes.agenda_topics_ru
        elif language == "en" and minutes.agenda_topics_en:
            topics = minutes.agenda_topics_en
        else:
            topics = minutes.agenda_topics

        # Decisions
        decisions = []
        for d in minutes.decisions:
            topic = (d.topic_ru if language == "ru" and d.topic_ru else
                     d.topic_en if language == "en" and d.topic_en else d.topic)
            decision = (d.decision_ru if language == "ru" and d.decision_ru else
                        d.decision_en if language == "en" and d.decision_en else d.decision)
            decisions.append({
                "id": d.id,
                "topic": topic,
                "decision": decision,
                "category": d.category,
                "is_reviewed": d.is_reviewed,
            })

        # Action Items
        actions = []
        for a in minutes.action_items:
            task = (a.task_ru if language == "ru" and a.task_ru else
                    a.task_en if language == "en" and a.task_en else a.task)
            deadline = (a.deadline_phrase_ru if language == "ru" and a.deadline_phrase_ru else
                        a.deadline_phrase_en if language == "en" and a.deadline_phrase_en else
                        a.deadline_date or a.deadline_phrase or "Nespecificat")
            actions.append({
                "id": a.id,
                "task": task,
                "owner": a.owner,
                "deadline": deadline,
                "priority": a.priority,
                "status": a.status,
                "is_reviewed": a.is_reviewed,
            })

        # Risks
        risks = []
        for r in minutes.risks_and_questions:
            desc = (r.description_ru if language == "ru" and r.description_ru else
                    r.description_en if language == "en" and r.description_en else r.description)
            risks.append({
                "id": r.id,
                "description": desc,
                "item_type": r.item_type,
                "severity": r.severity,
            })

        return {
            "meeting_id": minutes.meeting_id,
            "title": minutes.title,
            "language": language,
            "summary": summary,
            "agenda_topics": topics,
            "decisions": decisions,
            "action_items": actions,
            "risks_and_questions": risks,
            "revision": minutes.revision,
        }


translation_service = TranslationService()
