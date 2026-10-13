import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.config import Settings
from app.knowledge.models import IngestionJob, JobStatus
from app.models import DocumentVersion, IngestionStatus


class LostLease(RuntimeError):
    pass


def database_now(db: Session) -> datetime:
    if db.get_bind().dialect.name != "postgresql":
        return datetime.now(UTC)  # Fast tests; SQLite CURRENT_TIMESTAMP loses subsecond precision.
    value = db.scalar(select(func.clock_timestamp() if db.get_bind().dialect.name == "postgresql" else func.now()))
    assert isinstance(value, datetime)
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def transition(version: DocumentVersion, target: IngestionStatus) -> None:
    legal = {
        IngestionStatus.PENDING_UPLOAD: {IngestionStatus.UPLOADED},
        IngestionStatus.UPLOADED: {IngestionStatus.PROCESSING},
        IngestionStatus.PROCESSING: {IngestionStatus.READY, IngestionStatus.FAILED},
        IngestionStatus.FAILED: {IngestionStatus.UPLOADED, IngestionStatus.PROCESSING},
        IngestionStatus.READY: set(),
    }
    if target not in legal[version.ingestion_status]:
        raise ValueError("Illegal ingestion state transition")
    version.ingestion_status = target


def enqueue(db: Session, version: DocumentVersion, settings: Settings) -> IngestionJob:
    if version.ingestion_status != IngestionStatus.UPLOADED:
        raise ValueError("Only persisted clean uploaded sources can be queued")
    job = IngestionJob(organization_id=version.organization_id, document_version_id=version.id,
                       max_attempts=settings.ingestion_max_attempts)
    db.add(job)
    return job


@dataclass(frozen=True)
class ClaimedJob:
    id: uuid.UUID
    organization_id: uuid.UUID
    document_version_id: uuid.UUID
    lease_owner: uuid.UUID
    attempt: int
    storage_key: str
    mime_type: str
    sha256: str
    size_bytes: int


def _version(db: Session, job: IngestionJob) -> DocumentVersion:
    version = db.scalar(select(DocumentVersion).where(
        DocumentVersion.organization_id == job.organization_id,
        DocumentVersion.id == job.document_version_id,
    ))
    if not version:
        raise ValueError("Invalid job lineage")
    return version


def _audit(db: Session, job: IngestionJob, action: str, metadata: dict[str, object] | None = None) -> None:
    record_audit(db, action=f"document.ingestion_{action}", resource_type="document_version",
                 resource_id=job.document_version_id, organization_id=job.organization_id,
                 actor_user_id=None, metadata={"job_id": str(job.id), "attempt": job.attempt_count, **(metadata or {})})


def claim(db: Session, settings: Settings) -> ClaimedJob | None:
    now = database_now(db)
    job = db.scalar(select(IngestionJob).where(or_(
        and_(IngestionJob.status.in_([JobStatus.PENDING, JobStatus.RETRYABLE]), IngestionJob.available_at <= now),
        and_(IngestionJob.status == JobStatus.RUNNING, IngestionJob.lease_expires_at <= now),
    )).order_by(IngestionJob.available_at, IngestionJob.id).limit(1).with_for_update(skip_locked=True))
    if not job:
        db.rollback()
        return None
    version = _version(db, job)
    if job.attempt_count >= job.max_attempts:
        job.status = JobStatus.FAILED
        job.lease_owner = job.lease_expires_at = None
        job.completed_at = now
        job.last_error_code, job.last_error_message = "attempts_exhausted", "Processing attempts were exhausted. An administrator may retry."
        if version.ingestion_status == IngestionStatus.PROCESSING:
            transition(version, IngestionStatus.FAILED)
        version.ingestion_error_code, version.ingestion_retryable = job.last_error_code, True
        _audit(db, job, "failed", {"error_code": job.last_error_code})
        db.commit()
        return None
    job.status = JobStatus.RUNNING
    job.attempt_count += 1
    job.lease_owner = uuid.uuid4()
    job.lease_expires_at = now + timedelta(seconds=settings.worker_lease_seconds)
    job.started_at, job.completed_at = now, None
    job.last_error_code = job.last_error_message = None
    if version.ingestion_status != IngestionStatus.PROCESSING:
        transition(version, IngestionStatus.PROCESSING)
    version.ingestion_error_code, version.ingestion_retryable = None, False
    _audit(db, job, "started")
    result = ClaimedJob(job.id, job.organization_id, job.document_version_id, job.lease_owner,
                        job.attempt_count, version.storage_key, version.mime_type, version.sha256, version.size_bytes)
    db.commit()
    return result


