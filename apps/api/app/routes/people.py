import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.audit import record_audit
from app.dependencies import Csrf, Db, OrgContext
from app.models import (
    EmployeeProfile,
    MembershipStatus,
    OrganizationMembership,
    Team,
    TeamMembership,
)
from app.policy import Capability, require_capability
from app.repositories import PeopleRepository
from app.schemas import (
    EmployeeProfileCreate,
    EmployeeProfileRead,
    EmployeeProfileUpdate,
    TeamCreate,
    TeamMemberCreate,
    TeamRead,
)
from app.security import normalize_email, slugify

router = APIRouter(tags=["people"])


def _profile(db: Db, organization_id: uuid.UUID, profile_id: uuid.UUID) -> EmployeeProfile:
    result = PeopleRepository(db, organization_id).get_profile(profile_id)
    if not result:
        raise HTTPException(status_code=404, detail="Employee profile not found")
    return result


def _validate_links(
    db: Db,
    organization_id: uuid.UUID,
    user_id: uuid.UUID | None,
    manager_id: uuid.UUID | None,
) -> None:
    if user_id and not db.scalar(
        select(OrganizationMembership.id).where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.status == MembershipStatus.ACTIVE,
        )
    ):
        raise HTTPException(
            status_code=422, detail="Linked user is not an active organization member"
        )
    if manager_id and not db.scalar(
        select(EmployeeProfile.id).where(
            EmployeeProfile.organization_id == organization_id,
            EmployeeProfile.id == manager_id,
        )
    ):
        raise HTTPException(status_code=422, detail="Manager profile is not in this organization")


@router.get("/people", response_model=list[EmployeeProfileRead])
def list_people(db: Db, context: OrgContext) -> list[EmployeeProfile]:
    return list(
        db.scalars(
            select(EmployeeProfile)
            .where(EmployeeProfile.organization_id == context.organization.id)
            .order_by(EmployeeProfile.display_name)
        )
    )


@router.post("/people", response_model=EmployeeProfileRead, status_code=201)
def create_profile(
    payload: EmployeeProfileCreate, db: Db, context: OrgContext, csrf: Csrf
) -> EmployeeProfile:
    require_capability(context, Capability.MANAGE_PEOPLE)
    _validate_links(db, context.organization.id, payload.user_id, payload.manager_profile_id)
    profile = EmployeeProfile(
        id=uuid.uuid4(),
        organization_id=context.organization.id,
        user_id=payload.user_id,
        display_name=payload.display_name.strip(),
        work_email=normalize_email(str(payload.work_email)) if payload.work_email else None,
        job_title=payload.job_title,
        department=payload.department,
        seniority=payload.seniority,
        manager_profile_id=payload.manager_profile_id,
        start_date=payload.start_date,
        timezone=payload.timezone,
        locale=payload.locale,
        profile_metadata=payload.metadata,
    )
    db.add(profile)
    record_audit(
        db,
        action="employee.created",
        resource_type="employee_profile",
        resource_id=profile.id,
        organization_id=context.organization.id,
        actor_user_id=context.user.id,
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="This user already has an employee profile"
        ) from exc
    return profile


@router.get("/people/{profile_id}", response_model=EmployeeProfileRead)
def get_profile(profile_id: uuid.UUID, db: Db, context: OrgContext) -> EmployeeProfile:
    return _profile(db, context.organization.id, profile_id)


@router.patch("/people/{profile_id}", response_model=EmployeeProfileRead)
def update_profile(
    profile_id: uuid.UUID, payload: EmployeeProfileUpdate, db: Db, context: OrgContext, csrf: Csrf
) -> EmployeeProfile:
    require_capability(context, Capability.MANAGE_PEOPLE)
    profile = _profile(db, context.organization.id, profile_id)
    changes = payload.model_dump(exclude_unset=True)
    if "manager_profile_id" in changes:
        if changes["manager_profile_id"] == profile.id:
            raise HTTPException(status_code=422, detail="An employee cannot manage themselves")
        _validate_links(db, context.organization.id, None, changes["manager_profile_id"])
    if "work_email" in changes and changes["work_email"]:
        changes["work_email"] = normalize_email(str(changes["work_email"]))
    if "metadata" in changes:
        changes["profile_metadata"] = changes.pop("metadata")
    for name, value in changes.items():
        setattr(profile, name, value)
    record_audit(
        db,
        action="employee.updated",
        resource_type="employee_profile",
        resource_id=profile.id,
        organization_id=context.organization.id,
        actor_user_id=context.user.id,
    )
    db.commit()
    return profile


