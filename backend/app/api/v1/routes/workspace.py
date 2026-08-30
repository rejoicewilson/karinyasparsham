from collections import defaultdict
from decimal import Decimal

import httpx
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.responses import success
from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import CurrentActor, get_current_actor
from app.models.domain import (
    AgentTalukAssignment,
    AuditLog,
    BankAccount,
    CaseObligation,
    CollectionTransaction,
    DeathCase,
    DepositBatch,
    DepositItem,
    Member,
    NotificationEvent,
    NotificationRecipient,
    PermanentMembershipAccount,
    Profile,
    Taluk,
    UserRole,
)
from app.services.rules import payment_status
from app.services.supabase_admin import service_headers


router = APIRouter()
ZERO = Decimal("0")
settings = get_settings()


async def signed_case_photo_urls(paths: list[str]) -> dict[str, str]:
    base = str(settings.SUPABASE_URL).rstrip("/")
    urls: dict[str, str] = {}
    async with httpx.AsyncClient(timeout=15) as client:
        for path in set(paths):
            try:
                response = await client.post(
                    f"{base}/storage/v1/object/sign/death-case-photos/{path}",
                    headers=service_headers(),
                    json={"expiresIn": 3600},
                )
            except httpx.HTTPError:
                continue
            if response.status_code != 200:
                continue
            signed_path = response.json().get("signedURL")
            if signed_path:
                if signed_path.startswith("http"):
                    urls[path] = signed_path
                elif signed_path.startswith("/storage/v1/"):
                    urls[path] = f"{base}{signed_path}"
                else:
                    urls[path] = f"{base}/storage/v1/{signed_path.lstrip('/')}"
    return urls


async def case_rows(db: AsyncSession) -> list[dict]:
    identity_rows = (
        await db.execute(
            select(DeathCase, Profile.full_name, Taluk.name)
            .join(Member, Member.id == DeathCase.deceased_member_id)
            .join(Profile, Profile.id == Member.profile_id)
            .join(Taluk, Taluk.id == Member.taluk_id)
            .order_by(DeathCase.created_at.desc())
        )
    ).all()
    photo_urls = await signed_case_photo_urls(
        [item.photo_object_path for item, _, _ in identity_rows if item.photo_object_path]
    )
    obligations = (await db.scalars(select(CaseObligation))).all()
    taluk_ids = {obligation.taluk_id_snapshot for obligation in obligations}
    taluk_names = dict((await db.execute(
        select(Taluk.id, Taluk.name).where(Taluk.id.in_(taluk_ids))
    )).all()) if taluk_ids else {}
    totals: dict = defaultdict(lambda: {"required": ZERO, "collected": ZERO, "verified": ZERO})
    by_taluk: dict = defaultdict(
        lambda: defaultdict(lambda: {"required": ZERO, "collected": ZERO, "verified": ZERO})
    )
    for obligation in obligations:
        case_total = totals[obligation.death_case_id]
        taluk_total = by_taluk[obligation.death_case_id][obligation.taluk_id_snapshot]
        for target in (case_total, taluk_total):
            target["required"] += obligation.required_amount
            target["collected"] += obligation.collected_amount
            target["verified"] += obligation.verified_amount
    return [
        {
            "id": item.id,
            "case_number": item.case_number,
            "deceased_name": deceased_name,
            "taluk_name": taluk_name,
            "death_date": item.death_date,
            "created_at": item.created_at,
            "contribution_amount": item.contribution_amount,
            "required_amount": totals[item.id]["required"],
            "collected_amount": totals[item.id]["collected"],
            "verified_amount": totals[item.id]["verified"],
            "taluk_progress": [
                {"id": taluk_id, "name": taluk_names.get(taluk_id, "Unknown taluk"), **amounts}
                for taluk_id, amounts in by_taluk[item.id].items()
            ],
            "status": item.status,
            "details": item.details,
            "photo_url": photo_urls.get(item.photo_object_path),
        }
        for item, deceased_name, taluk_name in identity_rows
    ]


