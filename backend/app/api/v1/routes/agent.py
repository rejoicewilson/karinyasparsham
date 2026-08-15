import uuid

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.responses import success
from app.core.database import get_db
from app.core.security import CurrentActor, require_role
from app.models.domain import CollectionTransaction, DepositBatch, UserRole
from app.schemas.api import CollectionCreate, DepositCreate, DepositSubmit
from app.services.ledger import create_deposit, record_collection, submit_deposit


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
    actor: CurrentActor = Depends(agent_only),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.scalars(
            select(CollectionTransaction)
            .where(CollectionTransaction.agent_profile_id == actor.profile_id)
            .order_by(CollectionTransaction.collected_at.desc())
            .limit(100)
        )
    ).all()
    return success(request, rows)


@router.post("/collections", status_code=status.HTTP_201_CREATED)
async def create_collection(
    payload: CollectionCreate,
    request: Request,
    actor: CurrentActor = Depends(agent_only),
    db: AsyncSession = Depends(get_db),
):
    collection = await record_collection(db, actor, payload, request_id(request))
    return success(request, collection)


@router.get("/deposits")
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
async def create_deposit_batch(
    payload: DepositCreate,
    request: Request,
    actor: CurrentActor = Depends(agent_only),
    db: AsyncSession = Depends(get_db),
):
    batch = await create_deposit(db, actor, payload, request_id(request))
    return success(request, batch)


@router.post("/deposits/{batch_id}/submit")
async def submit_deposit_batch(
    batch_id: uuid.UUID,
    payload: DepositSubmit,
    request: Request,
    actor: CurrentActor = Depends(agent_only),
    db: AsyncSession = Depends(get_db),
):
    batch = await submit_deposit(
        db, actor, batch_id, payload.expected_version, request_id(request)
    )
    return success(request, batch)
