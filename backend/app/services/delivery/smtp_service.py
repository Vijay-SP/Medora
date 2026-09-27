"""
Medpark Meeting Intelligence System - Local SMTP Dispatcher
Sends approved Minutes of Meeting with PDF/DOCX attachments to internal SMTP / Mailpit.
"""

from datetime import datetime, timezone
from email.message import EmailMessage
from email import policy
from email.utils import format_datetime, make_msgid
import hashlib
import os
import tempfile
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
from app.storage.repository import repository
from app.storage.file_manager import file_manager


def get_email_languages(meeting: Meeting) -> list[str]:
    """Meeting snapshot wins; older attendees fall back to their registered preference."""
    found = {"ro"}
    for attendee in meeting.attendees:
        language = attendee.primary_language
        if not language and attendee.person_id:
            person = repository.get_person(attendee.person_id)
            language = person.primary_language if person else None
        if language:
            found.add(language.strip().lower())
    return [language for language in ("ro", "ru", "en") if language in found]

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
    romanian = (
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
        f"Spitalul Internațional Medpark\n\n"
        f"---\n"
        f"Aviz de transparență AI (EU AI Act Art. 50): Acest document a fost redactat cu asistență AI "
        f"și verificat/aprobat formal de un revizor uman înainte de transmitere.\n"
    )
    sections = ["Română (RO)\n\n" + romanian]
    languages = get_email_languages(meeting)
    # Fixed notification templates deliberately do not use the LLM or cached MoM translations.
    # Only counts, metadata and attachment references enter the email body.
    date = meeting.scheduled_at.strftime('%d.%m.%Y %H:%M')
    attachment_names = ', '.join(attachments) or 'PDF / DOCX'
    if "ru" in languages:
        sections.append(
            f"Русский (RU)\n\nУважаемые коллеги,\n\n"
            f"Направляем официальный протокол заседания '{meeting.title}' от {date} (Rev.{minutes.revision}).\n\n"
            f"Принято решений: {len(minutes.decisions)}\n"
            f"Поставлено задач: {len(minutes.action_items)}\n"
            f"Риски и открытые вопросы: {len(minutes.risks_and_questions)}\n\n"
            f"Приложения: {attachment_names}. Официальные документы прилагаются на румынском языке.\n\n"
            "С уважением,\nСистема документирования заседаний Medpark\nМеждународная больница Medpark\n\n"
            "---\n"
            "Уведомление об ИИ (EU AI Act ст. 50): Данный протокол составлен с помощью ИИ "
            "и проверен/утвержден ответственным лицом перед отправкой.\n"
        )
    if "en" in languages:
        sections.append(
            f"English (EN)\n\nDear colleagues,\n\n"
            f"Please find the official minutes for '{meeting.title}', held on {date} (Rev.{minutes.revision}).\n\n"
            f"Decisions adopted: {len(minutes.decisions)}\n"
            f"Actions assigned: {len(minutes.action_items)}\n"
            f"Risks and open questions: {len(minutes.risks_and_questions)}\n\n"
            f"Attachments: {attachment_names}. The official documents are attached in Romanian.\n\n"
            "Kind regards,\nMedpark Meeting Documentation System\nMedpark International Hospital\n\n"
            "---\n"
            "AI Compliance Notice (EU AI Act Art. 50): This minutes document was prepared with AI assistance "
            "and formally verified/approved by a human reviewer prior to dispatch.\n"
        )
    return "\n--------------------\n\n".join(sections)