async def collection_rows(db: AsyncSession, actor: CurrentActor, member_id=None) -> list[dict]:
    query = (
        select(CollectionTransaction, Profile.full_name, DeathCase.id, DeathCase.title)
        .join(Member, Member.id == CollectionTransaction.member_id)
        .join(Profile, Profile.id == Member.profile_id)
        .outerjoin(CaseObligation, CaseObligation.id == CollectionTransaction.case_obligation_id)
        .outerjoin(DeathCase, DeathCase.id == CaseObligation.death_case_id)
        .order_by(CollectionTransaction.collected_at.desc())
    )
    if actor.role == UserRole.AGENT:
        query = query.where(CollectionTransaction.agent_profile_id == actor.profile_id)
    elif actor.role == UserRole.MEMBER:
        query = query.where(CollectionTransaction.member_id == member_id)
    rows = (await db.execute(query.limit(250))).all()
    collector_ids = {item.agent_profile_id for item, _, _, _ in rows}
    collectors = {
        profile.id: profile.full_name
        for profile in (await db.scalars(select(Profile).where(Profile.id.in_(collector_ids)))).all()
    } if collector_ids else {}
    return [
        {
            "id": item.id,
            "receipt_number": item.receipt_number,
            "member_id": item.member_id,
            "member_name": member_name,
            "collector_name": collectors.get(item.agent_profile_id, "Collection agent"),
            "case_id": case_id,
            "case_obligation_id": item.case_obligation_id,
            "permanent_account_id": item.permanent_account_id,
            "label": case_title or "Permanent membership",
            "collection_type": item.collection_type,
            "amount": item.amount,
            "method": item.method,
            "collected_at": item.collected_at,
            "status": item.status,
        }
        for item, member_name, case_id, case_title in rows
    ]


async def deposit_rows(db: AsyncSession, actor: CurrentActor) -> list[dict]:
    query = (
        select(DepositBatch, Profile.full_name, Profile.phone, Taluk.name)
        .join(Profile, Profile.id == DepositBatch.agent_profile_id)
        .join(Taluk, Taluk.id == DepositBatch.taluk_id)
        .order_by(DepositBatch.created_at.desc())
    )
    if actor.role == UserRole.AGENT:
        query = query.where(DepositBatch.agent_profile_id == actor.profile_id)
    batches = (await db.execute(query.limit(150))).all()
    batch_ids = [batch.id for batch, _, _, _ in batches]
    items = []
    if batch_ids:
        items = (
            await db.scalars(
                select(DepositItem).where(
                    DepositItem.deposit_batch_id.in_(batch_ids),
                    DepositItem.released_at.is_(None),
                )
            )
        ).all()
    collection_ids: dict = defaultdict(list)
    for item in items:
        collection_ids[item.deposit_batch_id].append(item.collection_transaction_id)
    return [
        {
            "id": batch.id,
            "deposit_number": batch.deposit_number,
            "agent_name": agent_name,
            "agent_phone": agent_phone,
            "taluk_name": taluk_name,
            "bank_name": batch.bank_snapshot.get("bank_name", "Assigned bank"),
            "bank_last4": batch.bank_snapshot.get("account_number_last4", ""),
            "calculated_total": batch.calculated_total,
            "declared_deposit_amount": batch.declared_deposit_amount,
            "submitted_at": batch.submitted_at or batch.created_at,
            "status": batch.status,
            "collection_ids": collection_ids[batch.id],
            "bank_reference": batch.bank_reference,
            "rejection_reason": batch.rejection_reason,
            "version": batch.version,
        }
        for batch, agent_name, agent_phone, taluk_name in batches
    ]


