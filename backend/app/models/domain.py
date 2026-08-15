import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, VersionMixin


class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"
    AGENT = "AGENT"
    MEMBER = "MEMBER"


class AccountStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    DECEASED = "DECEASED"
    LOCKED = "LOCKED"


class MembershipType(str, enum.Enum):
    REGULAR = "REGULAR"
    PERMANENT = "PERMANENT"


class DeathCaseStatus(str, enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class CollectionType(str, enum.Enum):
    DEATH_CONTRIBUTION = "DEATH_CONTRIBUTION"
    PERMANENT_MEMBERSHIP = "PERMANENT_MEMBERSHIP"


class CollectionMethod(str, enum.Enum):
    CASH = "CASH"
    UPI = "UPI"
    BANK_TRANSFER = "BANK_TRANSFER"
    OTHER = "OTHER"


class CollectionStatus(str, enum.Enum):
    RECORDED = "RECORDED"
    BATCHED = "BATCHED"
    VERIFIED = "VERIFIED"
    VOIDED = "VOIDED"


class DepositStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class NotificationType(str, enum.Enum):
    DEATH_CASE_CREATED = "DEATH_CASE_CREATED"
    PAYMENT_VERIFIED = "PAYMENT_VERIFIED"
    DEPOSIT_REJECTED = "DEPOSIT_REJECTED"
    PASSWORD_RESET = "PASSWORD_RESET"
    SYSTEM = "SYSTEM"


user_role = Enum(UserRole, name="user_role")
account_status = Enum(AccountStatus, name="account_status")
membership_type = Enum(MembershipType, name="membership_type")
death_case_status = Enum(DeathCaseStatus, name="death_case_status")
collection_type = Enum(CollectionType, name="collection_type")
collection_method = Enum(CollectionMethod, name="collection_method")
collection_status = Enum(CollectionStatus, name="collection_status")
deposit_status = Enum(DepositStatus, name="deposit_status")
notification_type = Enum(NotificationType, name="notification_type")
money = Numeric(12, 2)

# External Supabase Auth table. Declaring it lets SQLAlchemy resolve the profile
# foreign key without attempting to own or migrate the managed auth schema.
auth_users = Table(
    "users",
    Base.metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    schema="auth",
    info={"external": True},
)


class Profile(UUIDPrimaryKeyMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "profiles"

    auth_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("auth.users.id", ondelete="RESTRICT"), unique=True
    )
    login_id: Mapped[str] = mapped_column(CITEXT, unique=True)
    auth_email_alias: Mapped[str] = mapped_column(CITEXT, unique=True)
    role: Mapped[UserRole] = mapped_column(user_role)
    full_name: Mapped[str] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    account_status: Mapped[AccountStatus] = mapped_column(
        account_status, server_default=text("'ACTIVE'::account_status")
    )
    must_change_password: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="RESTRICT")
    )


class Taluk(UUIDPrimaryKeyMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "taluks"
    code: Mapped[str] = mapped_column(CITEXT, unique=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    district: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class AgentTalukAssignment(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "agent_taluk_assignments"
    agent_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="RESTRICT")
    )
    taluk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("taluks.id", ondelete="RESTRICT")
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        Index("uq_active_agent_per_taluk", "taluk_id", unique=True, postgresql_where=text("ends_at IS NULL")),
        Index("uq_active_taluk_per_agent", "agent_profile_id", unique=True, postgresql_where=text("ends_at IS NULL")),
    )


class Member(UUIDPrimaryKeyMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "members"
    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="RESTRICT"), unique=True
    )
    member_code: Mapped[str] = mapped_column(CITEXT, unique=True)
    taluk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("taluks.id", ondelete="RESTRICT"), index=True
    )
    joined_on: Mapped[date] = mapped_column(Date)
    membership_type: Mapped[MembershipType] = mapped_column(
        membership_type, server_default=text("'REGULAR'::membership_type")
    )
    permanent_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deceased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BankAccount(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "bank_accounts"
    taluk_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("taluks.id"))
    agent_profile_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("profiles.id"))
    bank_name: Mapped[str] = mapped_column(Text)
    branch_name: Mapped[str] = mapped_column(Text)
    account_holder_name: Mapped[str] = mapped_column(Text)
    account_number_ciphertext: Mapped[str] = mapped_column(Text)
    account_number_last4: Mapped[str] = mapped_column(String(4))
    ifsc_code: Mapped[str] = mapped_column(CITEXT)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("profiles.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        CheckConstraint("account_number_last4 ~ '^[0-9]{4}$'", name="last4_digits"),
        CheckConstraint("ifsc_code ~* '^[A-Z]{4}0[A-Z0-9]{6}$'", name="ifsc_format"),
        Index("uq_active_bank_per_taluk", "taluk_id", unique=True, postgresql_where=text("ends_at IS NULL")),
    )


class MonthlyCaseCounter(Base):
    __tablename__ = "monthly_case_counters"
    sequence_month: Mapped[date] = mapped_column(Date, primary_key=True)
    last_sequence: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (CheckConstraint("last_sequence >= 0", name="nonnegative_sequence"),)