def save_message(record: DeliveryRecord, raw: bytes) -> None:
    """Publish the complete MIME artifact atomically; a partial file is never downloadable."""
    path = file_manager.get_delivery_eml_path(record.meeting_id, record.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
    record.eml_sha256 = hashlib.sha256(raw).hexdigest()
    record.eml_available = True


def read_message(record: DeliveryRecord) -> bytes:
    if not record.eml_available:
        raise FileNotFoundError("No saved email for this delivery")
    raw = file_manager.get_delivery_eml_path(record.meeting_id, record.id).read_bytes()
    if hashlib.sha256(raw).hexdigest() != record.eml_sha256:
        raise ValueError("Saved email failed its integrity check")
    return raw


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
            created_at=datetime.now(timezone.utc),
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
            delivery_router.assert_dispatchable(minutes)
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
        msg["Date"] = format_datetime(record.created_at)
        msg["Message-ID"] = make_msgid(domain="medpark.local")
        msg["To"] = ", ".join(to_list)
        if cc_list:
            msg["Cc"] = ", ".join(cc_list)

        # Plain text body in Romanian (counts + attachment names only)
        msg.set_content(body_text, cte="quoted-printable")

        record.body_text = body_text
        record.languages_included = get_email_languages(meeting)
        record.from_header = str(msg["From"])
        record.envelope_sender = settings.SMTP_FROM_EMAIL
        record.to_recipients = to_list
        record.cc_recipients = cc_list
        try:
            for path, subtype in ((pdf_path, "pdf"), (docx_path, "vnd.openxmlformats-officedocument.wordprocessingml.document")):
                if path is None:
                    raise FileNotFoundError("Approved PDF and DOCX attachments are required")
                msg.add_attachment(path.read_bytes(), maintype="application", subtype=subtype, filename=path.name)
            save_message(record, msg.as_bytes(policy=policy.SMTP))
        except (OSError, ValueError) as exc:
            record.status = DeliveryStatus.FAILED
            record.error_message = f"Could not save the complete email: {exc}"
            return record

        if settings.DELIVERY_CHANNEL == "local_outbox":
            record.channel = DeliveryChannel.LOCAL_OUTBOX
            record.status = DeliveryStatus.SAVED_LOCALLY
            record.retry_allowed = True
            return record
        return await self.transmit(record, read_message(record))

    async def transmit(self, record: DeliveryRecord, raw: bytes, *, allow_fallback: bool = True) -> DeliveryRecord:
        # Persist a pending attempt before network I/O. An interrupted process must not silently resend it.
        record.channel = DeliveryChannel.DIRECT_SMTP
        record.status = DeliveryStatus.PENDING
        record.retry_allowed = False
        repository.save_delivery(record)
        use_tls = settings.SMTP_USE_TLS
        start_tls = settings.SMTP_STARTTLS
        if use_tls:
            start_tls = False
        elif start_tls is None:
            if settings.SMTP_PORT == 587:
                start_tls = True
            elif settings.SMTP_PORT in (1025, 25) or settings.SMTP_HOST in ("127.0.0.1", "localhost", "::1"):
                start_tls = False

        try:
            logger.info(f"Connecting to SMTP server at {settings.SMTP_HOST}:{settings.SMTP_PORT} (tls={use_tls}, starttls={start_tls})...")
            try:
                refused, _ = await aiosmtplib.send(
                    raw,
                    sender=record.envelope_sender,
                    recipients=record.recipients,
                    hostname=settings.SMTP_HOST,
                    port=settings.SMTP_PORT,
                    username=settings.SMTP_USERNAME or None,
                    password=settings.SMTP_PASSWORD or None,
                    use_tls=use_tls,
                    start_tls=start_tls,
                    timeout=settings.SMTP_TIMEOUT_SECONDS
                )
            except aiosmtplib.errors.SMTPException as smtp_exc:
                if "STARTTLS extension not supported" in str(smtp_exc) and start_tls is not False:
                    logger.warning(
                        f"SMTP server at {settings.SMTP_HOST}:{settings.SMTP_PORT} does not support STARTTLS: {smtp_exc}. "
                        "Retrying connection in plaintext without STARTTLS..."
                    )
                    refused, _ = await aiosmtplib.send(
                        raw,
                        sender=record.envelope_sender,
                        recipients=record.recipients,
                        hostname=settings.SMTP_HOST,
                        port=settings.SMTP_PORT,
                        username=settings.SMTP_USERNAME or None,
                        password=settings.SMTP_PASSWORD or None,
                        use_tls=False,
                        start_tls=False,
                        timeout=settings.SMTP_TIMEOUT_SECONDS
                    )
                else:
                    raise
            if refused:
                record.status = DeliveryStatus.FAILED
                record.error_message = "Some recipients were refused; others may have received the email. Check the relay before any resend."
                return record
            record.status = DeliveryStatus.DISPATCHED
            record.sent_at = datetime.now(timezone.utc)
            record.smtp_response_code = 250
            logger.info(f"Email accepted by SMTP for {len(record.recipients)} recipients.")
        except Exception as e:
            # Only a definite connection failure may become a local save. A timeout after DATA
            # could mean the server accepted the email, so uncertain outcomes cannot be retried here.
            connection_failed = (
                isinstance(e, (aiosmtplib.errors.SMTPConnectError, ConnectionRefusedError))
                or "Connect call failed" in str(e)
                or "10061" in str(e)
            )
            record.retry_allowed = connection_failed or isinstance(e, (
                aiosmtplib.errors.SMTPException,
                aiosmtplib.errors.SMTPAuthenticationError, aiosmtplib.errors.SMTPRecipientsRefused,
                aiosmtplib.errors.SMTPSenderRefused,
            ))
            if connection_failed and allow_fallback and settings.ENABLE_LOCAL_OUTBOX_FALLBACK:
                record.channel = DeliveryChannel.LOCAL_OUTBOX
                record.status = DeliveryStatus.SAVED_LOCALLY
                record.error_message = "SMTP connection failed. Email saved locally; no email was sent."
            elif connection_failed and settings.ALLOW_SIMULATED_DELIVERY:
                logger.warning(f"SMTP connection to {settings.SMTP_HOST}:{settings.SMTP_PORT} failed ({e}). ALLOW_SIMULATED_DELIVERY is active -> recording SIMULATED.")
                record.status = DeliveryStatus.SIMULATED
                record.error_message = f"Simulated delivery (SMTP unreachable: {e})"
            else:
                logger.error(f"SMTP delivery failed to {settings.SMTP_HOST}:{settings.SMTP_PORT}: {e}")
                record.status = DeliveryStatus.FAILED
                record.error_message = f"SMTP transmission failed: {e}"
        return record

    async def send_saved(self, source: DeliveryRecord) -> DeliveryRecord:
        raw = read_message(source)
        record = source.model_copy(update={
            "id": DeliveryRecord(meeting_id=source.meeting_id).id,
            "created_at": datetime.now(timezone.utc), "retry_of": source.id,
            "sent_at": None, "error_message": None, "smtp_response_code": None,
        })
        # A retry uses exactly the saved bytes and envelope, even if profiles or exports changed.
        save_message(record, raw)
        return await self.transmit(record, raw, allow_fallback=False)


smtp_service = SMTPDeliveryService()
