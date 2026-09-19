import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.security import CurrentActor
from app.models.domain import (
    AccountStatus,
    AgentTalukAssignment,
    AuditLog,
    BankAccount,
    CaseObligation,
    CollectionStatus,
    CollectionTransaction,
    CollectionType,
    DeathCase,
    DepositBatch,
    DepositItem,
    DepositStatus,
    Member,
    MembershipType,
    MonthlyCaseCounter,
    NotificationEvent,
    NotificationOutbox,
    NotificationRecipient,
    NotificationType,
    PermanentMembershipAccount,
    Profile,
    UserRole,
)
from app.schemas.api import CollectionCreate, DeathCaseCreate, DepositCreate
from app.services.rules import default_case_amount, eligibility_cutoff_for_case, sequence_month


def _reference(prefix: str) -> str:
    now = datetime.now(timezone.utc)
    return f"{prefix}-{now:%Y%m}-{uuid.uuid4().hex[:8].upper()}"


async def _audit(
    db: AsyncSession,
    actor: CurrentActor,
    request_id: uuid.UUID,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_profile_id=actor.profile_id,
            actor_role=actor.role,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before_data=before,
            after_data=after,
            request_id=request_id,
        )
    )


async def publish_death_case(
    db: AsyncSession,
    actor: CurrentActor,
    payload: DeathCaseCreate,
    request_id: uuid.UUID,
) -> DeathCase:
    deceased_row = (
        await db.execute(
            select(Member, Profile)
            .join(Profile, Profile.id == Member.profile_id)
            .where(Member.id == payload.deceased_member_id)
            .with_for_update()
        )
    ).one_or_none()
    if deceased_row is None or deceased_row.Profile.account_status != AccountStatus.ACTIVE:
        raise AppError("FORBIDDEN_RESOURCE", "Deceased member must be active.", 404)

    active_rows = (
        await db.execute(
            select(Member, Profile, AgentTalukAssignment.agent_profile_id)
            .join(Profile, Profile.id == Member.profile_id)
            .outerjoin(
                AgentTalukAssignment,
                (AgentTalukAssignment.taluk_id == Member.taluk_id)
                & (AgentTalukAssignment.ends_at.is_(None)),
            )
            .where(
                Profile.account_status == AccountStatus.ACTIVE,
                Member.joined_on < eligibility_cutoff_for_case(payload.death_date),
            )
        )
    ).all()
    unready = {
        str(member.taluk_id)
        for member, _, agent_id in active_rows
        if agent_id is None
    }
    if unready:
        raise AppError(
            "TALUK_AGENT_NOT_CONFIGURED",
            "Every active member's taluk requires an active agent.",
            409,
            {"taluk_ids": sorted(unready)},
        )

    now = datetime.now(timezone.utc)
    month = sequence_month(now)
    counter = pg_insert(MonthlyCaseCounter).values(
        sequence_month=month, last_sequence=1, updated_at=now
    )
    counter = counter.on_conflict_do_update(
        index_elements=[MonthlyCaseCounter.sequence_month],
        set_={
            "last_sequence": MonthlyCaseCounter.last_sequence + 1,
            "updated_at": now,
        },
    ).returning(MonthlyCaseCounter.last_sequence)
    sequence_number = int(await db.scalar(counter))
    default_amount = default_case_amount(sequence_number)
    overridden = payload.contribution_amount_override is not None
    if overridden and not payload.override_reason:
        raise AppError(
            "VALIDATION_ERROR", "An override reason is required.", 422,
            {"override_reason": "Required when overriding the default amount."},
        )
    amount = payload.contribution_amount_override or default_amount
    case = DeathCase(
        case_number=f"DC-{month:%Y%m}-{sequence_number:03d}",
        deceased_member_id=deceased_row.Member.id,
        death_date=payload.death_date,
        title=payload.title.strip(),
        details=payload.details.strip(),
        photo_object_path=payload.photo_object_path,
        sequence_month=month,
        monthly_sequence=sequence_number,
        default_amount=default_amount,
        contribution_amount=amount,
        is_amount_overridden=overridden,
        override_reason=payload.override_reason if overridden else None,
        created_by=actor.profile_id,
    )
    db.add(case)
    await db.flush()

    deceased_row.Profile.account_status = AccountStatus.DECEASED
    deceased_row.Member.deceased_at = now
    for member, profile, agent_id, _ in active_rows:
        if member.id == deceased_row.Member.id:
            continue
        db.add(
            CaseObligation(
                death_case_id=case.id,
                member_id=member.id,
                taluk_id_snapshot=member.taluk_id,
                responsible_agent_id=agent_id,
                original_agent_id=agent_id,
                required_amount=amount,
                collected_amount=Decimal("0"),
                verified_amount=Decimal("0"),
            )
        )

    event = NotificationEvent(
        type=NotificationType.DEATH_CASE_CREATED,
        title="New helping request",
        body_template=f"{deceased_row.Profile.full_name} — contribution ₹{amount:.2f}",
        template_data={"case_id": str(case.id), "amount": str(amount)},
        deep_link=f"/cases/{case.id}",
        related_entity_type="death_case",
        related_entity_id=case.id,
    )
    db.add(event)
    await db.flush()
    recipients = [
        profile.id
        for _, profile, _, _ in active_rows
        if profile.id != deceased_row.Profile.id
    ]
    recipients.extend(
        (
            await db.scalars(
                select(Profile.id).where(
                    Profile.role == UserRole.AGENT,
                    Profile.account_status == AccountStatus.ACTIVE,
                )
            )
        ).all()
    )
    for profile_id in set(recipients):
        recipient = NotificationRecipient(event_id=event.id, profile_id=profile_id)
        db.add(recipient)
        await db.flush()
        db.add(NotificationOutbox(recipient_id=recipient.id))
    await _audit(
        db, actor, request_id, "DEATH_CASE_PUBLISHED", "death_case", case.id,
        after={"case_number": case.case_number, "amount": str(amount), "obligations": len(active_rows) - 1},
    )
    await db.commit()
    await db.refresh(case)
    return case


