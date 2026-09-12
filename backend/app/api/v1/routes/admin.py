import uuid
from datetime import datetime, timezone
import httpx
from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, File, Request, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.responses import success
from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import CurrentActor, require_role
from app.models.domain import (
    AccountStatus, AgentTalukAssignment, AuditLog, BankAccount, CaseObligation, DeathCase,
    DepositBatch, DepositStatus, Member, MonthlyCaseCounter, Profile, Taluk, UserRole,
)
from app.schemas.api import (
    AgentCreate, AgentUpdate, BankAccountCreate, BankAccountReplace, DeathCaseCreate, DepositApprove, DepositReject,
    DeathCaseWhatsAppStatusUpdate, MemberCreate, MemberUpdate, TalukCreate, TalukUpdate,
)
from app.services.ledger import publish_death_case, review_deposit
from app.services.supabase_admin import create_auth_user, delete_auth_user, service_headers
from app.services.rules import default_case_amount, sequence_month


router = APIRouter()
admin_only = require_role(UserRole.ADMIN)
settings = get_settings()
bank_cipher = Fernet(settings.BANK_FIELD_ENCRYPTION_KEY.encode())


def request_id(request: Request) -> uuid.UUID:
    try:
        return uuid.UUID(request.state.request_id)
    except ValueError:
        return uuid.uuid5(uuid.NAMESPACE_URL, request.state.request_id)


@router.get("/taluks")
async def list_taluks(
    request: Request,
    _: CurrentActor = Depends(admin_only), db: AsyncSession = Depends(get_db)
):
    return success(request, (
        await db.scalars(
            select(Taluk).where(Taluk.is_active.is_(True)).order_by(Taluk.name)
        )
    ).all())


@router.post("/taluks", status_code=status.HTTP_201_CREATED)
async def create_taluk(
    payload: TalukCreate,
    request: Request,
    _: CurrentActor = Depends(admin_only),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.scalar(
        select(Taluk.id).where((Taluk.code == payload.code) | (Taluk.name == payload.name))
    )
    if existing:
        raise AppError("VERSION_CONFLICT", "Taluk code or name already exists.", 409)
    taluk = Taluk(code=payload.code.upper(), name=payload.name.strip(), district=payload.district)
    db.add(taluk)
    await db.commit()
    await db.refresh(taluk)
    return success(request, taluk)


@router.patch("/taluks/{taluk_id}")
async def update_taluk(
    taluk_id: uuid.UUID, payload: TalukUpdate, request: Request,
    actor: CurrentActor = Depends(admin_only), db: AsyncSession = Depends(get_db),
):
    taluk = await db.scalar(select(Taluk).where(Taluk.id == taluk_id).with_for_update())
    if taluk is None:
        raise AppError("FORBIDDEN_RESOURCE", "Taluk was not found.", 404)
    if taluk.version != payload.expected_version:
        raise AppError("VERSION_CONFLICT", "Taluk was changed by another request. Reload and try again.", 409)
    duplicate = await db.scalar(select(Taluk.id).where(
        Taluk.id != taluk_id, (Taluk.code == payload.code) | (Taluk.name == payload.name)
    ))
    if duplicate:
        raise AppError("VERSION_CONFLICT", "Taluk code or name already exists.", 409)
    if not payload.is_active:
        has_assignment = await db.scalar(select(AgentTalukAssignment.id).where(
            AgentTalukAssignment.taluk_id == taluk_id, AgentTalukAssignment.ends_at.is_(None)
        ))
        has_members = await db.scalar(
            select(Member.id).join(Profile, Profile.id == Member.profile_id).where(
                Member.taluk_id == taluk_id, Profile.account_status == AccountStatus.ACTIVE
            ).limit(1)
        )
        has_bank = await db.scalar(select(BankAccount.id).where(
            BankAccount.taluk_id == taluk_id, BankAccount.ends_at.is_(None)
        ))
        if has_assignment or has_members or has_bank:
            raise AppError("VERSION_CONFLICT", "End active assignments and move or disable active members first.", 409)
    before = {"code": taluk.code, "name": taluk.name, "district": taluk.district, "is_active": taluk.is_active}
    taluk.code = payload.code.upper()
    taluk.name = payload.name.strip()
    taluk.district = payload.district.strip() if payload.district else None
    taluk.is_active = payload.is_active
    db.add(AuditLog(
        actor_profile_id=actor.profile_id, actor_role=actor.role, action="TALUK_UPDATED",
        entity_type="taluk", entity_id=taluk.id, before_data=before,
        after_data={"code": taluk.code, "name": taluk.name, "district": taluk.district,
                    "is_active": taluk.is_active, "reason": payload.reason},
        request_id=request_id(request),
    ))
    await db.commit()
    await db.refresh(taluk)
    return success(request, taluk)


@router.get("/agents")
async def list_agents(
    request: Request,
    _: CurrentActor = Depends(admin_only),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(Profile, AgentTalukAssignment)
            .outerjoin(
                AgentTalukAssignment,
                (AgentTalukAssignment.agent_profile_id == Profile.id)
                & (AgentTalukAssignment.ends_at.is_(None)),
            )
            .where(
                Profile.role == UserRole.AGENT,
                Profile.account_status == AccountStatus.ACTIVE,
            )
            .order_by(Profile.full_name)
        )
    ).all()
    return success(request, [
        {
            "id": profile.id, "login_id": profile.login_id, "full_name": profile.full_name,
            "phone": profile.phone, "account_status": profile.account_status,
            "taluk_id": assignment.taluk_id if assignment else None,
        }
        for profile, assignment in rows
    ])