async def member_rows(db: AsyncSession, actor: CurrentActor, taluk_id=None) -> list[dict]:
    query = (
        select(Member, Profile, Taluk, PermanentMembershipAccount)
        .join(Profile, Profile.id == Member.profile_id)
        .join(Taluk, Taluk.id == Member.taluk_id)
        .outerjoin(PermanentMembershipAccount, PermanentMembershipAccount.member_id == Member.id)
        .order_by(Member.member_code)
    )
    if actor.role == UserRole.AGENT:
        query = query.where(Member.taluk_id == taluk_id)
    elif actor.role == UserRole.MEMBER:
        query = query.where(Member.profile_id == actor.profile_id)
    rows = (await db.execute(query)).all()
    member_ids = [member.id for member, _, _, _ in rows]
    obligations = []
    if member_ids:
        obligations = (
            await db.execute(
                select(CaseObligation, DeathCase)
                .join(DeathCase, DeathCase.id == CaseObligation.death_case_id)
                .where(CaseObligation.member_id.in_(member_ids))
                .order_by(DeathCase.created_at.desc())
            )
        ).all()
    by_member: dict = defaultdict(list)
    for obligation, case in obligations:
        if actor.role == UserRole.AGENT and obligation.responsible_agent_id != actor.profile_id:
            continue
        by_member[obligation.member_id].append({
            "id": obligation.id,
            "case_id": case.id,
            "case_number": case.case_number,
            "label": case.title,
            "required_amount": obligation.required_amount,
            "collected_amount": obligation.collected_amount,
            "verified_amount": obligation.verified_amount,
            "available_amount": obligation.required_amount - obligation.collected_amount,
        })
    return [
        {
            "id": member.id,
            "profile_id": profile.id,
            "member_code": member.member_code,
            "full_name": profile.full_name,
            "phone": profile.phone,
            "taluk_id": member.taluk_id,
            "taluk_name": taluk.name,
            "joined_on": member.joined_on,
            "version": member.version,
            "profile_version": profile.version,
            "membership_type": member.membership_type,
            "account_status": profile.account_status,
            "pending_amount": sum((item["available_amount"] for item in by_member[member.id]), ZERO),
            "permanent_account_id": permanent.id if permanent else None,
            "permanent_target": permanent.target_amount if permanent else ZERO,
            "permanent_collected": permanent.collected_amount if permanent else ZERO,
            "permanent_verified": permanent.verified_amount if permanent else ZERO,
            "obligations": by_member[member.id],
        }
        for member, profile, taluk, permanent in rows
    ]


