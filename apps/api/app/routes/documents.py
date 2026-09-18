import hashlib
import logging
import re
import tempfile
import uuid
from pathlib import PurePath

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select

from app.audit import record_audit
from app.config import Settings, get_settings
from app.dependencies import Csrf, Db, OrgContext
from app.file_security import FileSecurityScanner, ScanResult
from app.file_validation import InvalidFileContent, validate_content
from app.models import (
    Document,
    DocumentStatus,
    DocumentTeamGrant,
    DocumentUserGrant,
    DocumentVersion,
    DocumentVisibility,
    IngestionStatus,
    MembershipStatus,
    OrganizationMembership,
    Team,
)
from app.policy import (
    Capability,
    can_manage_document,
    document_access_predicate,
    require_capability,
)
from app.rate_limit import check_upload_rate
from app.repositories import DocumentRepository
from app.schemas import (
    DocumentGrantRead,
    DocumentGrantUpdate,
    DocumentRead,
    DocumentUpdate,
    DocumentVersionRead,
    Page,
)
from app.storage import ObjectStorage

router = APIRouter(prefix="/documents", tags=["documents"])
logger = logging.getLogger("readyset.documents")


def get_storage(request: Request) -> ObjectStorage:
    return request.app.state.storage  # type: ignore[no-any-return]


def get_file_scanner(request: Request) -> FileSecurityScanner:
    return request.app.state.file_scanner  # type: ignore[no-any-return]


def _safe_filename(value: str | None) -> str:
    name = PurePath(value or "upload").name
    name = re.sub(r"[\x00-\x1f\x7f]+", "", name).strip()
    return name[:255] or "upload"


def _stage_upload(
    file: UploadFile, settings: Settings
) -> tuple[tempfile.SpooledTemporaryFile[bytes], int, str, str]:
    declared_mime = (file.content_type or "application/octet-stream").lower()
    if declared_mime not in settings.allowed_content_types:
        raise HTTPException(status_code=415, detail="Unsupported file type")
    staged = tempfile.SpooledTemporaryFile(max_size=min(settings.max_upload_bytes, 8 * 1024 * 1024))
    digest = hashlib.sha256()
    size = 0
    while chunk := file.file.read(64 * 1024):
        size += len(chunk)
        if size > settings.max_upload_bytes:
            staged.close()
            raise HTTPException(status_code=413, detail="Upload exceeds maximum size")
        digest.update(chunk)
        staged.write(chunk)
    staged.seek(0)
    try:
        mime = validate_content(staged, declared_mime)
    except InvalidFileContent as exc:
        staged.close()
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    return staged, size, digest.hexdigest(), mime


def _scan_upload(staged: tempfile.SpooledTemporaryFile[bytes], scanner: FileSecurityScanner) -> None:
    result = scanner.scan(staged)
    staged.seek(0)
    if result == ScanResult.INFECTED:
        raise HTTPException(status_code=422, detail="File did not pass security inspection")
    if result == ScanResult.UNAVAILABLE:
        raise HTTPException(status_code=503, detail="File security inspection is unavailable")


