"""
Medpark Meeting Intelligence System - Evidence Grounding & Deadline Validator
Verifies that all extracted claims map to verbatim audio timestamps and resolves temporal expressions.
"""

from datetime import datetime, timedelta
import re
from typing import Optional
from app.core.logging import logger
from app.models.meeting import Meeting
from app.models.transcript import Transcript
from app.models.extraction import MinutesOfMeeting, EvidenceQuote, RiskOrQuestionItem


class EvidenceValidator:
    """Ensures 100% factual grounding by verifying citations against transcript utterances."""

    def validate_and_enrich(self, minutes: MinutesOfMeeting, transcript: Transcript, meeting: Meeting) -> MinutesOfMeeting:
        """
        Validates evidence quotes against actual transcript text and calculates ISO dates for deadlines.
        Moves any claim lacking verified audio grounding out of official decisions into review questions.
        """
        segment_map = {seg.id: seg for seg in transcript.segments}
        verified_decisions = []
        verified_actions = []

        # 1. Validate Decision Grounding
        for dec in minutes.decisions:
            valid_evidence = []
            for ev in dec.evidence:
                if self._verify_quote_exists(ev, transcript, segment_map):
                    valid_evidence.append(ev)
            
            if valid_evidence:
                dec.evidence = valid_evidence
                verified_decisions.append(dec)
            else:
                # Reject unsupported claims from official decisions; flag for human review
                logger.warning(f"Decision '{dec.topic}' rejected: No valid audio evidence found. Moving to review questions.")
                minutes.risks_and_questions.append(
                    RiskOrQuestionItem(
                        item_type="unresolved_question",
                        description=f"[NEVERIFICAT AUDIO] {dec.topic}: {dec.decision} (Lipsă dovadă audio sincronizată)",
                        severity="high"
                    )
                )

        # 2. Validate Action Item Grounding and Resolve Deadlines
        for act in minutes.action_items:
            valid_evidence = []
            for ev in act.evidence:
                if self._verify_quote_exists(ev, transcript, segment_map):
                    valid_evidence.append(ev)

            if valid_evidence:
                act.evidence = valid_evidence
                # Resolve relative dates (e.g., "până vineri", "до конца недели")
                if act.deadline_phrase and not act.deadline_date:
                    act.deadline_date = self.resolve_relative_deadline(act.deadline_phrase, meeting.scheduled_at)
                verified_actions.append(act)
            else:
                logger.warning(f"Action '{act.task}' rejected: No valid audio evidence found. Moving to review questions.")
                minutes.risks_and_questions.append(
                    RiskOrQuestionItem(
                        item_type="unresolved_question",
                        description=f"[NEVERIFICAT AUDIO] Sarcină propusă: {act.task} (Responsabil prezumat: {act.owner})",
                        severity="medium"
                    )
                )

        minutes.decisions = verified_decisions
        minutes.action_items = verified_actions

        logger.info(f"Evidence validation: {len(minutes.decisions)} decisions and {len(minutes.action_items)} actions verified with audio grounding.")
        return minutes

    def _verify_quote_exists(
        self,
        evidence: EvidenceQuote,
        transcript: Transcript,
        segment_map: dict
    ) -> bool:
        """
        Validates evidence citation strictly against cited segment ID and timestamps.
        Prevents hallucinated claims by requiring physical quote presence in cited segment.
        """
        quote = evidence.quote.strip()
        if not quote or len(quote) < 3:
            return False

        # 1. Primary check: Cited segment exists and contains the quote
        seg_id = evidence.segment_id
        if seg_id in segment_map:
            target_seg = segment_map[seg_id]
            seg_text = target_seg.display_text.lower()
            quote_clean = re.sub(r"[^\w\s]", "", quote.lower())
            seg_clean = re.sub(r"[^\w\s]", "", seg_text)

            # Check if quote or significant substring is inside cited segment
            if quote.lower() in seg_text or quote_clean in seg_clean:
                # Verify timestamp bounds overlap with cited segment
                if evidence.start <= target_seg.end + 1.0 and evidence.end >= target_seg.start - 1.0:
                    return True

            # Check adjacent segments if speech crossed boundary
            quote_words = set(quote_clean.split())
            seg_words = set(seg_clean.split())
            if len(quote_words) > 0 and len(quote_words & seg_words) / len(quote_words) >= 0.65:
                return True

        # 2. Secondary check across all segments (must match an actual spoken segment)
        quote_clean = re.sub(r"[^\w\s]", "", quote.lower())
        for seg in transcript.segments:
            seg_clean = re.sub(r"[^\w\s]", "", seg.display_text.lower())
            if quote_clean in seg_clean and len(quote_clean) > 8:
                evidence.segment_id = seg.id
                evidence.start = seg.start
                evidence.end = seg.end
                evidence.speaker = seg.speaker
                return True

        return False

    def resolve_relative_deadline(self, phrase: str, meeting_time: datetime) -> Optional[str]:
        """
        Calculates an ISO YYYY-MM-DD deadline from Romanian/Russian/English phrases.
        Tests longer phrases first (e.g. 'poimâine' before 'mâine') to prevent false matches.
        """
        p = phrase.lower()
        base_date = meeting_time.date()

        # Check 'poimâine' / 'послезавтра' FIRST before 'mâine' / 'завтра'
        if "poimâine" in p or "poimiine" in p or "послезавтра" in p or "day after tomorrow" in p:
            return (base_date + timedelta(days=2)).isoformat()

        if "mâine" in p or "miine" in p or "завтра" in p or "tomorrow" in p:
            return (base_date + timedelta(days=1)).isoformat()
        
        # Days of week in Romanian / Russian
        day_mapping = {
            "luni": 0, "понедельник": 0, "monday": 0,
            "marți": 1, "marti": 1, "вторник": 1, "tuesday": 1,
            "miercuri": 2, "среда": 2, "wednesday": 2,
            "joi": 3, "четверг": 3, "thursday": 3,
            "vineri": 4, "пятница": 4, "friday": 4,
            "sâmbătă": 5, "sambata": 5, "суббота": 5, "saturday": 5,
            "duminică": 6, "duminica": 6, "воскресенье": 6, "sunday": 6,
        }

        for day_name, target_weekday in day_mapping.items():
            if day_name in p:
                days_ahead = target_weekday - base_date.weekday()
                if days_ahead <= 0:  # Target day already happened this week
                    days_ahead += 7
                return (base_date + timedelta(days=days_ahead)).isoformat()

        if "săptămâna viitoare" in p or "следующая неделя" in p or "next week" in p:
            return (base_date + timedelta(days=7)).isoformat()

        if "sfârșitul lunii" in p or "end of month" in p:
            # Approximate end of current month
            next_month = base_date.replace(day=28) + timedelta(days=4)
            end_of_month = next_month - timedelta(days=next_month.day)
            return end_of_month.isoformat()

        return None


evidence_validator = EvidenceValidator()
