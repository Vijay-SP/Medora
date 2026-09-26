"""
Medpark Meeting Intelligence System - n8n Automation Engine Client
Dispatches approved meeting payloads to self-hosted n8n workflows for complex routing.
"""

from datetime import datetime, timezone
import httpx
from app.core.config import settings
from app.core.exceptions import DeliveryError
from app.core.logging import logger
from app.models.meeting import Meeting
from app.models.extraction import MinutesOfMeeting
from app.models.delivery import DeliveryRecord, DeliveryStatus, DeliveryChannel
from app.services.delivery.router import delivery_router
from app.services.delivery.smtp_service import assert_no_person_names, build_body, get_email_languages
from app.storage.repository import repository


class N8nAutomationService:
    """Dispatches webhook payloads to self-hosted local n8n instances."""

    async def trigger_workflow(
        self,
        meeting: Meeting,
        minutes: MinutesOfMeeting,
        recipients: list[str]
    ) -> DeliveryRecord:
        record = DeliveryRecord(
            meeting_id=meeting.id,
            revision=minutes.revision,
            channel=DeliveryChannel.N8N_WEBHOOK,
            recipients=recipients
        )

        if not recipients:
            logger.error(f"No recipients resolved for meeting '{meeting.title}' -> n8n dispatch aborted.")
            record.status = DeliveryStatus.FAILED
            record.error_message = "No recipients resolved: add attendee emails or a distribution list to this meeting."
            return record

        if not settings.N8N_ENABLED:
            logger.warning("n8n dispatch requested while N8N_ENABLED is False -> recording FAILED.")
            record.status = DeliveryStatus.FAILED
            record.error_message = "n8n automation engine is disabled (N8N_ENABLED=False)"
            return record

        # The webhook payload is what n8n puts into the email: counts and the shared counts-only body,
        # never the summary or any other free text that could carry a person's name. The same name
        # guard as the SMTP channel runs over the subject and body before the webhook is called.
        subject = delivery_router.get_subject_line(meeting, revision=minutes.revision)
        body_text = build_body(meeting, minutes)
        try:
            assert_no_person_names(subject, meeting, minutes, field="subiectul")
            assert_no_person_names(body_text, meeting, minutes, field="corpul")
        except DeliveryError as guard:
            record.status = DeliveryStatus.FAILED
            record.error_message = guard.message
            return record
        record.subject = subject
        record.created_at = datetime.now(timezone.utc)
        record.body_text = body_text
        record.languages_included = get_email_languages(meeting)
        record.to_recipients, record.cc_recipients = delivery_router.split_to_cc(meeting, recipients)

        payload = {
            "event": "meeting.approved",
            "meeting_id": meeting.id,
            "title": meeting.title,
            "meeting_type": meeting.meeting_type.value,
            "revision": minutes.revision,
            "recipients": recipients,
            "subject": subject,
            "body_text": body_text,
            "languages_included": record.languages_included,
            "decisions_count": len(minutes.decisions),
            "actions_count": len(minutes.action_items)
        }

        try:
            logger.info(f"Triggering n8n webhook at {settings.N8N_WEBHOOK_URL}...")
            repository.save_delivery(record)
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(settings.N8N_WEBHOOK_URL, json=payload)
                if res.status_code in [200, 201]:
                    logger.info("n8n workflow triggered successfully.")
                    record.status = DeliveryStatus.DISPATCHED
                    record.sent_at = datetime.now(timezone.utc)
                else:
                    logger.error(f"n8n webhook rejected the payload with HTTP {res.status_code}.")
                    record.status = DeliveryStatus.FAILED
                    record.error_message = f"n8n webhook rejected the payload with HTTP {res.status_code}"
        except Exception as e:
            logger.error(f"Failed to reach local n8n webhook: {e}")
            record.status = DeliveryStatus.FAILED
            record.error_message = f"n8n webhook unreachable: {e}"

        return record


n8n_service = N8nAutomationService()
