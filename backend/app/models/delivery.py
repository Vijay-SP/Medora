"""
Medpark Meeting Intelligence System - Delivery & Routing Models
Manages meeting-type email distribution policies, local outbox queue, and SMTP tracking.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field, field_validator
import uuid


class DeliveryChannel(str, Enum):
    DIRECT_SMTP = "direct_smtp"
    N8N_WEBHOOK = "n8n_webhook"


class DeliveryStatus(str, Enum):
    PENDING = "pending"
    DISPATCHED = "dispatched"
    FAILED = "failed"
    SIMULATED = "simulated"


class RoutingPolicy(BaseModel):
    """Routing rules mapping meeting types to official internal distribution groups."""
    meeting_type: str
    department_name: str
    default_recipients: list[str] = Field(default_factory=list)
    cc_recipients: list[str] = Field(default_factory=list)
    subject_prefix: str = "[MEDPARK MoM]"


class DeliveryRecord(BaseModel):
    """Immutable audit entry for every document delivery attempt."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    meeting_id: str
    revision: int = 1
    channel: DeliveryChannel = DeliveryChannel.DIRECT_SMTP
    
    recipients: list[str] = Field(default_factory=list)
    subject: str = ""
    status: DeliveryStatus = DeliveryStatus.PENDING
    
    pdf_attachment_path: Optional[str] = None
    docx_attachment_path: Optional[str] = None
    
    sent_at: Optional[datetime] = None
    error_message: Optional[str] = None
    smtp_response_code: Optional[int] = None
    idempotency_key: str = Field(default_factory=lambda: str(uuid.uuid4()))

    @field_validator("sent_at", mode="before")
    @classmethod
    def validate_sent_at(cls, v: Any) -> Any:
        if v is None:
            return None
        if isinstance(v, str):
            v = datetime.fromisoformat(v.replace("Z", "+00:00"))
        if isinstance(v, datetime):
            if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
                return v.replace(tzinfo=timezone.utc)
            return v.astimezone(timezone.utc)
        return v


# Pre-configured hospital distribution policies as specified in challenge brief
DEFAULT_ROUTING_POLICIES: dict[str, RoutingPolicy] = {
    "medical": RoutingPolicy(
        meeting_type="medical",
        department_name="Consiliul Medical & Șefi Secții",
        default_recipients=["director.medical@medpark.md", "comitet.calitate@medpark.md", "sefi.sectii@medpark.md"],
        cc_recipients=["arhiva.medicala@medpark.md"],
        subject_prefix="[MEDPARK MEDICAL BOARD]"
    ),
    "executive": RoutingPolicy(
        meeting_type="executive",
        department_name="Comitetul Director Executiv",
        default_recipients=["director.general@medpark.md", "director.financiar@medpark.md", "director.operational@medpark.md"],
        cc_recipients=["secretariat.executiv@medpark.md"],
        subject_prefix="[MEDPARK EXECUTIVE]"
    ),
    "administrative": RoutingPolicy(
        meeting_type="administrative",
        department_name="Administrație & Operațiuni Spitalicești",
        default_recipients=["sefi.departamente@medpark.md", "logistica@medpark.md", "achizitii@medpark.md"],
        cc_recipients=["administratie@medpark.md"],
        subject_prefix="[MEDPARK ADMIN]"
    )
}
