from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo


IST = ZoneInfo("Asia/Kolkata")
FIRST_CASE_AMOUNT = Decimal("200.00")
LATER_CASE_AMOUNT = Decimal("100.00")
FIRST_CASE_AMOUNT_LIMIT = 2
PERMANENT_TARGET = Decimal("15000.00")


def sequence_month(now: datetime) -> datetime.date:
    local = now.astimezone(IST)
    return local.date().replace(day=1)


def default_case_amount(sequence: int) -> Decimal:
    if sequence < 1:
        raise ValueError("Monthly sequence must be positive")
    return FIRST_CASE_AMOUNT if sequence <= FIRST_CASE_AMOUNT_LIMIT else LATER_CASE_AMOUNT


def eligibility_cutoff_for_case(death_date: date) -> date:
    return death_date.replace(day=1)


def member_is_eligible_for_case(joined_on: date, death_date: date) -> bool:
    """Membership contributions begin in the calendar month after joining."""
    return joined_on < eligibility_cutoff_for_case(death_date)


def payment_status(required: Decimal, collected: Decimal, verified: Decimal) -> str:
    if any(value < 0 for value in (required, collected, verified)):
        raise ValueError("Amounts cannot be negative")
    if verified > collected or collected > required:
        raise ValueError("Financial amount invariant violated")
    if collected == 0:
        return "Unpaid"
    if collected < required:
        return "Partially Paid"
    if verified < required:
        return "Awaiting Verification"
    return "Verified"


def require_exact_deposit(calculated: Decimal, declared: Decimal) -> None:
    if calculated != declared:
        raise ValueError("DEPOSIT_TOTAL_MISMATCH")


def permanent_membership_achieved(verified: Decimal, target: Decimal = PERMANENT_TARGET) -> bool:
    if verified > target:
        raise ValueError("Permanent membership overpayment")
    return verified == target
