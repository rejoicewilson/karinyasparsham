from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.services.rules import (
    default_case_amount,
    member_is_eligible_for_case,
    payment_status,
    permanent_membership_achieved,
    require_exact_deposit,
    sequence_month,
)


@pytest.mark.parametrize(
    ("sequence", "amount"),
    [(1, "200.00"), (2, "200.00"), (3, "100.00"), (4, "100.00"), (12, "100.00")],
)
def test_monthly_case_amount(sequence, amount):
    assert default_case_amount(sequence) == Decimal(amount)


def test_month_boundary_uses_kolkata():
    utc_time = datetime(2026, 7, 31, 19, 0, tzinfo=timezone.utc)
    assert sequence_month(utc_time).isoformat() == "2026-08-01"


@pytest.mark.parametrize(
    ("joined_on", "death_date", "eligible"),
    [
        ("2026-08-01", "2026-08-31", False),
        ("2026-08-31", "2026-08-31", False),
        ("2026-08-01", "2026-09-01", True),
        ("2026-08-31", "2026-09-01", True),
        ("2026-09-01", "2026-09-30", False),
    ],
)
def test_member_eligibility_starts_month_after_joining(joined_on, death_date, eligible):
    assert member_is_eligible_for_case(
        datetime.fromisoformat(joined_on).date(),
        datetime.fromisoformat(death_date).date(),
    ) is eligible


@pytest.mark.parametrize(
    ("required", "collected", "verified", "expected"),
    [
        ("200", "0", "0", "Unpaid"),
        ("200", "50", "0", "Partially Paid"),
        ("200", "200", "50", "Awaiting Verification"),
        ("200", "200", "200", "Verified"),
        ("200", "100", "50", "Partially Paid"),
    ],
)
def test_payment_status(required, collected, verified, expected):
    assert payment_status(Decimal(required), Decimal(collected), Decimal(verified)) == expected


def test_exact_deposit_rejects_one_paise_difference():
    with pytest.raises(ValueError, match="DEPOSIT_TOTAL_MISMATCH"):
        require_exact_deposit(Decimal("100.00"), Decimal("99.99"))


def test_permanent_conversion_requires_exact_verified_target():
    assert not permanent_membership_achieved(Decimal("14999.99"))
    assert permanent_membership_achieved(Decimal("15000.00"))
    with pytest.raises(ValueError):
        permanent_membership_achieved(Decimal("15000.01"))