@router.post("/agents", status_code=status.HTTP_201_CREATED)
async def create_agent(
    payload: AgentCreate,
    request: Request,
    actor: CurrentActor = Depends(admin_only),
    db: AsyncSession = Depends(get_db),
):
    if await db.scalar(select(Taluk.id).where(Taluk.id == payload.taluk_id, Taluk.is_active.is_(True))) is None:
        raise AppError("FORBIDDEN_RESOURCE", "Active taluk was not found.", 404)
    if await db.scalar(select(AgentTalukAssignment.id).where(AgentTalukAssignment.taluk_id == payload.taluk_id, AgentTalukAssignment.ends_at.is_(None))):
        raise AppError("VERSION_CONFLICT", "Taluk already has an active agent.", 409)
    auth_user_id, alias = await create_auth_user(
        payload.login_id, payload.temporary_password.get_secret_value(), payload.full_name, "AGENT"
    )
    try:
        profile = Profile(
            auth_user_id=auth_user_id, login_id=payload.login_id, auth_email_alias=alias,
            role=UserRole.AGENT, full_name=payload.full_name.strip(), phone=payload.phone,
            must_change_password=True, created_by=actor.profile_id,
        )
        db.add(profile)
        await db.flush()
        db.add(AgentTalukAssignment(
            agent_profile_id=profile.id, taluk_id=payload.taluk_id, created_by=actor.profile_id
        ))
        db.add(AuditLog(
            actor_profile_id=actor.profile_id, actor_role=actor.role, action="AGENT_CREATED",
            entity_type="profile", entity_id=profile.id, after_data={"login_id": payload.login_id, "taluk_id": str(payload.taluk_id)},
            request_id=request_id(request),
        ))
        await db.commit()
        await db.refresh(profile)
    except Exception:
        await db.rollback()
        await delete_auth_user(auth_user_id)
        raise
    return success(request, {"id": profile.id, "login_id": profile.login_id, "full_name": profile.full_name, "taluk_id": payload.taluk_id})


