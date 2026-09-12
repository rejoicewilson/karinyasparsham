"""Read-only verification of active production workspace record counts."""

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import psycopg
from psycopg.rows import dict_row


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-taluks", type=int, default=0)
    args = parser.parse_args()
    configured = get_settings().DATABASE_URL.replace(
        "postgresql+asyncpg://", "postgresql://", 1
    )
    parsed = urlsplit(configured)
    query = [
        ("sslmode" if key == "ssl" else key, value)
        for key, value in parse_qsl(parsed.query)
    ]
    database_url = urlunsplit((*parsed[:3], urlencode(query), parsed.fragment))

    checks = {
        "active_admins": (
            "SELECT count(*) FROM profiles "
            "WHERE role = 'ADMIN' AND account_status = 'ACTIVE'"
        ),
        "active_non_admins": (
            "SELECT count(*) FROM profiles "
            "WHERE role <> 'ADMIN' AND account_status = 'ACTIVE'"
        ),
        "active_taluks": "SELECT count(*) FROM taluks WHERE is_active",
        "active_assignments": (
            "SELECT count(*) FROM agent_taluk_assignments WHERE ends_at IS NULL"
        ),
        "active_banks": "SELECT count(*) FROM bank_accounts WHERE ends_at IS NULL",
        "visible_members": (
            "SELECT count(*) FROM members m JOIN taluks t ON t.id = m.taluk_id "
            "WHERE t.is_active"
        ),
        "visible_cases": (
            "SELECT count(*) FROM death_cases dc "
            "JOIN members m ON m.id = dc.deceased_member_id "
            "JOIN taluks t ON t.id = m.taluk_id WHERE t.is_active"
        ),
        "visible_collections": (
            "SELECT count(*) FROM collection_transactions ct "
            "JOIN taluks t ON t.id = ct.taluk_id WHERE t.is_active"
        ),
        "visible_deposits": (
            "SELECT count(*) FROM deposit_batches db "
            "JOIN taluks t ON t.id = db.taluk_id WHERE t.is_active"
        ),
        "production_boundary": (
            "SELECT count(*) FROM app_settings WHERE key = 'production_data_boundary'"
        ),
    }
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            result = {}
            for name, statement in checks.items():
                cursor.execute(statement)
                result[name] = cursor.fetchone()["count"]
    expected = {
        "active_admins": 1,
        "active_non_admins": 0,
        "active_taluks": args.expected_taluks,
        "active_assignments": 0,
        "active_banks": 0,
        "visible_members": 0,
        "visible_cases": 0,
        "visible_collections": 0,
        "visible_deposits": 0,
        "production_boundary": 1,
    }
    print(json.dumps(result, indent=2))
    if result != expected:
        raise SystemExit("Production workspace verification failed.")
    print("Production workspace counts match and the sole Admin is active.")


if __name__ == "__main__":
    main()
