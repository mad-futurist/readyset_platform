from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from app.dependencies import Db, OrgContext
from app.models import AuditEvent
from app.policy import Capability, require_capability
from app.schemas import AuditEventRead, Page

router = APIRouter(prefix="/audit-events", tags=["audit"])


@router.get("", response_model=Page)
def list_audit_events(db: Db, context: OrgContext, page: int = 1, page_size: int = 50) -> Page:
    require_capability(context, Capability.VIEW_AUDIT)
    if page < 1 or page_size < 1 or page_size > 100:
        raise HTTPException(status_code=422, detail="Invalid pagination")
    total = (
        db.scalar(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.organization_id == context.organization.id
            )
        )
        or 0
    )
    events = list(
        db.scalars(
            select(AuditEvent)
            .where(AuditEvent.organization_id == context.organization.id)
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return Page(
        items=[AuditEventRead.model_validate(event) for event in events],
        page=page,
        page_size=page_size,
        total=total,
    )