async def record_collection(
    db: AsyncSession,
    actor: CurrentActor,
    payload: CollectionCreate,
    request_id: uuid.UUID,
) -> CollectionTransaction:
    existing = await db.scalar(
        select(CollectionTransaction).where(
            CollectionTransaction.agent_profile_id == actor.profile_id,
            CollectionTransaction.client_request_id == payload.client_request_id,
        )
    )
    if existing:
        return existing

    target = None
    taluk_id = None
    if payload.collection_type == CollectionType.DEATH_CONTRIBUTION:
        if not payload.case_obligation_id or payload.permanent_account_id:
            raise AppError("VALIDATION_ERROR", "A death-case obligation is required.", 422)
        target = await db.scalar(
            select(CaseObligation)
            .where(
                CaseObligation.id == payload.case_obligation_id,
                CaseObligation.member_id == payload.member_id,
                CaseObligation.responsible_agent_id == actor.profile_id,
            )
            .with_for_update()
        )
        if target is not None:
            taluk_id = target.taluk_id_snapshot
    else:
        if not payload.permanent_account_id or payload.case_obligation_id:
            raise AppError("VALIDATION_ERROR", "A permanent-membership account is required.", 422)
        row = (
            await db.execute(
                select(PermanentMembershipAccount, Member)
                .join(Member, Member.id == PermanentMembershipAccount.member_id)
                .join(
                    AgentTalukAssignment,
                    (AgentTalukAssignment.taluk_id == Member.taluk_id)
                    & (AgentTalukAssignment.agent_profile_id == actor.profile_id)
                    & (AgentTalukAssignment.ends_at.is_(None)),
                )
                .where(
                    PermanentMembershipAccount.id == payload.permanent_account_id,
                    PermanentMembershipAccount.member_id == payload.member_id,
                )
                .with_for_update(of=PermanentMembershipAccount)
            )
        ).one_or_none()
        if row:
            target, member = row
            taluk_id = member.taluk_id
    if target is None or taluk_id is None:
        raise AppError("FORBIDDEN_RESOURCE", "Collection target was not found.", 404)

    remaining = target.required_amount - target.collected_amount if isinstance(target, CaseObligation) else target.target_amount - target.collected_amount
    if payload.amount > remaining:
        raise AppError(
            "COLLECTION_EXCEEDS_BALANCE", "Collection amount exceeds the available balance.", 409,
            {"remaining_amount": str(remaining)},
        )
    target.collected_amount += payload.amount
    collection = CollectionTransaction(
        receipt_number=_reference("RC"),
        collection_type=payload.collection_type,
        member_id=payload.member_id,
        agent_profile_id=actor.profile_id,
        taluk_id=taluk_id,
        case_obligation_id=payload.case_obligation_id,
        permanent_account_id=payload.permanent_account_id,
        amount=payload.amount,
        method=payload.method,
        external_reference=payload.external_reference,
        note=payload.note,
        collected_at=payload.collected_at,
        status=CollectionStatus.RECORDED,
        created_by=actor.profile_id,
        client_request_id=payload.client_request_id,
    )
    db.add(collection)
    await db.flush()
    await _audit(
        db, actor, request_id, "COLLECTION_RECORDED", "collection_transaction", collection.id,
        after={"receipt_number": collection.receipt_number, "amount": str(collection.amount), "type": collection.collection_type.value},
    )
    await db.commit()
    await db.refresh(collection)
    return collection


