"""
Medpark Meeting Intelligence System - Delivery Router
Resolves meeting-type distribution rules, attendee inclusion, and official department lists.
"""

from app.core.logging import logger
from app.models.meeting import Meeting
from app.models.delivery import DEFAULT_ROUTING_POLICIES, RoutingPolicy


class DeliveryRouter:
    """Computes final authorized distribution list based on meeting category and attendees."""

    def resolve_recipients(self, meeting: Meeting) -> list[str]:
        policy = DEFAULT_ROUTING_POLICIES.get(
            meeting.meeting_type.value,
            DEFAULT_ROUTING_POLICIES["medical"]
        )

        recipients = set()
        
        # 1. Add Department Default Recipients
        for email in policy.default_recipients:
            if email and "@" in email:
                recipients.add(email.strip().lower())

        # 2. Add Meeting Attendees
        for att in meeting.attendees:
            if att.email and "@" in att.email:
                recipients.add(att.email.strip().lower())

        # 3. Add Custom Distribution List Overrides
        for email in meeting.distribution_list:
            if email and "@" in email:
                recipients.add(email.strip().lower())

        final_list = sorted(list(recipients))
        logger.info(f"Resolved {len(final_list)} recipients for {meeting.meeting_type.value.upper()} meeting '{meeting.title}'")
        return final_list

    def get_subject_line(self, meeting: Meeting, revision: int = 1) -> str:
        policy = DEFAULT_ROUTING_POLICIES.get(
            meeting.meeting_type.value,
            DEFAULT_ROUTING_POLICIES["medical"]
        )
        date_str = meeting.scheduled_at.strftime("%d.%m.%Y")
        return f"{policy.subject_prefix} {meeting.title} - {date_str} (Rev.{revision})"


delivery_router = DeliveryRouter()
