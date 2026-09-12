from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.api.responses import success
from app.core.security import CurrentActor, get_current_actor
from app.models.domain import DeathCase, Member, Taluk


router = APIRouter()


@router.get("/app-config")
async def app_config(request: Request):
    return success(request, {
        "app_name": "Karunya Sparsham",
        "version": "1.0.0",
        "currency": "INR",
        "timezone": "Asia/Kolkata",
        "financial_writes_require_online": True,
    })


@router.get("/me")
async def me(request: Request, actor: CurrentActor = Depends(get_current_actor)):
    return success(request, {
        "id": actor.profile_id,
        "login_id": actor.login_id,
        "full_name": actor.full_name,
        "role": actor.role,
    })


@router.get("/death-cases")
async def death_cases(
    request: Request,
    limit: int = Query(default=25, ge=1, le=100),
    _: CurrentActor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.scalars(
            select(DeathCase)
            .join(Member, Member.id == DeathCase.deceased_member_id)
            .join(Taluk, Taluk.id == Member.taluk_id)
            .where(Taluk.is_active.is_(True))
            .order_by(DeathCase.created_at.desc())
            .limit(limit)
        )
    ).all()
    return success(request, rows)