async def create_deposit(
    db: AsyncSession,
    actor: CurrentActor,
    payload: DepositCreate,
    request_id: uuid.UUID,
) -> DepositBatch:
    collections = (
        await db.scalars(
            select(CollectionTransaction)
            .where(
                CollectionTransaction.id.in_(payload.collection_ids),
                CollectionTransaction.agent_profile_id == actor.profile_id,
            )
            .with_for_update()
        )
    ).all()
    if len(collections) != len(payload.collection_ids):
        raise AppError("FORBIDDEN_RESOURCE", "One or more collections were not found.", 404)
    if any(item.status != CollectionStatus.RECORDED for item in collections):
        raise AppError("COLLECTION_ALREADY_BATCHED", "A selected collection is not eligible.", 409)
    taluks = {item.taluk_id for item in collections}
    if len(taluks) != 1:
        raise AppError("FORBIDDEN_RESOURCE", "All collections must belong to one taluk.", 409)
    taluk_id = taluks.pop()
    bank = await db.scalar(
        select(BankAccount).where(
            BankAccount.taluk_id == taluk_id,
            BankAccount.agent_profile_id == actor.profile_id,
            BankAccount.ends_at.is_(None),
        )
    )
    total = sum((item.amount for item in collections), Decimal("0"))
    batch = DepositBatch(
        deposit_number=_reference("HND"),
        agent_profile_id=actor.profile_id,
        taluk_id=taluk_id,
        bank_account_id=bank.id if bank else None,
        bank_snapshot={
            "bank_name": bank.bank_name,
            "branch_name": bank.branch_name,
            "account_holder_name": bank.account_holder_name,
            "account_number_last4": bank.account_number_last4,
            "ifsc_code": bank.ifsc_code,
        } if bank else {},
        calculated_total=total,
        declared_deposit_amount=payload.declared_deposit_amount,
        deposited_at=payload.deposited_at,
        bank_reference=payload.bank_reference,
        agent_message=payload.agent_message,
        status=DepositStatus.DRAFT,
    )
    db.add(batch)
    await db.flush()
    for collection in collections:
        db.add(
            DepositItem(
                deposit_batch_id=batch.id,
                collection_transaction_id=collection.id,
                amount_snapshot=collection.amount,
            )
        )
    await _audit(
        db, actor, request_id, "HANDOVER_DRAFT_CREATED", "deposit_batch", batch.id,
        after={"handover_number": batch.deposit_number, "calculated_total": str(total), "items": len(collections)},
    )
    await db.commit()
    await db.refresh(batch)
    return batch


async def submit_deposit(
    db: AsyncSession,
    actor: CurrentActor,
    batch_id: uuid.UUID,
    expected_version: int,
    request_id: uuid.UUID,
) -> DepositBatch:
    batch = await db.scalar(
        select(DepositBatch)
        .where(DepositBatch.id == batch_id, DepositBatch.agent_profile_id == actor.profile_id)
        .with_for_update()
    )
    if batch is None:
        raise AppError("FORBIDDEN_RESOURCE", "Handover was not found.", 404)
    if batch.status != DepositStatus.DRAFT:
        raise AppError("HANDOVER_NOT_SUBMITTED", "Only a draft handover can be submitted.", 409)
    if batch.version != expected_version:
        raise AppError("VERSION_CONFLICT", "Handover was changed by another request.", 409)
    items = (
        await db.execute(
            select(DepositItem, CollectionTransaction)
            .join(CollectionTransaction, CollectionTransaction.id == DepositItem.collection_transaction_id)
            .where(DepositItem.deposit_batch_id == batch.id, DepositItem.released_at.is_(None))
            .with_for_update(of=CollectionTransaction)
        )
    ).all()
    if not items:
        raise AppError("VALIDATION_ERROR", "A handover requires at least one collection.", 422)
    total = sum((item.amount_snapshot for item, _ in items), Decimal("0"))
    if any(collection.status != CollectionStatus.RECORDED for _, collection in items):
        raise AppError("COLLECTION_ALREADY_BATCHED", "A collection is no longer eligible.", 409)
    batch.calculated_total = total
    batch.status = DepositStatus.SUBMITTED
    batch.submitted_at = datetime.now(timezone.utc)
    for _, collection in items:
        collection.status = CollectionStatus.BATCHED
    await _audit(db, actor, request_id, "HANDOVER_SUBMITTED", "deposit_batch", batch.id, after={"total": str(total)})
    await db.commit()
    await db.refresh(batch)
    return batch