@router.patch("/agents/{agent_id}")
async def update_agent(
    agent_id: uuid.UUID, payload: AgentUpdate, request: Request,
    actor: CurrentActor = Depends(admin_only), db: AsyncSession = Depends(get_db),
):
    profile = await db.scalar(select(Profile).where(
        Profile.id == agent_id, Profile.role == UserRole.AGENT
    ).with_for_update())
    if profile is None:
        raise AppError("FORBIDDEN_RESOURCE", "Agent was not found.", 404)
    if profile.version != payload.expected_version:
        raise AppError("VERSION_CONFLICT", "Agent was changed by another request. Reload and try again.", 409)
    current = await db.scalar(select(AgentTalukAssignment).where(
        AgentTalukAssignment.agent_profile_id == agent_id,
        AgentTalukAssignment.ends_at.is_(None),
    ).with_for_update())
    current_taluk_id = current.taluk_id if current else None
    if payload.account_status != AccountStatus.ACTIVE and payload.taluk_id is not None:
        raise AppError("VALIDATION_ERROR", "Inactive or locked agents must be unassigned from a taluk.", 422)
    if payload.taluk_id != current_taluk_id and payload.taluk_id is not None:
        target = await db.scalar(select(Taluk).where(
            Taluk.id == payload.taluk_id, Taluk.is_active.is_(True)
        ))
        if target is None:
            raise AppError("FORBIDDEN_RESOURCE", "Active target taluk was not found.", 404)
        occupied = await db.scalar(select(AgentTalukAssignment.id).where(
            AgentTalukAssignment.taluk_id == payload.taluk_id,
            AgentTalukAssignment.ends_at.is_(None),
        ))
        if occupied:
            raise AppError("VERSION_CONFLICT", "Target taluk already has an active agent.", 409)
    before = {
        "full_name": profile.full_name, "phone": profile.phone,
        "account_status": profile.account_status.value,
        "taluk_id": str(current_taluk_id) if current_taluk_id else None,
    }
    ended_banks: list[BankAccount] = []
    if payload.taluk_id != current_taluk_id:
        changed_at = datetime.now(timezone.utc)
        if current:
            current.ends_at = changed_at
            active_bank = await db.scalar(select(BankAccount).where(
                BankAccount.taluk_id == current.taluk_id, BankAccount.ends_at.is_(None)
            ).with_for_update())
            if active_bank:
                active_bank.ends_at = changed_at
                ended_banks.append(active_bank)
        if payload.taluk_id is not None:
            target_bank = await db.scalar(select(BankAccount).where(
                BankAccount.taluk_id == payload.taluk_id, BankAccount.ends_at.is_(None)
            ).with_for_update())
            if target_bank:
                target_bank.ends_at = changed_at
                ended_banks.append(target_bank)
            db.add(AgentTalukAssignment(
                agent_profile_id=agent_id, taluk_id=payload.taluk_id, created_by=actor.profile_id
            ))
    profile.full_name = payload.full_name.strip()
    profile.phone = payload.phone.strip() if payload.phone else None
    profile.account_status = payload.account_status
    db.add(AuditLog(
        actor_profile_id=actor.profile_id, actor_role=actor.role, action="AGENT_UPDATED",
        entity_type="profile", entity_id=profile.id, before_data=before,
        after_data={"full_name": profile.full_name, "phone": profile.phone,
                    "account_status": profile.account_status.value,
                    "taluk_id": str(payload.taluk_id) if payload.taluk_id else None,
                    "reason": payload.reason},
        request_id=request_id(request),
    ))
    for ended_bank in ended_banks:
        db.add(AuditLog(
            actor_profile_id=actor.profile_id, actor_role=actor.role,
            action="BANK_ACCOUNT_ENDED_FOR_AGENT_CHANGE", entity_type="bank_account",
            entity_id=ended_bank.id,
            before_data={"bank_name": ended_bank.bank_name,
                         "account_number_last4": ended_bank.account_number_last4},
            after_data={"ends_at": ended_bank.ends_at.isoformat(), "reason": payload.reason},
            request_id=request_id(request),
        ))
    await db.commit()
    await db.refresh(profile)
    return success(request, {"id": profile.id, "version": profile.version,
                             "taluk_id": payload.taluk_id, "account_status": profile.account_status})


@router.get("/members")
async def list_members(
    request: Request,
    _: CurrentActor = Depends(admin_only),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(Member, Profile)
            .join(Profile, Profile.id == Member.profile_id)
            .join(Taluk, Taluk.id == Member.taluk_id)
            .where(Taluk.is_active.is_(True))
            .order_by(Member.member_code)
        )
    ).all()
    return success(request, [
        {
            "id": member.id, "member_code": member.member_code, "full_name": profile.full_name,
            "phone": profile.phone, "taluk_id": member.taluk_id,
            "membership_type": member.membership_type, "account_status": profile.account_status,
        }
        for member, profile in rows
    ])


