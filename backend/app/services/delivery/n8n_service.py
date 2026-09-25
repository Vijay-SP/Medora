"""
Medpark Meeting Intelligence System - n8n Automation Engine Client
Dispatches approved meeting payloads to self-hosted n8n workflows for complex routing.
"""

from typing import Optional
import httpx
from app.core.config import settings
from app.core.logging import logger
from app.models.meeting import Meeting
from app.models.extraction import MinutesOfMeeting
from app.models.delivery import DeliveryRecord, DeliveryStatus, DeliveryChannel


class N8nAutomationService:
    """Dispatches webhook payloads to self-hosted local n8n instances."""

    async def trigger_workflow(
        self,
        meeting: Meeting,
        minutes: MinutesOfMeeting,
        recipients: list[str]
    ) -> Optional[DeliveryRecord]:
        if not settings.N8N_ENABLED:
            return None

        payload = {
            "event": "meeting.approved",
            "meeting_id": meeting.id,
            "title": meeting.title,
            "meeting_type": meeting.meeting_type.value,
            "recipients": recipients,
            "summary_ro": minutes.summary_ro,
            "decisions_count": len(minutes.decisions),
            "actions_count": len(minutes.action_items)
        }

        try:
            logger.info(f"Triggering n8n webhook at {settings.N8N_WEBHOOK_URL}...")
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(settings.N8N_WEBHOOK_URL, json=payload)
                if res.status_code in [200, 201]:
                    logger.info("n8n workflow triggered successfully.")
                    return DeliveryRecord(
                        meeting_id=meeting.id,
                        revision=minutes.revision,
                        channel=DeliveryChannel.N8N_WEBHOOK,
                        recipients=recipients,
                        status=DeliveryStatus.DISPATCHED
                    )
        except Exception as e:
            logger.warning(f"Failed to reach local n8n webhook: {e}")
            
        return None


n8n_service = N8nAutomationService()
