"""
Medpark Meeting Intelligence System - Local SMTP Dispatcher
Sends approved Minutes of Meeting with PDF/DOCX attachments to internal SMTP / Mailpit.
"""

from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Optional
import aiosmtplib
from app.core.config import settings
from app.core.logging import logger
from app.models.meeting import Meeting
from app.models.extraction import MinutesOfMeeting
from app.models.delivery import DeliveryRecord, DeliveryStatus, DeliveryChannel
from app.services.delivery.router import delivery_router


class SMTPDeliveryService:
    """Manages secure, air-gapped email dispatch to local hospital SMTP or Mailpit."""

    async def deliver(
        self,
        meeting: Meeting,
        minutes: MinutesOfMeeting,
        pdf_path: Optional[Path] = None,
        docx_path: Optional[Path] = None
    ) -> DeliveryRecord:
        recipients = delivery_router.resolve_recipients(meeting)
        subject = delivery_router.get_subject_line(meeting, revision=minutes.revision)

        record = DeliveryRecord(
            meeting_id=meeting.id,
            revision=minutes.revision,
            channel=DeliveryChannel.DIRECT_SMTP,
            recipients=recipients,
            subject=subject,
            pdf_attachment_path=str(pdf_path) if pdf_path else None,
            docx_attachment_path=str(docx_path) if docx_path else None
        )

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
        msg["To"] = ", ".join(recipients)

        # Plain text & HTML Body in Romanian
        body_text = (
            f"Stimați Colegi,\n\n"
            f"Vă transmitem procesul-verbal oficial (Minutes of Meeting) aferent ședinței '{meeting.title}', "
            f"desfășurată la data de {meeting.scheduled_at.strftime('%d.%m.%Y %H:%M')}.\n\n"
            f"Sumar decizii și acțiuni:\n"
            f"- Decizii adoptate: {len(minutes.decisions)}\n"
            f"- Sarcini de lucru stabilite: {len(minutes.action_items)}\n\n"
            f"Documentele oficiale în format PDF și DOCX sunt atașate prezentului mesaj.\n\n"
            f"Cu respect,\n"
            f"Sistemul Automat de Documentare a Ședințelor Medpark\n"
            f"Spitalul Internațional Medpark\n"
        )
        msg.set_content(body_text)

        # Attach PDF
        if pdf_path and pdf_path.exists():
            with open(pdf_path, "rb") as f:
                pdf_data = f.read()
            msg.add_attachment(
                pdf_data,
                maintype="application",
                subtype="pdf",
                filename=pdf_path.name
            )

        # Attach DOCX
        if docx_path and docx_path.exists():
            with open(docx_path, "rb") as f:
                docx_data = f.read()
            msg.add_attachment(
                docx_data,
                maintype="application",
                subtype="vnd.openxmlformats-officedocument.wordprocessingml.document",
                filename=docx_path.name
            )

        # Transmit via SMTP
        try:
            logger.info(f"Connecting to SMTP server at {settings.SMTP_HOST}:{settings.SMTP_PORT}...")
            await aiosmtplib.send(
                msg,
                hostname=settings.SMTP_HOST,
                port=settings.SMTP_PORT,
                username=settings.SMTP_USERNAME or None,
                password=settings.SMTP_PASSWORD or None,
                use_tls=settings.SMTP_USE_TLS,
                timeout=5.0
            )
            record.status = DeliveryStatus.DISPATCHED
            record.sent_at = datetime.now()
            logger.info(f"Email successfully delivered via SMTP to {len(recipients)} recipients.")
        except Exception as e:
            if settings.ALLOW_SIMULATED_DELIVERY:
                logger.warning(f"SMTP connection to {settings.SMTP_HOST}:{settings.SMTP_PORT} failed ({e}). ALLOW_SIMULATED_DELIVERY is active -> recording SIMULATED.")
                record.status = DeliveryStatus.SIMULATED
                record.error_message = f"Simulated delivery (SMTP unreachable: {e})"
            else:
                logger.error(f"SMTP delivery failed to {settings.SMTP_HOST}:{settings.SMTP_PORT}: {e}")
                record.status = DeliveryStatus.FAILED
                record.error_message = f"SMTP transmission failed: {e}"

        return record


smtp_service = SMTPDeliveryService()