@router.post("/members", status_code=status.HTTP_201_CREATED)
async def create_member(
    payload: MemberCreate,
    request: Request,
    actor: CurrentActor = Depends(admin_only),
    db: AsyncSession = Depends(get_db),
):
    if await db.scalar(select(Taluk.id).where(Taluk.id == payload.taluk_id, Taluk.is_active.is_(True))) is None:
        raise AppError("FORBIDDEN_RESOURCE", "Active taluk was not found.", 404)
    auth_user_id, alias = await create_auth_user(
        payload.login_id, payload.temporary_password.get_secret_value(), payload.full_name, "MEMBER"
    )
    try:
        profile = Profile(
            auth_user_id=auth_user_id, login_id=payload.login_id, auth_email_alias=alias,
            role=UserRole.MEMBER, full_name=payload.full_name.strip(), phone=payload.phone,
            must_change_password=True, created_by=actor.profile_id,
        )
        db.add(profile)
        await db.flush()
        member = Member(
            profile_id=profile.id, member_code=payload.member_code.upper(),
            taluk_id=payload.taluk_id, joined_on=payload.joined_on,
        )
        db.add(member)
        await db.flush()
        db.add(AuditLog(
            actor_profile_id=actor.profile_id, actor_role=actor.role, action="MEMBER_CREATED",
            entity_type="member", entity_id=member.id,
            after_data={"login_id": payload.login_id, "member_code": member.member_code, "taluk_id": str(payload.taluk_id)},
            request_id=request_id(request),
        ))
        await db.commit()
        await db.refresh(member)
    except Exception:
        await db.rollback()
        await delete_auth_user(auth_user_id)
        raise
    return success(request, {"id": member.id, "profile_id": profile.id, "member_code": member.member_code, "full_name": profile.full_name})


@router.patch("/members/{member_id}")
async def update_member(
    member_id: uuid.UUID, payload: MemberUpdate, request: Request,
    actor: CurrentActor = Depends(admin_only), db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(
            select(Member, Profile).join(Profile, Profile.id == Member.profile_id)
            .where(Member.id == member_id).with_for_update()
        )
    ).first()
    if row is None:
        raise AppError("FORBIDDEN_RESOURCE", "Member was not found.", 404)
    member, profile = row
    if member.version != payload.expected_version or profile.version != payload.profile_expected_version:
        raise AppError("VERSION_CONFLICT", "Member was changed by another request. Reload and try again.", 409)
    if payload.account_status == AccountStatus.DECEASED:
        raise AppError("VALIDATION_ERROR", "Publish a death case to mark a member deceased.", 422)
    taluk_ready = await db.scalar(select(Taluk.id).where(
        Taluk.id == payload.taluk_id, Taluk.is_active.is_(True)
    ))
    active_assignment = await db.scalar(select(AgentTalukAssignment.id).where(
        AgentTalukAssignment.taluk_id == payload.taluk_id, AgentTalukAssignment.ends_at.is_(None)
    ))
    active_bank = await db.scalar(select(BankAccount.id).where(
        BankAccount.taluk_id == payload.taluk_id, BankAccount.ends_at.is_(None)
    ))
    if not taluk_ready or not active_assignment or not active_bank:
        raise AppError("VERSION_CONFLICT", "The selected taluk must have an active agent and bank account.", 409)
    duplicate = await db.scalar(select(Member.id).where(
        Member.id != member_id, Member.member_code == payload.member_code
    ))
    if duplicate:
        raise AppError("VERSION_CONFLICT", "Member code already exists.", 409)
    before = {
        "member_code": member.member_code, "full_name": profile.full_name, "phone": profile.phone,
        "taluk_id": str(member.taluk_id), "joined_on": str(member.joined_on),
        "account_status": profile.account_status.value,
    }
    member.member_code = payload.member_code.upper()
    member.taluk_id = payload.taluk_id
    member.joined_on = payload.joined_on
    profile.full_name = payload.full_name.strip()
    profile.phone = payload.phone.strip() if payload.phone else None
    profile.account_status = payload.account_status
    db.add(AuditLog(
        actor_profile_id=actor.profile_id, actor_role=actor.role, action="MEMBER_UPDATED",
        entity_type="member", entity_id=member.id, before_data=before,
        after_data={"member_code": member.member_code, "full_name": profile.full_name,
                    "phone": profile.phone, "taluk_id": str(member.taluk_id),
                    "joined_on": str(member.joined_on), "account_status": profile.account_status.value,
                    "reason": payload.reason},
        request_id=request_id(request),
    ))
    await db.commit()
    await db.refresh(member)
    await db.refresh(profile)
    return success(request, {"id": member.id, "version": member.version, "profile_version": profile.version})