class DeathCase(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "death_cases"
    case_number: Mapped[str] = mapped_column(CITEXT, unique=True)
    deceased_member_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("members.id"))
    death_date: Mapped[date] = mapped_column(Date)
    title: Mapped[str] = mapped_column(Text)
    details: Mapped[str] = mapped_column(Text)
    photo_object_path: Mapped[str] = mapped_column(Text)
    sequence_month: Mapped[date] = mapped_column(Date)
    monthly_sequence: Mapped[int] = mapped_column(Integer)
    default_amount: Mapped[Decimal] = mapped_column(money)
    contribution_amount: Mapped[Decimal] = mapped_column(money)
    is_amount_overridden: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    override_reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[DeathCaseStatus] = mapped_column(
        death_case_status, server_default=text("'OPEN'::death_case_status")
    )
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("profiles.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    __table_args__ = (
        UniqueConstraint("sequence_month", "monthly_sequence", name="uq_death_case_month_sequence"),
        CheckConstraint("monthly_sequence > 0", name="positive_sequence"),
        CheckConstraint("default_amount > 0 AND contribution_amount > 0", name="positive_amounts"),
        CheckConstraint(
            "(is_amount_overridden AND nullif(btrim(override_reason), '') IS NOT NULL) OR "
            "(NOT is_amount_overridden AND override_reason IS NULL)",
            name="override_reason_required",
        ),
        Index("ix_death_cases_created_desc", text("created_at DESC")),
        Index("ix_death_cases_status_created", "status", text("created_at DESC")),
    )


class CaseObligation(UUIDPrimaryKeyMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "case_obligations"
    death_case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("death_cases.id"))
    member_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("members.id"))
    taluk_id_snapshot: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("taluks.id"))
    responsible_agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("profiles.id"))
    original_agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("profiles.id"))
    required_amount: Mapped[Decimal] = mapped_column(money)
    collected_amount: Mapped[Decimal] = mapped_column(money, server_default=text("0"))
    verified_amount: Mapped[Decimal] = mapped_column(money, server_default=text("0"))
    __table_args__ = (
        UniqueConstraint("death_case_id", "member_id", name="uq_case_obligation_member"),
        CheckConstraint(
            "required_amount > 0 AND collected_amount >= 0 AND verified_amount >= 0 "
            "AND verified_amount <= collected_amount AND collected_amount <= required_amount",
            name="amount_invariants",
        ),
        Index("ix_obligations_member_case", "member_id", "death_case_id"),
        Index("ix_obligations_agent_updated", "responsible_agent_id", "updated_at"),
        Index("ix_obligations_open_balance", "responsible_agent_id", postgresql_where=text("collected_amount < required_amount")),
    )


class PermanentMembershipAccount(UUIDPrimaryKeyMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "permanent_membership_accounts"
    member_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("members.id"), unique=True)
    target_amount: Mapped[Decimal] = mapped_column(money, server_default=text("15000.00"))
    collected_amount: Mapped[Decimal] = mapped_column(money, server_default=text("0"))
    verified_amount: Mapped[Decimal] = mapped_column(money, server_default=text("0"))
    achieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint(
            "target_amount > 0 AND collected_amount >= 0 AND verified_amount >= 0 "
            "AND verified_amount <= collected_amount AND collected_amount <= target_amount",
            name="amount_invariants",
        ),
    )


class CollectionTransaction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "collection_transactions"
    receipt_number: Mapped[str] = mapped_column(CITEXT, unique=True)
    collection_type: Mapped[CollectionType] = mapped_column(collection_type)
    member_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("members.id"))
    agent_profile_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("profiles.id"))
    taluk_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("taluks.id"))
    case_obligation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("case_obligations.id"))
    permanent_account_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("permanent_membership_accounts.id"))
    amount: Mapped[Decimal] = mapped_column(money)
    method: Mapped[CollectionMethod] = mapped_column(collection_method)
    external_reference: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[CollectionStatus] = mapped_column(collection_status, server_default=text("'RECORDED'::collection_status"))
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("profiles.id"))
    voided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("profiles.id"))
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    void_reason: Mapped[str | None] = mapped_column(Text)
    client_request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    __table_args__ = (
        UniqueConstraint("agent_profile_id", "client_request_id", name="uq_collection_actor_request"),
        CheckConstraint("amount > 0", name="positive_amount"),
        CheckConstraint(
            "(collection_type = 'DEATH_CONTRIBUTION' AND case_obligation_id IS NOT NULL AND permanent_account_id IS NULL) OR "
            "(collection_type = 'PERMANENT_MEMBERSHIP' AND permanent_account_id IS NOT NULL AND case_obligation_id IS NULL)",
            name="target_matches_type",
        ),
        CheckConstraint(
            "(status = 'VOIDED' AND voided_by IS NOT NULL AND voided_at IS NOT NULL AND nullif(btrim(void_reason), '') IS NOT NULL) "
            "OR status <> 'VOIDED'",
            name="void_audit_required",
        ),
        Index("ix_collections_agent_status_date", "agent_profile_id", "status", "collected_at"),
        Index("ix_collections_member_date", "member_id", text("collected_at DESC")),
    )


class DepositBatch(UUIDPrimaryKeyMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "deposit_batches"
    deposit_number: Mapped[str] = mapped_column(CITEXT, unique=True)
    agent_profile_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("profiles.id"))
    taluk_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("taluks.id"))
    bank_account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("bank_accounts.id"))
    bank_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    calculated_total: Mapped[Decimal] = mapped_column(money, server_default=text("0"))
    declared_deposit_amount: Mapped[Decimal] = mapped_column(money, server_default=text("0"))
    deposited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bank_reference: Mapped[str | None] = mapped_column(Text)
    receipt_object_path: Mapped[str | None] = mapped_column(Text)
    agent_message: Mapped[str | None] = mapped_column(Text)
    status: Mapped[DepositStatus] = mapped_column(deposit_status, server_default=text("'DRAFT'::deposit_status"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("profiles.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint("calculated_total >= 0 AND declared_deposit_amount >= 0", name="nonnegative_totals"),
        CheckConstraint(
            "(status = 'REJECTED' AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL "
            "AND nullif(btrim(rejection_reason), '') IS NOT NULL) OR status <> 'REJECTED'",
            name="rejection_audit_required",
        ),
        CheckConstraint(
            "(status = 'APPROVED' AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL "
            "AND calculated_total = declared_deposit_amount) OR status <> 'APPROVED'",
            name="approval_exact_match",
        ),
        Index("ix_deposits_status_submitted", "status", "submitted_at"),
        Index("ix_deposits_agent_created", "agent_profile_id", text("created_at DESC")),
    )


class DepositItem(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "deposit_items"
    deposit_batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("deposit_batches.id"))
    collection_transaction_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("collection_transactions.id"))
    amount_snapshot: Mapped[Decimal] = mapped_column(money)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        CheckConstraint("amount_snapshot > 0", name="positive_amount"),
        Index("uq_active_deposit_item_collection", "collection_transaction_id", unique=True, postgresql_where=text("released_at IS NULL")),
    )


class NotificationEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "notification_events"
    type: Mapped[NotificationType] = mapped_column(notification_type)
    title: Mapped[str] = mapped_column(Text)
    body_template: Mapped[str] = mapped_column(Text)
    template_data: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    deep_link: Mapped[str | None] = mapped_column(Text)
    related_entity_type: Mapped[str | None] = mapped_column(Text)
    related_entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NotificationRecipient(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "notification_recipients"
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("notification_events.id"))
    profile_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("profiles.id"))
    recipient_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    push_status: Mapped[str] = mapped_column(String(20), server_default=text("'PENDING'"))
    push_attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("event_id", "profile_id", name="uq_notification_event_recipient"),
        Index("ix_notifications_profile_read_created", "profile_id", "read_at", text("created_at DESC")),
    )


class PushSubscription(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "push_subscriptions"
    profile_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("profiles.id"))
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh_ciphertext: Mapped[str] = mapped_column(Text)
    auth_ciphertext: Mapped[str] = mapped_column(Text)
    device_label: Mapped[str | None] = mapped_column(Text)
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index("ix_push_subscriptions_profile_active", "profile_id", postgresql_where=text("revoked_at IS NULL")),)


class NotificationOutbox(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "notification_outbox"
    recipient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("notification_recipients.id"), unique=True)
    status: Mapped[str] = mapped_column(String(20), server_default=text("'PENDING'"))
    attempt_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_error: Mapped[str | None] = mapped_column(Text)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        CheckConstraint("status IN ('PENDING','PROCESSING','SENT','FAILED')", name="valid_status"),
        Index("ix_outbox_due", "status", "next_attempt_at", postgresql_where=text("status IN ('PENDING','FAILED')")),
    )


class AuditLog(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_logs"
    actor_profile_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("profiles.id"))
    actor_role: Mapped[UserRole | None] = mapped_column(user_role)
    action: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str] = mapped_column(Text)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    before_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    ip_hash: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, server_default=text("'{}'::jsonb"))
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        Index("ix_audit_entity_created", "entity_type", "entity_id", text("created_at DESC")),
        Index("ix_audit_actor_created", "actor_profile_id", text("created_at DESC")),
    )


class AppSetting(UUIDPrimaryKeyMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(CITEXT, unique=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB)
    description: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("profiles.id"))


class IdempotencyKey(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "idempotency_keys"
    actor_profile_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("profiles.id"))
    operation: Mapped[str] = mapped_column(Text)
    key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    request_hash: Mapped[str] = mapped_column(String(64))
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("actor_profile_id", "operation", "key", name="uq_idempotency_actor_operation_key"),
        Index("ix_idempotency_expiry", "expires_at"),
    )
