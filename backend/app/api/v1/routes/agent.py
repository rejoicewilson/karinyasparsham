import uuid

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.responses import success
from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import CurrentActor, require_role
from app.models.domain import (
    CaseObligation,
    CollectionStatus,
    CollectionTransaction,
    CollectionType,
    DeathCase,
    DepositBatch,
    Member,
    Profile,
    UserRole,
)
from app.schemas.api import CollectionCreate, DepositCreate, DepositSubmit


router = APIRouter()
agent_only = require_role(UserRole.AGENT)


def request_id(request: Request) -> uuid.UUID:
    try:
        return uuid.UUID(request.state.request_id)
    except ValueError:
        return uuid.uuid5(uuid.NAMESPACE_URL, request.state.request_id)


@router.get("/collections")
async def list_collections(
    request: Request,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    collection_type: CollectionType | None = Query(default=None),
    query: str | None = Query(default=None, max_length=120),
    actor: CurrentActor = Depends(agent_only),
    db: AsyncSession = Depends(get_db),
):
    filters = [
        CollectionTransaction.agent_profile_id == actor.profile_id,
        CollectionTransaction.status != CollectionStatus.VOIDED,
    ]
    if collection_type is not None:
        filters.append(CollectionTransaction.collection_type == collection_type)
    term = query.strip() if query else ""
    if term:
        pattern = f"%{term}%"
        filters.append(or_(
            Profile.full_name.ilike(pattern),
            DeathCase.title.ilike(pattern),
            CollectionTransaction.receipt_number.ilike(pattern),
        ))

    base = (
        select(CollectionTransaction, Profile.full_name, DeathCase.id, DeathCase.title)
        .join(Member, Member.id == CollectionTransaction.member_id)
        .join(Profile, Profile.id == Member.profile_id)
        .outerjoin(CaseObligation, CaseObligation.id == CollectionTransaction.case_obligation_id)
        .outerjoin(DeathCase, DeathCase.id == CaseObligation.death_case_id)
        .where(*filters)
    )
    filtered = base.order_by(None).subquery()
    total = int(await db.scalar(select(func.count()).select_from(filtered)) or 0)
    verified_amount = await db.scalar(
        select(func.coalesce(func.sum(filtered.c.amount), 0))
        .where(filtered.c.status == CollectionStatus.VERIFIED)
    )
    rows = (
        await db.execute(
            base.order_by(CollectionTransaction.collected_at.desc(), CollectionTransaction.id)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    items = [
        {
            "id": item.id,
            "receipt_number": item.receipt_number,
            "member_id": item.member_id,
            "member_name": member_name,
            "case_id": case_id,
            "label": case_title or "Permanent membership",
            "collection_type": item.collection_type,
            "amount": item.amount,
            "method": item.method,
            "collected_at": item.collected_at,
            "status": item.status,
        }
        for item, member_name, case_id, case_title in rows
    ]
    return success(request, {
        "items": items,
        "total": total,
        "verified_amount": verified_amount,
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(items) < total,
    })


@router.post("/collections", status_code=status.HTTP_201_CREATED)
async def create_collection(
    payload: CollectionCreate,
    request: Request,
    actor: CurrentActor = Depends(agent_only),
    db: AsyncSession = Depends(get_db),
):
    raise AppError("AGENT_READ_ONLY", "Agent accounts are view-only. An administrator records collections.", 403)


@router.get("/deposits")
@router.get("/handovers")
async def list_deposits(
    request: Request,
    actor: CurrentActor = Depends(agent_only),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.scalars(
            select(DepositBatch)
            .where(DepositBatch.agent_profile_id == actor.profile_id)
            .order_by(DepositBatch.created_at.desc())
            .limit(100)
        )
    ).all()
    return success(request, rows)


@router.post("/deposits", status_code=status.HTTP_201_CREATED)
@router.post("/handovers", status_code=status.HTTP_201_CREATED)
async def create_deposit_batch(
    payload: DepositCreate,
    request: Request,
    actor: CurrentActor = Depends(agent_only),
    db: AsyncSession = Depends(get_db),
):
    raise AppError("AGENT_READ_ONLY", "Agent accounts are view-only. Handovers are no longer submitted by agents.", 403)


@router.post("/deposits/{batch_id}/submit")
@router.post("/handovers/{batch_id}/submit")
async def submit_deposit_batch(
    batch_id: uuid.UUID,
    payload: DepositSubmit,
    request: Request,
    actor: CurrentActor = Depends(agent_only),
    db: AsyncSession = Depends(get_db),
):
    raise AppError("AGENT_READ_ONLY", "Agent accounts are view-only. Handovers are no longer submitted by agents.", 403)
