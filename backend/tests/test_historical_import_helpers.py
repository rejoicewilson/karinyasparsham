import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from scripts.import_uniform_historical_taluk_ledger import parse_paid_through_overrides


def test_parse_paid_through_overrides_normalizes_member_codes():
    assert parse_paid_through_overrides([" WYD-01-M022=20 "]) == {
        "wyd-01-m022": 20,
    }


@pytest.mark.parametrize("value", ["WYD-01-M022", "=20", "WYD-01-M022=twenty"])
def test_parse_paid_through_overrides_rejects_invalid_values(value):
    with pytest.raises(SystemExit):
        parse_paid_through_overrides([value])


def test_parse_paid_through_overrides_rejects_duplicates():
    with pytest.raises(SystemExit, match="Duplicate"):
        parse_paid_through_overrides(["WYD-01-M022=20", "wyd-01-m022=19"])