@router.get("/workspace")
async def workspace(
    request: Request,
    actor: CurrentActor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    profile_data = {
        "id": actor.profile_id,
        "login_id": actor.login_id,
        "full_name": actor.full_name,
        "role": actor.role,
    }
    data = {
        "profile": profile_data,
        "cases": await case_rows(db),
        "members": [],
        "dues": [],
        "collections": [],
        "deposits": [],
        "taluks": [],
        "agents": [],
        "bank_accounts": [],
        "notifications": [],
        "case_whatsapp_tracking": [],
    }

    recipient_rows = (
        await db.execute(
            select(NotificationRecipient, NotificationEvent)
            .join(NotificationEvent, NotificationEvent.id == NotificationRecipient.event_id)
            .where(NotificationRecipient.profile_id == actor.profile_id)
            .order_by(NotificationRecipient.created_at.desc())
            .limit(50)
        )
    ).all()
    data["notifications"] = [
        {
            "id": recipient.id,
            "title": event.title,
            "body": event.body_template,
            "created_at": recipient.created_at,
            "read": recipient.read_at is not None,
            "type": event.type,
        }
        for recipient, event in recipient_rows
    ]

    if actor.role == UserRole.MEMBER:
        member = await db.scalar(select(Member).where(Member.profile_id == actor.profile_id))
        if member is None:
            raise AppError("FORBIDDEN_RESOURCE", "Member profile was not found.", 404)
        member_data = (await member_rows(db, actor))[0]
        profile_data["member_code"] = member_data["member_code"]
        profile_data["taluk_name"] = member_data["taluk_name"]
        assignment = await db.scalar(select(AgentTalukAssignment).where(
            AgentTalukAssignment.taluk_id == member.taluk_id,
            AgentTalukAssignment.ends_at.is_(None),
        ))
        agent = await db.get(Profile, assignment.agent_profile_id) if assignment else None
        profile_data["agent"] = {
            "id": agent.id, "full_name": agent.full_name, "phone": agent.phone,
        } if agent else None
        data["members"] = [member_data]
        data["dues"] = [
            {
                **item,
                "obligation_id": item["id"],
                "amount_still_to_collect": item["available_amount"],
                "amount_awaiting_verification": item["collected_amount"] - item["verified_amount"],
                "display_status": payment_status(
                    item["required_amount"], item["collected_amount"], item["verified_amount"]
                ),
            }
            for item in member_data["obligations"]
        ]
        data["collections"] = await collection_rows(db, actor, member.id)
    elif actor.role == UserRole.AGENT:
        assignment = await db.scalar(
            select(AgentTalukAssignment).where(
                AgentTalukAssignment.agent_profile_id == actor.profile_id,
                AgentTalukAssignment.ends_at.is_(None),
            )
        )
        if assignment:
            taluk = await db.get(Taluk, assignment.taluk_id)
            bank = await db.scalar(
                select(BankAccount).where(
                    BankAccount.taluk_id == assignment.taluk_id,
                    BankAccount.ends_at.is_(None),
                )
            )
            profile_data["taluk_name"] = taluk.name if taluk else None
            profile_data["bank"] = {
                "bank_name": bank.bank_name,
                "branch_name": bank.branch_name,
                "last4": bank.account_number_last4,
                "ifsc_code": bank.ifsc_code,
            } if bank else None
            data["members"] = await member_rows(db, actor, assignment.taluk_id)
        data["collections"] = await collection_rows(db, actor)
        data["deposits"] = await deposit_rows(db, actor)
    else:
        data["members"] = await member_rows(db, actor)
        data["collections"] = await collection_rows(db, actor)
        data["deposits"] = await deposit_rows(db, actor)
        taluks = (await db.scalars(select(Taluk).order_by(Taluk.name))).all()
        assignments = (
            await db.execute(
                select(AgentTalukAssignment, Profile)
                .join(Profile, Profile.id == AgentTalukAssignment.agent_profile_id)
                .where(AgentTalukAssignment.ends_at.is_(None))
            )
        ).all()
        agent_profiles = (
            await db.scalars(select(Profile).where(Profile.role == UserRole.AGENT).order_by(Profile.full_name))
        ).all()
        assignment_by_agent = {assignment.agent_profile_id: assignment for assignment, _ in assignments}
        agent_by_taluk = {assignment.taluk_id: profile for assignment, profile in assignments}
        banks = (
            await db.scalars(select(BankAccount).where(BankAccount.ends_at.is_(None)))
        ).all()
        bank_by_taluk = {bank.taluk_id: bank for bank in banks}
        data["taluks"] = [
            {
                "id": item.id, "code": item.code, "name": item.name, "district": item.district,
                "is_active": item.is_active, "version": item.version,
                "agent_profile_id": agent_by_taluk[item.id].id if item.id in agent_by_taluk else None,
                "agent_name": agent_by_taluk[item.id].full_name if item.id in agent_by_taluk else None,
                "bank_account_id": bank_by_taluk[item.id].id if item.id in bank_by_taluk else None,
                "bank_name": bank_by_taluk[item.id].bank_name if item.id in bank_by_taluk else None,
                "bank_last4": bank_by_taluk[item.id].account_number_last4 if item.id in bank_by_taluk else None,
                "bank_branch_name": bank_by_taluk[item.id].branch_name if item.id in bank_by_taluk else None,
                "bank_account_holder_name": bank_by_taluk[item.id].account_holder_name if item.id in bank_by_taluk else None,
                "bank_ifsc_code": bank_by_taluk[item.id].ifsc_code if item.id in bank_by_taluk else None,
                "member_count": sum(1 for member in data["members"] if member["taluk_id"] == item.id),
            }
            for item in taluks
        ]
        data["agents"] = [
            {
                "id": profile.id, "full_name": profile.full_name, "login_id": profile.login_id,
                "phone": profile.phone, "account_status": profile.account_status,
                "version": profile.version,
                "taluk_id": assignment_by_agent[profile.id].taluk_id if profile.id in assignment_by_agent else None,
                "taluk_name": next((item.name for item in taluks if profile.id in assignment_by_agent
                                     and item.id == assignment_by_agent[profile.id].taluk_id), None),
            }
            for profile in agent_profiles
        ]
        data["bank_accounts"] = [
            {
                "id": bank.id, "taluk_id": bank.taluk_id,
                "agent_profile_id": bank.agent_profile_id, "bank_name": bank.bank_name,
                "branch_name": bank.branch_name, "account_holder_name": bank.account_holder_name,
                "last4": bank.account_number_last4,
                "ifsc_code": bank.ifsc_code,
            }
            for bank in banks
        ]
        case_ids = [item["id"] for item in data["cases"]]
        if case_ids:
            tracking_logs = (
                await db.scalars(
                    select(AuditLog)
                    .where(
                        AuditLog.entity_type == "death_case_whatsapp",
                        AuditLog.entity_id.in_(case_ids),
                    )
                    .order_by(AuditLog.created_at)
                )
            ).all()
            latest_tracking: dict[tuple, AuditLog] = {}
            for log in tracking_logs:
                member_id = (log.after_data or {}).get("member_id")
                if member_id:
                    latest_tracking[(log.entity_id, member_id)] = log
            data["case_whatsapp_tracking"] = [
                {
                    "case_id": case_id,
                    "member_id": member_id,
                    "status": log.after_data.get("status", "NOT_SENT"),
                    "updated_at": log.created_at,
                    "updated_by": log.actor_profile_id,
                }
                for (case_id, member_id), log in latest_tracking.items()
            ]

    return success(request, data)