@router.get("/bank-accounts")
async def list_bank_accounts(
    request: Request,
    _: CurrentActor = Depends(admin_only),
    db: AsyncSession = Depends(get_db),
):
    accounts = (
        await db.scalars(
            select(BankAccount)
            .join(Taluk, Taluk.id == BankAccount.taluk_id)
            .where(Taluk.is_active.is_(True), BankAccount.ends_at.is_(None))
            .order_by(BankAccount.created_at.desc())
        )
    ).all()
    return success(request, [
        {
            "id": item.id, "taluk_id": item.taluk_id, "agent_profile_id": item.agent_profile_id,
            "bank_name": item.bank_name, "branch_name": item.branch_name,
            "account_holder_name": item.account_holder_name,
            "masked_account_number": f"•••• {item.account_number_last4}",
            "ifsc_code": item.ifsc_code, "starts_at": item.starts_at, "ends_at": item.ends_at,
        }
        for item in accounts
    ])


@router.post("/bank-accounts", status_code=status.HTTP_201_CREATED)
async def create_bank_account(
    payload: BankAccountCreate,
    request: Request,
    actor: CurrentActor = Depends(admin_only),
    db: AsyncSession = Depends(get_db),
):
    assignment = await db.scalar(select(AgentTalukAssignment).where(
        AgentTalukAssignment.taluk_id == payload.taluk_id,
        AgentTalukAssignment.agent_profile_id == payload.agent_profile_id,
        AgentTalukAssignment.ends_at.is_(None),
    ))
    if assignment is None:
        raise AppError("FORBIDDEN_RESOURCE", "Agent is not actively assigned to this taluk.", 409)
    if await db.scalar(select(BankAccount.id).where(BankAccount.taluk_id == payload.taluk_id, BankAccount.ends_at.is_(None))):
        raise AppError("VERSION_CONFLICT", "Taluk already has an active bank account.", 409)
    account_number = "".join(char for char in payload.account_number.get_secret_value() if char.isdigit())
    if len(account_number) < 6:
        raise AppError("VALIDATION_ERROR", "Account number must contain at least 6 digits.", 422)
    account = BankAccount(
        taluk_id=payload.taluk_id, agent_profile_id=payload.agent_profile_id,
        bank_name=payload.bank_name.strip(), branch_name=payload.branch_name.strip(),
        account_holder_name=payload.account_holder_name.strip(),
        account_number_ciphertext=bank_cipher.encrypt(account_number.encode()).decode(),
        account_number_last4=account_number[-4:], ifsc_code=payload.ifsc_code.upper(),
        created_by=actor.profile_id,
    )
    db.add(account)
    await db.flush()
    db.add(AuditLog(
        actor_profile_id=actor.profile_id, actor_role=actor.role, action="BANK_ACCOUNT_CREATED",
        entity_type="bank_account", entity_id=account.id,
        after_data={"taluk_id": str(payload.taluk_id), "bank_name": account.bank_name, "account_number_last4": account.account_number_last4},
        request_id=request_id(request),
    ))
    await db.commit()
    await db.refresh(account)
    return success(request, {"id": account.id, "bank_name": account.bank_name, "masked_account_number": f"•••• {account.account_number_last4}", "ifsc_code": account.ifsc_code})


