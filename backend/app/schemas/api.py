import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.models.domain import AccountStatus, CollectionMethod, CollectionType


class LoginRequest(BaseModel):
    login_id: str = Field(min_length=2, max_length=100)
    password: str = Field(min_length=8, max_length=256)

    @field_validator("login_id")
    @classmethod
    def normalize_login(cls, value: str) -> str:
        return value.strip().lower()


class PasswordChangeRequest(BaseModel):
    new_password: SecretStr = Field(min_length=8, max_length=256)


class TalukCreate(BaseModel):
    code: str = Field(min_length=2, max_length=20, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=2, max_length=120)
    district: str | None = Field(default=None, max_length=120)


class TalukRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    code: str
    name: str
    district: str | None
    version: int
    is_active: bool


class CasePreviewRead(BaseModel):
    sequence_month: date
    next_sequence: int
    default_amount: Decimal
    case_number_preview: str


class CaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    case_number: str
    deceased_member_id: uuid.UUID
    death_date: date
    title: str
    details: str
    monthly_sequence: int
    contribution_amount: Decimal
    status: str
    created_at: datetime


class DuesRead(BaseModel):
    obligation_id: uuid.UUID
    case_id: uuid.UUID
    case_number: str
    deceased_name: str
    required_amount: Decimal
    collected_amount: Decimal
    verified_amount: Decimal
    amount_still_to_collect: Decimal
    amount_awaiting_verification: Decimal
    display_status: str


class DeathCaseCreate(BaseModel):
    deceased_member_id: uuid.UUID
    death_date: date
    title: str = Field(min_length=3, max_length=180)
    details: str = Field(min_length=3, max_length=5000)
    photo_object_path: str = Field(min_length=3, max_length=500)
    contribution_amount_override: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    override_reason: str | None = Field(default=None, max_length=1000)

    @field_validator("override_reason")
    @classmethod
    def strip_reason(cls, value: str | None) -> str | None:
        return value.strip() if value else None


class CollectionCreate(BaseModel):
    client_request_id: uuid.UUID
    member_id: uuid.UUID
    collection_type: CollectionType
    case_obligation_id: uuid.UUID | None = None
    permanent_account_id: uuid.UUID | None = None
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    method: CollectionMethod
    collected_at: datetime
    external_reference: str | None = Field(default=None, max_length=500)
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("collected_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("collected_at must include a timezone offset")
        return value


class DepositCreate(BaseModel):
    collection_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    declared_deposit_amount: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    deposited_at: datetime
    bank_reference: str | None = Field(default=None, max_length=500)
    agent_message: str | None = Field(default=None, max_length=1000)

    @field_validator("collection_ids")
    @classmethod
    def unique_collections(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(value) != len(set(value)):
            raise ValueError("collection_ids must be unique")
        return value


class DepositSubmit(BaseModel):
    expected_version: int = Field(ge=1)


class DepositApprove(BaseModel):
    expected_version: int = Field(ge=1)


class DepositReject(BaseModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=1000)


class AgentCreate(BaseModel):
    login_id: str = Field(min_length=2, max_length=100, pattern=r"^[A-Za-z0-9._-]+$")
    temporary_password: SecretStr = Field(min_length=8, max_length=256)
    full_name: str = Field(min_length=2, max_length=180)
    phone: str | None = Field(default=None, max_length=30)
    taluk_id: uuid.UUID

    @field_validator("login_id")
    @classmethod
    def normalize_agent_login(cls, value: str) -> str:
        return value.strip().lower()


class AgentUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    full_name: str = Field(min_length=2, max_length=180)
    phone: str | None = Field(default=None, max_length=30)
    account_status: AccountStatus
    taluk_id: uuid.UUID | None = None
    reason: str = Field(min_length=3, max_length=500)


class MemberCreate(BaseModel):
    login_id: str = Field(min_length=2, max_length=100, pattern=r"^[A-Za-z0-9._-]+$")
    temporary_password: SecretStr = Field(min_length=8, max_length=256)
    member_code: str = Field(min_length=2, max_length=40, pattern=r"^[A-Za-z0-9._-]+$")
    full_name: str = Field(min_length=2, max_length=180)
    phone: str | None = Field(default=None, max_length=30)
    taluk_id: uuid.UUID
    joined_on: date

    @field_validator("login_id")
    @classmethod
    def normalize_member_login(cls, value: str) -> str:
        return value.strip().lower()


class BankAccountCreate(BaseModel):
    taluk_id: uuid.UUID
    agent_profile_id: uuid.UUID
    bank_name: str = Field(min_length=2, max_length=180)
    branch_name: str = Field(min_length=2, max_length=180)
    account_holder_name: str = Field(min_length=2, max_length=180)
    account_number: SecretStr = Field(min_length=6, max_length=34)
    ifsc_code: str = Field(pattern=r"^[A-Za-z]{4}0[A-Za-z0-9]{6}$")


class TalukUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    code: str = Field(min_length=2, max_length=20, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=2, max_length=120)
    district: str | None = Field(default=None, max_length=120)
    is_active: bool
    reason: str = Field(min_length=3, max_length=500)


class MemberUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    profile_expected_version: int = Field(ge=1)
    member_code: str = Field(min_length=2, max_length=40, pattern=r"^[A-Za-z0-9._-]+$")
    full_name: str = Field(min_length=2, max_length=180)
    phone: str | None = Field(default=None, max_length=30)
    taluk_id: uuid.UUID
    joined_on: date
    account_status: AccountStatus
    reason: str = Field(min_length=3, max_length=500)


class BankAccountReplace(BankAccountCreate):
    reason: str = Field(min_length=3, max_length=500)
