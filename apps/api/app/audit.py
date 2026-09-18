import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditEvent


def record_audit(
    db: Session,
    *,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID | None,
    organization_id: uuid.UUID | None,
    actor_user_id: uuid.UUID | None,
    metadata: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> AuditEvent:
    event = AuditEvent(
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        event_metadata=metadata or {},
        ip_address=ip_address,
    )
    db.add(event)
    return event
