"""Non-blocking delivery exclusion for this prototype's single API process."""
from contextlib import contextmanager
from threading import Lock
from fastapi import HTTPException
from app.models.delivery import DeliveryRecord, DeliveryStatus
from app.models.meeting import ReviewStatus
from app.storage.repository import repository

_dispatch_lock = Lock()


@contextmanager
def dispatch_lock():
    if not _dispatch_lock.acquire(blocking=False):
        raise HTTPException(409, "Another delivery is in progress. Refresh the outbox before retrying.")
    try:
        yield
    finally:
        _dispatch_lock.release()


def record_outcome(record: DeliveryRecord):
    """A network await must never roll back concurrent edits or resurrect a deleted meeting."""
    with repository.lock:
        current = repository.get_meeting(record.meeting_id)
        if current is None:
            raise HTTPException(409, "Meeting was deleted during delivery. Check the relay before any resend.")
        repository.save_delivery(record)
        if current.current_revision == record.revision and current.review_status == ReviewStatus.APPROVED:
            if record.status == DeliveryStatus.DISPATCHED:
                current.review_status = ReviewStatus.DELIVERED
            current.error_message = record.error_message
            repository.save_meeting(current)
        elif record.status == DeliveryStatus.DISPATCHED and current.review_status == ReviewStatus.APPROVED:
            current.review_status = ReviewStatus.DELIVERED
            current.error_message = None
            repository.save_meeting(current)
        return current
