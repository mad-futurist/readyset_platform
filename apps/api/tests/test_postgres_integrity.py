import os
import threading
import time
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models import (
    AuthIdentity,
    Document,
    DocumentVersion,
    DocumentVisibility,
    IngestionStatus,
    MembershipStatus,
    Organization,
    OrganizationMembership,
    OrganizationRole,
    User,
)

pytestmark = pytest.mark.postgres


@pytest.fixture
def postgres_factory() -> sessionmaker[Session]:
    if os.getenv("RUN_POSTGRES_TESTS") != "1":
        pytest.skip("set RUN_POSTGRES_TESTS=1 with a migrated PostgreSQL database")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _seed_document(factory: sessionmaker[Session]) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    suffix = uuid.uuid4().hex
    user_id, identity_id, organization_id, document_id = (
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
    )
    with factory() as db:
        db.add(
            User(
                id=user_id,
                primary_email=f"postgres-{suffix}@example.com",
                normalized_email=f"postgres-{suffix}@example.com",
                display_name="Postgres Owner",
            )
        )
        # These models intentionally do not expose ORM relationships for every FK.
        # Flush each dependency layer so the fixture is valid on PostgreSQL rather
        # than relying on incidental unit-of-work ordering.
        db.flush()
        db.add_all(
            [
                AuthIdentity(
                    id=identity_id,
                    user_id=user_id,
                    provider="password",
                    provider_subject=f"postgres-{suffix}@example.com",
                    provider_email=f"postgres-{suffix}@example.com",
                    email_verified_at=datetime.now(UTC),
                ),
                Organization(
                    id=organization_id,
                    name=f"Postgres {suffix}",
                    slug=f"postgres-{suffix}",
                    created_by_user_id=user_id,
                ),
            ]
        )
        db.flush()
        db.add(
            OrganizationMembership(
                organization_id=organization_id,
                user_id=user_id,
                role=OrganizationRole.OWNER,
                status=MembershipStatus.ACTIVE,
            )
        )
        db.flush()
        db.add(
            Document(
                id=document_id,
                organization_id=organization_id,
                title="Concurrent source",
                owner_user_id=user_id,
                visibility=DocumentVisibility.ORGANIZATION,
            )
        )
        db.commit()
    return user_id, organization_id, document_id


def _version(
    *,
    organization_id: uuid.UUID,
    document_id: uuid.UUID,
    user_id: uuid.UUID,
    number: int,
) -> DocumentVersion:
    version_id = uuid.uuid4()
    return DocumentVersion(
        id=version_id,
        organization_id=organization_id,
        document_id=document_id,
        version_number=number,
        storage_key=f"organizations/{organization_id}/documents/{document_id}/versions/{version_id}/source",
        original_filename="source.txt",
        mime_type="text/plain",
        size_bytes=1,
        sha256="0" * 64,
        ingestion_status=IngestionStatus.UPLOADED,
        created_by_user_id=user_id,
    )


def test_current_version_must_belong_to_same_document(
    postgres_factory: sessionmaker[Session],
) -> None:
    user_id, organization_id, first_document_id = _seed_document(postgres_factory)
    second_document_id = uuid.uuid4()
    with postgres_factory() as db:
        db.add(
            Document(
                id=second_document_id,
                organization_id=organization_id,
                title="Second source",
                owner_user_id=user_id,
                visibility=DocumentVisibility.ORGANIZATION,
            )
        )
        db.commit()
        first_version = _version(
            organization_id=organization_id,
            document_id=first_document_id,
            user_id=user_id,
            number=1,
        )
        second_version = _version(
            organization_id=organization_id,
            document_id=second_document_id,
            user_id=user_id,
            number=1,
        )
        db.add_all([first_version, second_version])
        db.commit()
        first_document = db.get(Document, first_document_id)
        assert first_document
        first_document.current_version_id = second_version.id
        with pytest.raises(IntegrityError):
            db.commit()


def test_parent_lock_serializes_concurrent_version_numbers(
    postgres_factory: sessionmaker[Session],
) -> None:
    user_id, organization_id, document_id = _seed_document(postgres_factory)
    with postgres_factory() as db:
        initial = _version(
            organization_id=organization_id,
            document_id=document_id,
            user_id=user_id,
            number=1,
        )
        db.add(initial)
        db.flush()
        document = db.get(Document, document_id)
        assert document
        document.current_version_id = initial.id
        db.commit()

    barrier = threading.Barrier(2)
    numbers: list[int] = []
    failures: list[BaseException] = []
    result_lock = threading.Lock()

    def create_next(delay: float) -> None:
        try:
            barrier.wait(timeout=5)
            with postgres_factory() as db:
                document = db.scalar(
                    select(Document).where(Document.id == document_id).with_for_update()
                )
                assert document
                number = (
                    db.scalar(
                        select(func.max(DocumentVersion.version_number)).where(
                            DocumentVersion.document_id == document_id
                        )
                    )
                    or 0
                ) + 1
                time.sleep(delay)
                version = _version(
                    organization_id=organization_id,
                    document_id=document_id,
                    user_id=user_id,
                    number=number,
                )
                db.add(version)
                db.flush()
                document.current_version_id = version.id
                db.commit()
                with result_lock:
                    numbers.append(number)
        except BaseException as exc:  # pragma: no cover - failure is asserted below
            with result_lock:
                failures.append(exc)

    first = threading.Thread(target=create_next, args=(0.2,))
    second = threading.Thread(target=create_next, args=(0.0,))
    first.start()
    second.start()
    first.join(timeout=10)
    second.join(timeout=10)
    assert not failures
    assert sorted(numbers) == [2, 3]


def test_database_allows_only_one_active_owner(
    postgres_factory: sessionmaker[Session],
) -> None:
    _, organization_id, _ = _seed_document(postgres_factory)
    suffix = uuid.uuid4().hex
    second_user_id = uuid.uuid4()
    with postgres_factory() as db:
        db.add(
            User(
                id=second_user_id,
                primary_email=f"owner-{suffix}@example.com",
                normalized_email=f"owner-{suffix}@example.com",
                display_name="Second Owner",
            )
        )
        db.flush()
        db.add(
            OrganizationMembership(
                organization_id=organization_id,
                user_id=second_user_id,
                role=OrganizationRole.OWNER,
                status=MembershipStatus.ACTIVE,
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
