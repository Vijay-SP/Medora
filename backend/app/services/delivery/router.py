"""
Medpark Meeting Intelligence System - Delivery Router
Resolves meeting-type distribution rules, attendee inclusion, and official department lists.
"""

from app.core.exceptions import DeliveryError
from app.core.logging import logger
from app.models.meeting import Meeting
from app.models.extraction import MinutesOfMeeting
from app.models.delivery import DEFAULT_ROUTING_POLICIES, RoutingPolicy, default_routing_policies_enabled


class DeliveryRouter:
    """Computes final authorized distribution list based on meeting category and attendees."""

    def _get_policy(self, meeting: Meeting) -> RoutingPolicy:
        return DEFAULT_ROUTING_POLICIES.get(
            meeting.meeting_type.value,
            DEFAULT_ROUTING_POLICIES["medical"]
        )

    def _normalize(self, emails: list[str]) -> set[str]:
        return {email.strip().lower() for email in emails if email and "@" in email}

    def resolve_recipients(self, meeting: Meeting) -> list[str]:
        policy = self._get_policy(meeting)

        # 1. A custom distribution list is an exclusive override of the department policy
        overrides = self._normalize(meeting.distribution_list)
        if overrides:
            final_list = sorted(overrides)
            logger.info(f"Resolved {len(final_list)} recipients from the custom distribution list of meeting '{meeting.title}' (policy overridden)")
            return final_list

        recipients = set()

        # 2. Add Department Default & CC Recipients - only when the hardcoded hospital lists
        #    were explicitly enabled, so an unconfigured install never mails real addresses
        if default_routing_policies_enabled():
            recipients |= self._normalize(policy.default_recipients + policy.cc_recipients)
        elif policy.default_recipients or policy.cc_recipients:
            logger.warning(f"Routing policy '{policy.department_name}' is not enabled (ENABLE_DEFAULT_ROUTING_POLICIES=false) -> only attendees of '{meeting.title}' will be addressed")

        # 3. Add Meeting Attendees
        recipients |= self._normalize([att.email for att in meeting.attendees if att.email])

        final_list = sorted(list(recipients))
        logger.info(f"Resolved {len(final_list)} recipients for {meeting.meeting_type.value.upper()} meeting '{meeting.title}'")
        return final_list

    def split_to_cc(self, meeting: Meeting, recipients: list[str]) -> tuple[list[str], list[str]]:
        """
        Splits an already resolved list into primary (To) and carbon-copy (Cc) addresses so that
        policy CC entries such as the medical archive stay a CC instead of being exposed in To.
        """
        # A custom distribution list has no policy semantics: everybody is a primary recipient
        if self._normalize(meeting.distribution_list) or not default_routing_policies_enabled():
            return list(recipients), []

        cc_pool = self._normalize(self._get_policy(meeting).cc_recipients)
        to_list = [email for email in recipients if email not in cc_pool]
        cc_list = [email for email in recipients if email in cc_pool]

        # Never emit an empty To header: promote the CC addresses if nothing else remains
        if not to_list:
            return cc_list, []
        return to_list, cc_list

    def assert_dispatchable(self, minutes: MinutesOfMeeting) -> None:
        """
        Dispatch guard shared by the auto-pilot pipeline and the reviewer approval endpoint.
        A document produced by the heuristic fallback is a draft nobody validated: it never leaves
        the building, whichever channel was about to send it.
        Stale minutes resulting from post-extraction transcript edits are blocked from dispatch.
        """
        if minutes.is_degraded:
            logger.warning(f"Dispatch refused for meeting {minutes.meeting_id}: minutes Rev.{minutes.revision} are a degraded draft ({minutes.model_version})")
            raise DeliveryError("Documentul este un DRAFT degradat (LLM local indisponibil) și nu poate fi expediat")
        if minutes.needs_transcript_review:
            logger.warning(f"Dispatch refused for meeting {minutes.meeting_id}: minutes Rev.{minutes.revision} are stale after transcript edit")
            raise DeliveryError("Transcriptul a fost modificat ulterior generării procesului-verbal. Este necesară re-extragerea procesului-verbal înainte de expediere (needs_transcript_review).")

    def get_subject_line(self, meeting: Meeting, revision: int = 1) -> str:
        policy = self._get_policy(meeting)
        date_str = meeting.scheduled_at.strftime("%d.%m.%Y")
        return f"{policy.subject_prefix} {meeting.title} - {date_str} (Rev.{revision})"


delivery_router = DeliveryRouter()