@router.get("/teams", response_model=list[TeamRead])
def list_teams(db: Db, context: OrgContext) -> list[Team]:
    return list(
        db.scalars(
            select(Team).where(Team.organization_id == context.organization.id).order_by(Team.name)
        )
    )


@router.post("/teams", response_model=TeamRead, status_code=201)
def create_team(payload: TeamCreate, db: Db, context: OrgContext, csrf: Csrf) -> Team:
    require_capability(context, Capability.MANAGE_PEOPLE)
    team = Team(
        id=uuid.uuid4(),
        organization_id=context.organization.id,
        name=payload.name.strip(),
        slug=slugify(payload.slug or payload.name),
        description=payload.description,
    )
    db.add(team)
    record_audit(
        db,
        action="team.created",
        resource_type="team",
        resource_id=team.id,
        organization_id=context.organization.id,
        actor_user_id=context.user.id,
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A team with this slug already exists") from exc
    return team


def _team(db: Db, organization_id: uuid.UUID, team_id: uuid.UUID) -> Team:
    team = PeopleRepository(db, organization_id).get_team(team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


@router.get("/teams/{team_id}/members", response_model=list[EmployeeProfileRead])
def list_team_members(team_id: uuid.UUID, db: Db, context: OrgContext) -> list[EmployeeProfile]:
    _team(db, context.organization.id, team_id)
    return list(
        db.scalars(
            select(EmployeeProfile)
            .join(
                TeamMembership,
                (TeamMembership.organization_id == EmployeeProfile.organization_id)
                & (TeamMembership.employee_profile_id == EmployeeProfile.id),
            )
            .where(
                TeamMembership.organization_id == context.organization.id,
                TeamMembership.team_id == team_id,
            )
            .order_by(EmployeeProfile.display_name)
        )
    )


@router.post("/teams/{team_id}/members", status_code=204)
def add_team_member(
    team_id: uuid.UUID, payload: TeamMemberCreate, db: Db, context: OrgContext, csrf: Csrf
) -> None:
    require_capability(context, Capability.MANAGE_PEOPLE)
    _team(db, context.organization.id, team_id)
    _profile(db, context.organization.id, payload.employee_profile_id)
    existing = db.scalar(
        select(TeamMembership.id).where(
            TeamMembership.team_id == team_id,
            TeamMembership.employee_profile_id == payload.employee_profile_id,
        )
    )
    if not existing:
        db.add(
            TeamMembership(
                organization_id=context.organization.id,
                team_id=team_id,
                employee_profile_id=payload.employee_profile_id,
            )
        )
        record_audit(
            db,
            action="team.member_added",
            resource_type="team",
            resource_id=team_id,
            organization_id=context.organization.id,
            actor_user_id=context.user.id,
            metadata={"employee_profile_id": str(payload.employee_profile_id)},
        )
        db.commit()


@router.delete("/teams/{team_id}/members/{profile_id}", status_code=204)
def remove_team_member(
    team_id: uuid.UUID, profile_id: uuid.UUID, db: Db, context: OrgContext, csrf: Csrf
) -> None:
    require_capability(context, Capability.MANAGE_PEOPLE)
    membership = db.scalar(
        select(TeamMembership).where(
            TeamMembership.organization_id == context.organization.id,
            TeamMembership.team_id == team_id,
            TeamMembership.employee_profile_id == profile_id,
        )
    )
    if not membership:
        raise HTTPException(status_code=404, detail="Team membership not found")
    db.delete(membership)
    record_audit(
        db,
        action="team.member_removed",
        resource_type="team",
        resource_id=team_id,
        organization_id=context.organization.id,
        actor_user_id=context.user.id,
        metadata={"employee_profile_id": str(profile_id)},
    )
    db.commit()