async def review_deposit(
    db: AsyncSession,
    actor: CurrentActor,
    batch_id: uuid.UUID,
    expected_version: int,
    approve: bool,
    request_id: uuid.UUID,
    reason: str | None = None,
) -> DepositBatch:
    batch = await db.scalar(select(DepositBatch).where(DepositBatch.id == batch_id).with_for_update())
    if batch is None:
        raise AppError("FORBIDDEN_RESOURCE", "Handover was not found.", 404)
    if batch.status != DepositStatus.SUBMITTED:
        raise AppError("HANDOVER_ALREADY_REVIEWED", "Handover is not awaiting review.", 409)
    if batch.version != expected_version:
        raise AppError("VERSION_CONFLICT", "Handover was changed by another request.", 409)
    item_rows = (
        await db.execute(
            select(DepositItem, CollectionTransaction)
            .join(CollectionTransaction, CollectionTransaction.id == DepositItem.collection_transaction_id)
            .where(DepositItem.deposit_batch_id == batch.id, DepositItem.released_at.is_(None))
            .with_for_update(of=CollectionTransaction)
        )
    ).all()
    calculated = sum((item.amount_snapshot for item, _ in item_rows), Decimal("0"))
    now = datetime.now(timezone.utc)
    batch.calculated_total = calculated
    batch.reviewed_by = actor.profile_id
    batch.reviewed_at = now
    affected_members: set[uuid.UUID] = set()
    if approve:
        if calculated != batch.declared_deposit_amount:
            raise AppError(
                "HANDOVER_TOTAL_MISMATCH",
                "The handed-over amount must equal the selected collection total.",
                409,
            )
        batch.status = DepositStatus.APPROVED
        for _, collection in item_rows:
            if collection.status != CollectionStatus.BATCHED:
                raise AppError("HANDOVER_ALREADY_REVIEWED", "Collection state is invalid.", 409)
            collection.status = CollectionStatus.VERIFIED
            affected_members.add(collection.member_id)
            if collection.collection_type == CollectionType.DEATH_CONTRIBUTION:
                target = await db.scalar(
                    select(CaseObligation)
                    .where(CaseObligation.id == collection.case_obligation_id)
                    .with_for_update()
                )
                target.verified_amount += collection.amount
            else:
                account = await db.scalar(
                    select(PermanentMembershipAccount)
                    .where(PermanentMembershipAccount.id == collection.permanent_account_id)
                    .with_for_update()
                )
                account.verified_amount += collection.amount
                if account.verified_amount == account.target_amount and account.achieved_at is None:
                    account.achieved_at = now
                    member = await db.scalar(select(Member).where(Member.id == account.member_id).with_for_update())
                    member.membership_type = MembershipType.PERMANENT
                    member.permanent_since = now
        profiles = (
            await db.execute(
                select(Member.id, Member.profile_id).where(Member.id.in_(affected_members))
            )
        ).all()
        for member_id, profile_id in profiles:
            member_total = sum(
                collection.amount for _, collection in item_rows if collection.member_id == member_id
            )
            event = NotificationEvent(
                type=NotificationType.PAYMENT_VERIFIED,
                title="Payment verified",
                body_template=f"₹{member_total:.2f} has been verified.",
                template_data={"deposit_id": str(batch.id), "amount": str(member_total)},
                deep_link=f"/my-payments?deposit={batch.id}",
                related_entity_type="deposit_batch",
                related_entity_id=batch.id,
            )
            db.add(event)
            await db.flush()
            recipient = NotificationRecipient(event_id=event.id, profile_id=profile_id)
            db.add(recipient)
            await db.flush()
            db.add(NotificationOutbox(recipient_id=recipient.id))
        action = "HANDOVER_RECEIVED"
    else:
        if not reason or not reason.strip():
            raise AppError("VALIDATION_ERROR", "A rejection reason is required.", 422)
        batch.status = DepositStatus.REJECTED
        batch.rejection_reason = reason.strip()
        for item, collection in item_rows:
            item.released_at = now
            collection.status = CollectionStatus.RECORDED
        event = NotificationEvent(
            type=NotificationType.DEPOSIT_REJECTED,
            title="Handover needs correction",
            body_template=reason.strip(),
            template_data={"deposit_id": str(batch.id)},
            deep_link=f"/agent/handovers/{batch.id}",
            related_entity_type="deposit_batch",
            related_entity_id=batch.id,
        )
        db.add(event)
        await db.flush()
        recipient = NotificationRecipient(event_id=event.id, profile_id=batch.agent_profile_id)
        db.add(recipient)
        await db.flush()
        db.add(NotificationOutbox(recipient_id=recipient.id))
        action = "HANDOVER_REJECTED"
    await _audit(db, actor, request_id, action, "deposit_batch", batch.id, after={"total": str(calculated), "reason": reason})
    await db.commit()
    await db.refresh(batch)
    return batch