@router.patch("/bank-accounts/{account_id}", status_code=status.HTTP_201_CREATED)
async def replace_bank_account(
    account_id: uuid.UUID, payload: BankAccountReplace, request: Request,
    actor: CurrentActor = Depends(admin_only), db: AsyncSession = Depends(get_db),
):
    current = await db.scalar(select(BankAccount).where(
        BankAccount.id == account_id, BankAccount.ends_at.is_(None)
    ).with_for_update())
    if current is None:
        raise AppError("VERSION_CONFLICT", "Active bank account was not found. Reload and try again.", 409)
    if current.taluk_id != payload.taluk_id:
        raise AppError("VALIDATION_ERROR", "A replacement must remain in the same taluk.", 422)
    assignment = await db.scalar(select(AgentTalukAssignment.id).where(
        AgentTalukAssignment.taluk_id == payload.taluk_id,
        AgentTalukAssignment.agent_profile_id == payload.agent_profile_id,
        AgentTalukAssignment.ends_at.is_(None),
    ))
    if assignment is None:
        raise AppError("VERSION_CONFLICT", "Agent is not actively assigned to this taluk.", 409)
    account_number = "".join(char for char in payload.account_number.get_secret_value() if char.isdigit())
    if len(account_number) < 6:
        raise AppError("VALIDATION_ERROR", "Account number must contain at least 6 digits.", 422)
    current.ends_at = datetime.now(timezone.utc)
    await db.flush()
    replacement = BankAccount(
        taluk_id=payload.taluk_id, agent_profile_id=payload.agent_profile_id,
        bank_name=payload.bank_name.strip(), branch_name=payload.branch_name.strip(),
        account_holder_name=payload.account_holder_name.strip(),
        account_number_ciphertext=bank_cipher.encrypt(account_number.encode()).decode(),
        account_number_last4=account_number[-4:], ifsc_code=payload.ifsc_code.upper(),
        created_by=actor.profile_id,
    )
    db.add(replacement)
    await db.flush()
    db.add(AuditLog(
        actor_profile_id=actor.profile_id, actor_role=actor.role, action="BANK_ACCOUNT_REPLACED",
        entity_type="bank_account", entity_id=replacement.id,
        before_data={"id": str(current.id), "bank_name": current.bank_name,
                     "account_number_last4": current.account_number_last4},
        after_data={"bank_name": replacement.bank_name,
                    "account_number_last4": replacement.account_number_last4, "reason": payload.reason},
        request_id=request_id(request),
    ))
    await db.commit()
    await db.refresh(replacement)
    return success(request, {"id": replacement.id, "bank_name": replacement.bank_name,
                             "masked_account_number": f"**** {replacement.account_number_last4}",
                             "ifsc_code": replacement.ifsc_code})


@router.post("/death-cases/preview")
async def preview_death_case(
    request: Request,
    _: CurrentActor = Depends(admin_only), db: AsyncSession = Depends(get_db)
):
    month = sequence_month(datetime.now(timezone.utc))
    current = await db.scalar(
        select(func.coalesce(MonthlyCaseCounter.last_sequence, 0)).where(
            MonthlyCaseCounter.sequence_month == month
        )
    )
    next_sequence = int(current or 0) + 1
    return success(request, {
        "sequence_month": month,
        "next_sequence": next_sequence,
        "default_amount": default_case_amount(next_sequence),
        "case_number_preview": f"DC-{month:%Y%m}-{next_sequence:03d}",
        "advisory": True,
    })


@router.post("/death-cases/photo", status_code=status.HTTP_201_CREATED)
async def upload_death_case_photo(
    request: Request,
    photo: UploadFile = File(...),
    _: CurrentActor = Depends(admin_only),
):
    allowed = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
    if photo.content_type not in allowed:
        raise AppError("VALIDATION_ERROR", "Photo must be JPEG, PNG, or WebP.", 422)
    content = await photo.read(10 * 1024 * 1024 + 1)
    if len(content) > 10 * 1024 * 1024:
        raise AppError("VALIDATION_ERROR", "Photo must not exceed 10 MB.", 422)
    object_path = f"pending/{uuid.uuid4()}{allowed[photo.content_type]}"
    base = str(settings.SUPABASE_URL).rstrip("/")
    headers = {**service_headers(), "Content-Type": photo.content_type, "x-upsert": "false"}
    async with httpx.AsyncClient(timeout=30) as client:
        storage_response = await client.post(
            f"{base}/storage/v1/object/death-case-photos/{object_path}",
            headers=headers,
            content=content,
        )
    if storage_response.status_code not in (200, 201):
        raise AppError("STORAGE_UNAVAILABLE", "The case photo could not be uploaded.", 502)
    return success(request, {"object_path": object_path})


