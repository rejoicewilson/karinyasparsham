from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.api.responses import success
from app.core.errors import AppError
from app.core.security import CurrentActor, require_role
from app.models.domain import CaseObligation, DeathCase, Member, UserRole
from app.services.rules import payment_status


router = APIRouter()
member_only = require_role(UserRole.MEMBER)


@router.get("/dues")
async def own_dues(
    request: Request,
    actor: CurrentActor = Depends(member_only), db: AsyncSession = Depends(get_db)
):
    member = await db.scalar(select(Member).where(Member.profile_id == actor.profile_id))
    if member is None:
        raise AppError("FORBIDDEN_RESOURCE", "Member profile was not found.", 404)
    result = await db.execute(
        select(CaseObligation, DeathCase)
        .join(DeathCase, DeathCase.id == CaseObligation.death_case_id)
        .where(CaseObligation.member_id == member.id)
        .order_by(DeathCase.created_at.desc())
    )
    data = [
        {
            "obligation_id": obligation.id,
            "case_id": case.id,
            "case_number": case.case_number,
            "title": case.title,
            "required_amount": obligation.required_amount,
            "collected_amount": obligation.collected_amount,
            "verified_amount": obligation.verified_amount,
            "amount_still_to_collect": obligation.required_amount - obligation.collected_amount,
            "amount_awaiting_verification": obligation.collected_amount - obligation.verified_amount,
            "display_status": payment_status(
                obligation.required_amount, obligation.collected_amount, obligation.verified_amount
            ),
        }
        for obligation, case in result.all()
    ]
    return success(request, data)
