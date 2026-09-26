"""
Medpark Meeting Intelligence System - Local SMTP Dispatcher
Sends approved Minutes of Meeting with PDF/DOCX attachments to internal SMTP / Mailpit.
"""

from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Optional
import re
import aiosmtplib
from app.core.config import settings
from app.core.exceptions import DeliveryError
from app.core.logging import logger
from app.models.meeting import Meeting
from app.models.extraction import MinutesOfMeeting
from app.models.delivery import DeliveryRecord, DeliveryStatus, DeliveryChannel
from app.services.delivery.router import delivery_router

# Owner sources that hold a person's name (an anonymous "Speaker N" owner and "Unassigned" are not names)
NAMED_OWNER_SOURCES = frozenset({"roster", "mention", "confirmed_speaker"})
# Title tokens that are not part of a person's identity and must not trigger the name guard alone
NAME_HONORIFICS = frozenset({"dr", "dna", "dl", "prof", "conf", "asist", "med", "doamna", "domnul", "sef", "șef"})
NAME_TOKEN_MIN_LENGTH = 4
NAME_LEAK_MESSAGE = (
    "Expediere blocată: {field} emailului conține un nume de persoană ({names}). "
    "Numele apar exclusiv în documentele atașate."
)


def collect_protected_names(meeting: Meeting, minutes: MinutesOfMeeting) -> list[str]:
    """
    Every person name the email must not carry: the attendee roster plus the names the minutes
    already resolved (named owners and reviewer-confirmed evidence speakers).
    """
    names: set[str] = {att.name for att in meeting.attendees if att.name}
    for item in minutes.action_items:
        if item.owner_source in NAMED_OWNER_SOURCES and item.owner:
            names.add(item.owner)
    for item in [*minutes.decisions, *minutes.action_items, *minutes.risks_and_questions]:
        for evidence in item.evidence:
            if evidence.speaker_is_confirmed and evidence.speaker:
                names.add(evidence.speaker)
    return sorted(name.strip() for name in names if name and name.strip())


def find_person_names(text: str, names: list[str]) -> list[str]:
    """
    Names found in a text, matched case-insensitively on the full name or on any distinctive token
    (four or more letters, honorifics excluded) so 'Ceban' alone still trips the guard.
    """
    found: list[str] = []
    for name in names:
        full = re.sub(r"\s+", " ", name.strip())
        patterns = [re.escape(full)]
        for token in full.split(" "):
            bare = token.strip(".,;:()").casefold()
            if len(bare) >= NAME_TOKEN_MIN_LENGTH and bare not in NAME_HONORIFICS:
                patterns.append(re.escape(token.strip(".,;:()")))
        if any(re.search(rf"(?<!\w){pattern}(?!\w)", text, flags=re.IGNORECASE) for pattern in patterns):
            found.append(full)
    return found


def assert_no_person_names(text: str, meeting: Meeting, minutes: MinutesOfMeeting, field: str = "corpul") -> None:
    """Raises DeliveryError when the email text carries any protected person name; names travel only in attachments."""
    leaked = find_person_names(text, collect_protected_names(meeting, minutes))
    if leaked:
        logger.error(f"Name guard tripped on the email {field} of meeting {meeting.id}: {leaked}")
        raise DeliveryError(NAME_LEAK_MESSAGE.format(field=field, names=", ".join(leaked)), details={"names": leaked, "field": field})


def build_body(
    meeting: Meeting,
    minutes: MinutesOfMeeting,
    pdf_path: Optional[Path] = None,
    docx_path: Optional[Path] = None
) -> str:
    """
    Plain-text email body in Romanian: counts and attachment names only.
    No summary, decision, task or owner text is ever inlined: those fields can carry person names and
    the only reviewed rendering of them is the attached document.
    """
    attachments = [path.name for path in (pdf_path, docx_path) if path]
    attachment_line = (
        f"Documente atașate: {', '.join(attachments)}." if attachments
        else "Documentele oficiale în format PDF și DOCX sunt atașate prezentului mesaj."
    )
    return (
        f"Stimați Colegi,\n\n"
        f"Vă transmitem procesul-verbal oficial (Minutes of Meeting) aferent ședinței '{meeting.title}', "
        f"desfășurată la data de {meeting.scheduled_at.strftime('%d.%m.%Y %H:%M')} (Rev.{minutes.revision}).\n\n"
        f"Sumar decizii și acțiuni:\n"
        f"- Decizii adoptate: {len(minutes.decisions)}\n"
        f"- Sarcini de lucru stabilite: {len(minutes.action_items)}\n"
        f"- Riscuri și întrebări deschise: {len(minutes.risks_and_questions)}\n\n"
        f"{attachment_line}\n\n"
        f"Cu respect,\n"
        f"Sistemul Automat de Documentare a Ședințelor Medpark\n"
        f"Spitalul Internațional Medpark\n"
    )


class SMTPDeliveryService:
    """Manages secure, air-gapped email dispatch to local hospital SMTP or Mailpit."""

    async def deliver(
        self,
        meeting: Meeting,
        minutes: MinutesOfMeeting,
        pdf_path: Optional[Path] = None,
        docx_path: Optional[Path] = None,
        recipients: Optional[list[str]] = None
    ) -> DeliveryRecord:
        # Callers may hand over an already resolved list so that SMTP and n8n address the same people
        recipients = recipients if recipients is not None else delivery_router.resolve_recipients(meeting)
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

        if not recipients:
            logger.error(f"No recipients resolved for meeting '{meeting.title}' -> SMTP dispatch aborted.")
            record.status = DeliveryStatus.FAILED
            record.error_message = "No recipients resolved: add attendee emails or a distribution list to this meeting."
            return record

        # Names travel only inside the attachments: the subject (meeting title) and the counts-only
        # body are checked against the roster and the confirmed names before anything is connected.
        body_text = build_body(meeting, minutes, pdf_path, docx_path)
        try:
            assert_no_person_names(subject, meeting, minutes, field="subiectul")
            assert_no_person_names(body_text, meeting, minutes, field="corpul")
        except DeliveryError as guard:
            record.status = DeliveryStatus.FAILED
            record.error_message = guard.message
            return record

        # Policy CC addresses (e.g. the medical archive) must travel in Cc, not in To
        to_list, cc_list = delivery_router.split_to_cc(meeting, recipients)

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
        msg["To"] = ", ".join(to_list)
        if cc_list:
            msg["Cc"] = ", ".join(cc_list)

        # Plain text body in Romanian (counts + attachment names only)
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
            record.sent_at = datetime.now(timezone.utc)
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