@router.post("/death-cases", status_code=status.HTTP_201_CREATED)
async def create_death_case(
    payload: DeathCaseCreate,
    request: Request,
    actor: CurrentActor = Depends(admin_only),
    db: AsyncSession = Depends(get_db),
):
    case = await publish_death_case(db, actor, payload, request_id(request))
    return success(request, case)


@router.put("/death-cases/{case_id}/whatsapp/{member_id}")
async def update_death_case_whatsapp_status(
    case_id: uuid.UUID,
    member_id: uuid.UUID,
    payload: DeathCaseWhatsAppStatusUpdate,
    request: Request,
    actor: CurrentActor = Depends(admin_only),
    db: AsyncSession = Depends(get_db),
):
    obligation = await db.scalar(select(CaseObligation.id).where(
        CaseObligation.death_case_id == case_id,
        CaseObligation.member_id == member_id,
    ))
    if obligation is None or await db.get(DeathCase, case_id) is None:
        raise AppError("FORBIDDEN_RESOURCE", "Case notification recipient was not found.", 404)

    latest = await db.scalar(
        select(AuditLog)
        .where(
            AuditLog.entity_type == "death_case_whatsapp",
            AuditLog.entity_id == case_id,
            AuditLog.after_data["member_id"].astext == str(member_id),
        )
        .order_by(AuditLog.created_at.desc())
        .limit(1)
    )
    current_status = str(latest.after_data.get("status", "NOT_SENT")) if latest else "NOT_SENT"
    next_status = payload.status
    if current_status == "SENT" and next_status == "OPENED":
        next_status = "SENT"
    if current_status != next_status:
        db.add(AuditLog(
            actor_profile_id=actor.profile_id,
            actor_role=actor.role,
            action=f"DEATH_CASE_WHATSAPP_{next_status}",
            entity_type="death_case_whatsapp",
            entity_id=case_id,
            before_data={"member_id": str(member_id), "status": current_status},
            after_data={"member_id": str(member_id), "status": next_status},
            request_id=request_id(request),
        ))
        await db.commit()
    return success(request, {
        "case_id": case_id,
        "member_id": member_id,
        "status": next_status,
        "updated_at": datetime.now(timezone.utc),
    })


@router.get("/deposits")
async def list_deposits(
    request: Request,
    review_status: DepositStatus | None = None,
    _: CurrentActor = Depends(admin_only),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(DepositBatch)
        .join(Taluk, Taluk.id == DepositBatch.taluk_id)
        .where(Taluk.is_active.is_(True))
        .order_by(DepositBatch.created_at.desc())
        .limit(100)
    )
    if review_status is not None:
        query = query.where(DepositBatch.status == review_status)
    return success(request, (await db.scalars(query)).all())


@router.post("/deposits/{batch_id}/approve")
async def approve_deposit(
    batch_id: uuid.UUID,
    payload: DepositApprove,
    request: Request,
    actor: CurrentActor = Depends(admin_only),
    db: AsyncSession = Depends(get_db),
):
    batch = await review_deposit(
        db, actor, batch_id, payload.expected_version, True, request_id(request)
    )
    return success(request, batch)


@router.post("/deposits/{batch_id}/reject")
async def reject_deposit(
    batch_id: uuid.UUID,
    payload: DepositReject,
    request: Request,
    actor: CurrentActor = Depends(admin_only),
    db: AsyncSession = Depends(get_db),
):
    batch = await review_deposit(
        db, actor, batch_id, payload.expected_version, False, request_id(request), payload.reason
    )
    return success(request, batch)