def owned_job(db: Session, claim: ClaimedJob) -> IngestionJob:
    job = db.scalar(select(IngestionJob).where(
        IngestionJob.id == claim.id, IngestionJob.organization_id == claim.organization_id,
        IngestionJob.document_version_id == claim.document_version_id,
    ).with_for_update())
    now = database_now(db)
    if not job or job.status != JobStatus.RUNNING or job.lease_owner != claim.lease_owner or not job.lease_expires_at:
        raise LostLease()
    expiry = job.lease_expires_at.replace(tzinfo=UTC) if job.lease_expires_at.tzinfo is None else job.lease_expires_at
    if expiry <= now:
        raise LostLease()
    return job


def renew(db: Session, claimed: ClaimedJob, settings: Settings) -> bool:
    now = database_now(db)
    result = db.execute(update(IngestionJob).where(
        IngestionJob.id == claimed.id, IngestionJob.organization_id == claimed.organization_id,
        IngestionJob.status == JobStatus.RUNNING, IngestionJob.lease_owner == claimed.lease_owner,
        IngestionJob.lease_expires_at > now,
    ).values(lease_expires_at=now + timedelta(seconds=settings.worker_lease_seconds)))
    db.commit()
    return bool(result.rowcount)  # type: ignore[attr-defined]


def fail(db: Session, claimed: ClaimedJob, settings: Settings, *, code: str, retryable: bool) -> None:
    job = owned_job(db, claimed)
    version = _version(db, job)
    now = database_now(db)
    retry = retryable and job.attempt_count < job.max_attempts
    job.status = JobStatus.RETRYABLE if retry else JobStatus.FAILED
    job.available_at = now + timedelta(seconds=min(3600, settings.ingestion_retry_base_seconds * 2 ** (job.attempt_count - 1)))
    job.completed_at = None if retry else now
    job.lease_owner = job.lease_expires_at = None
    # Codes are selected by application code, never taken from exception messages.
    job.last_error_code = code
    job.last_error_message = "Processing is temporarily unavailable and will retry." if retry else "This file could not be processed."
    transition(version, IngestionStatus.FAILED)
    version.ingestion_error_code, version.ingestion_retryable = code, retryable
    _audit(db, job, "failed", {"error_code": code, "retry_scheduled": retry})
    db.commit()


def retry(db: Session, version: DocumentVersion, settings: Settings, actor_id: uuid.UUID) -> None:
    job = db.scalar(select(IngestionJob).where(
        IngestionJob.organization_id == version.organization_id,
        IngestionJob.document_version_id == version.id,
    ).with_for_update())
    # Refresh after waiting for a concurrent retry/finalization lock.
    db.refresh(version)
    if not job:
        if version.ingestion_status != IngestionStatus.UPLOADED:
            raise ValueError("Only uploaded legacy sources can be queued")
        enqueue(db, version, settings)
    elif job.status == JobStatus.FAILED:
        transition(version, IngestionStatus.UPLOADED)
        version.ingestion_error_code, version.ingestion_retryable = None, False
        job.status, job.attempt_count, job.max_attempts = JobStatus.PENDING, 0, settings.ingestion_max_attempts
        job.available_at = database_now(db)
        job.started_at = job.completed_at = None
        job.last_error_code = job.last_error_message = None
    else:
        return
    record_audit(db, action="document.ingestion_retried", resource_type="document_version",
                 resource_id=version.id, organization_id=version.organization_id, actor_user_id=actor_id)