def _readable_document(db: Db, context: OrgContext, document_id: uuid.UUID) -> Document:
    document = DocumentRepository(db, context).get_readable(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


def _managed_document(db: Db, context: OrgContext, document_id: uuid.UUID) -> Document:
    document = DocumentRepository(db, context).get_in_organization(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    if not can_manage_document(context, document):
        raise HTTPException(status_code=403, detail="Insufficient permission")
    return document


@router.post("", response_model=DocumentRead, status_code=201)
def upload_document(
    db: Db,
    context: OrgContext,
    csrf: Csrf,
    request: Request,
    file: UploadFile = File(...),
    title: str = Form(..., min_length=1, max_length=255),
    description: str | None = Form(None, max_length=5000),
    document_type: str | None = Form(None, max_length=100),
    domain: str | None = Form(None, max_length=100),
    visibility: DocumentVisibility = Form(DocumentVisibility.ORGANIZATION),
    settings: Settings = Depends(get_settings),
    storage: ObjectStorage = Depends(get_storage),
    scanner: FileSecurityScanner = Depends(get_file_scanner),
) -> Document:
    require_capability(context, Capability.UPLOAD_DOCUMENTS)
    if not settings.uploads_enabled:
        raise HTTPException(status_code=503, detail="Uploads are disabled")
    check_upload_rate(request, context.user.id, context.organization.id)
    document_id = uuid.uuid4()
    version_id = uuid.uuid4()
    document = Document(
        id=document_id,
        organization_id=context.organization.id,
        title=title.strip(),
        description=description,
        document_type=document_type,
        domain=domain,
        owner_user_id=context.user.id,
        visibility=visibility,
    )
    version = DocumentVersion(
        id=version_id,
        organization_id=context.organization.id,
        document_id=document_id,
        version_number=1,
        storage_key=f"organizations/{context.organization.id}/documents/{document_id}/versions/{version_id}/source",
        original_filename=_safe_filename(file.filename),
        mime_type=file.content_type or "application/octet-stream",
        size_bytes=0,
        sha256="0" * 64,
        ingestion_status=IngestionStatus.PENDING_UPLOAD,
        created_by_user_id=context.user.id,
    )
    staged, size, checksum, mime = _stage_upload(file, settings)
    try:
        _scan_upload(staged, scanner)
    except Exception:
        staged.close()
        raise
    version.mime_type, version.size_bytes, version.sha256 = mime, size, checksum
    object_written = False
    try:
        storage.put_stream(version.storage_key, staged, mime)
        object_written = True
        version.ingestion_status = IngestionStatus.UPLOADED
        db.add_all([document, version])
        db.flush()
        document.current_version_id = version.id
        record_audit(
            db,
            action="document.created",
            resource_type="document",
            resource_id=document.id,
            organization_id=context.organization.id,
            actor_user_id=context.user.id,
            metadata={"version_id": str(version.id), "size_bytes": size},
        )
        record_audit(
            db,
            action="document.version_uploaded",
            resource_type="document_version",
            resource_id=version.id,
            organization_id=context.organization.id,
            actor_user_id=context.user.id,
        )
        db.commit()
    except Exception:
        db.rollback()
        if object_written:
            try:
                storage.delete(version.storage_key)
            except Exception:
                logger.exception(
                    "Object compensation failed storage_key=%s", version.storage_key
                )
        raise
    finally:
        staged.close()
    return document


@router.get("", response_model=Page[DocumentRead])
def list_documents(
    db: Db, context: OrgContext, page: int = 1, page_size: int = 50
) -> Page[DocumentRead]:
    if page < 1 or page_size < 1 or page_size > 100:
        raise HTTPException(status_code=422, detail="Invalid pagination")
    predicate = document_access_predicate(context)
    total = (
        db.scalar(
            select(func.count(Document.id)).where(
                predicate, Document.status == DocumentStatus.ACTIVE
            )
        )
        or 0
    )
    items = list(
        db.scalars(
            select(Document)
            .where(predicate, Document.status == DocumentStatus.ACTIVE)
            .order_by(Document.updated_at.desc(), Document.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return Page[DocumentRead](
        items=[DocumentRead.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/{document_id}", response_model=DocumentRead)
def get_document(document_id: uuid.UUID, db: Db, context: OrgContext) -> Document:
    return _readable_document(db, context, document_id)


@router.patch("/{document_id}", response_model=DocumentRead)
def update_document(
    document_id: uuid.UUID, payload: DocumentUpdate, db: Db, context: OrgContext, csrf: Csrf
) -> Document:
    document = _managed_document(db, context, document_id)
    for name, value in payload.model_dump(exclude_unset=True).items():
        setattr(document, name, value.strip() if isinstance(value, str) else value)
    record_audit(
        db,
        action="document.updated",
        resource_type="document",
        resource_id=document.id,
        organization_id=context.organization.id,
        actor_user_id=context.user.id,
    )
    db.commit()
    return document


@router.get("/{document_id}/versions", response_model=list[DocumentVersionRead])
def list_versions(document_id: uuid.UUID, db: Db, context: OrgContext) -> list[DocumentVersion]:
    _readable_document(db, context, document_id)
    return list(
        db.scalars(
            select(DocumentVersion)
            .where(
                DocumentVersion.organization_id == context.organization.id,
                DocumentVersion.document_id == document_id,
            )
            .order_by(DocumentVersion.version_number.desc())
        )
    )


@router.post("/{document_id}/versions", response_model=DocumentVersionRead, status_code=201)
def upload_version(
    document_id: uuid.UUID,
    file: UploadFile,
    db: Db,
    context: OrgContext,
    csrf: Csrf,
    request: Request,
    settings: Settings = Depends(get_settings),
    storage: ObjectStorage = Depends(get_storage),
    scanner: FileSecurityScanner = Depends(get_file_scanner),
) -> DocumentVersion:
    if not settings.uploads_enabled:
        raise HTTPException(status_code=503, detail="Uploads are disabled")
    check_upload_rate(request, context.user.id, context.organization.id)
    document = _managed_document(db, context, document_id)
    locked_document = db.scalar(
        select(Document)
        .where(
            Document.id == document.id,
            Document.organization_id == context.organization.id,
            Document.status == DocumentStatus.ACTIVE,
        )
        .with_for_update()
    )
    if not locked_document:
        raise HTTPException(status_code=404, detail="Document not found")
    document = locked_document
    number = (
        db.scalar(
            select(func.max(DocumentVersion.version_number)).where(
                DocumentVersion.organization_id == context.organization.id,
                DocumentVersion.document_id == document.id,
            )
        )
        or 0
    ) + 1
    version_id = uuid.uuid4()
    version = DocumentVersion(
        id=version_id,
        organization_id=context.organization.id,
        document_id=document.id,
        version_number=number,
        storage_key=f"organizations/{context.organization.id}/documents/{document.id}/versions/{version_id}/source",
        original_filename=_safe_filename(file.filename),
        mime_type=file.content_type or "application/octet-stream",
        size_bytes=0,
        sha256="0" * 64,
        ingestion_status=IngestionStatus.PENDING_UPLOAD,
        created_by_user_id=context.user.id,
    )
    staged, size, checksum, mime = _stage_upload(file, settings)
    try:
        _scan_upload(staged, scanner)
    except Exception:
        staged.close()
        raise
    version.mime_type, version.size_bytes, version.sha256 = mime, size, checksum
    object_written = False
    try:
        storage.put_stream(version.storage_key, staged, mime)
        object_written = True
        version.ingestion_status = IngestionStatus.UPLOADED
        db.add(version)
        db.flush()
        document.current_version_id = version.id
        record_audit(
            db,
            action="document.version_uploaded",
            resource_type="document_version",
            resource_id=version.id,
            organization_id=context.organization.id,
            actor_user_id=context.user.id,
            metadata={"document_id": str(document.id), "version_number": number},
        )
        db.commit()
    except Exception:
        db.rollback()
        if object_written:
            try:
                storage.delete(version.storage_key)
            except Exception:
                logger.exception(
                    "Object compensation failed storage_key=%s", version.storage_key
                )
        raise
    finally:
        staged.close()
    return version


@router.get("/{document_id}/versions/{version_id}/download")
def download_version(
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    db: Db,
    context: OrgContext,
    storage: ObjectStorage = Depends(get_storage),
) -> StreamingResponse:
    _readable_document(db, context, document_id)
    version = DocumentRepository(db, context).get_version(document_id, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Document version not found")
    opened = storage.open_stream(version.storage_key)
    try:
        record_audit(
            db,
            action="document.downloaded",
            resource_type="document_version",
            resource_id=version.id,
            organization_id=context.organization.id,
            actor_user_id=context.user.id,
            metadata={"document_id": str(document_id)},
        )
        db.commit()
    except Exception:
        opened.close()
        raise
    safe_ascii = re.sub(r"[^A-Za-z0-9._-]+", "_", version.original_filename)
    return StreamingResponse(
        opened.iter_bytes(),
        media_type=version.mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{safe_ascii}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{document_id}/access", response_model=DocumentGrantRead)
def get_grants(document_id: uuid.UUID, db: Db, context: OrgContext) -> DocumentGrantRead:
    _managed_document(db, context, document_id)
    users = list(
        db.scalars(
            select(DocumentUserGrant.user_id).where(
                DocumentUserGrant.organization_id == context.organization.id,
                DocumentUserGrant.document_id == document_id,
            )
        )
    )
    teams = list(
        db.scalars(
            select(DocumentTeamGrant.team_id).where(
                DocumentTeamGrant.organization_id == context.organization.id,
                DocumentTeamGrant.document_id == document_id,
            )
        )
    )
    return DocumentGrantRead(user_ids=users, team_ids=teams)


@router.put("/{document_id}/access", response_model=DocumentGrantRead)
def replace_grants(
    document_id: uuid.UUID, payload: DocumentGrantUpdate, db: Db, context: OrgContext, csrf: Csrf
) -> DocumentGrantRead:
    document = _managed_document(db, context, document_id)
    user_ids, team_ids = set(payload.user_ids), set(payload.team_ids)
    valid_users = (
        set(
            db.scalars(
                select(OrganizationMembership.user_id).where(
                    OrganizationMembership.organization_id == context.organization.id,
                    OrganizationMembership.status == MembershipStatus.ACTIVE,
                    OrganizationMembership.user_id.in_(user_ids),
                )
            )
        )
        if user_ids
        else set()
    )
    valid_teams = (
        set(
            db.scalars(
                select(Team.id).where(
                    Team.organization_id == context.organization.id, Team.id.in_(team_ids)
                )
            )
        )
        if team_ids
        else set()
    )
    if valid_users != user_ids or valid_teams != team_ids:
        raise HTTPException(status_code=422, detail="A grant principal is outside the organization")
    db.execute(
        delete(DocumentUserGrant).where(
            DocumentUserGrant.organization_id == context.organization.id,
            DocumentUserGrant.document_id == document.id,
        )
    )
    db.execute(
        delete(DocumentTeamGrant).where(
            DocumentTeamGrant.organization_id == context.organization.id,
            DocumentTeamGrant.document_id == document.id,
        )
    )
    db.add_all(
        [
            DocumentUserGrant(
                organization_id=context.organization.id,
                document_id=document.id,
                user_id=user_id,
                created_by_user_id=context.user.id,
            )
            for user_id in user_ids
        ]
    )
    db.add_all(
        [
            DocumentTeamGrant(
                organization_id=context.organization.id,
                document_id=document.id,
                team_id=team_id,
                created_by_user_id=context.user.id,
            )
            for team_id in team_ids
        ]
    )
    record_audit(
        db,
        action="document.permission_changed",
        resource_type="document",
        resource_id=document.id,
        organization_id=context.organization.id,
        actor_user_id=context.user.id,
        metadata={"user_grants": len(user_ids), "team_grants": len(team_ids)},
    )
    db.commit()
    return DocumentGrantRead(user_ids=sorted(user_ids, key=str), team_ids=sorted(team_ids, key=str))


@router.delete("/{document_id}", status_code=204)
def archive_document(document_id: uuid.UUID, db: Db, context: OrgContext, csrf: Csrf) -> None:
    document = _managed_document(db, context, document_id)
    document.status = DocumentStatus.ARCHIVED
    record_audit(
        db,
        action="document.deleted",
        resource_type="document",
        resource_id=document.id,
        organization_id=context.organization.id,
        actor_user_id=context.user.id,
    )
    db.commit()
