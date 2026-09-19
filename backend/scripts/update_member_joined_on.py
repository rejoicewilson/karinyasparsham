"""Safely correct a member joining date with an audit record."""

import argparse
import json
import sys
import uuid
from datetime import date
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import psycopg
from psycopg.rows import dict_row


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402


def database_url() -> str:
    configured = get_settings().DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)
    parsed = urlsplit(configured)
    query = [("sslmode" if key == "ssl" else key, value) for key, value in parse_qsl(parsed.query)]
    return urlunsplit((*parsed[:3], urlencode(query), parsed.fragment))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--login-id", required=True)
    parser.add_argument("--expected-member-code", required=True)
    parser.add_argument("--expected-current-date", type=date.fromisoformat, required=True)
    parser.add_argument("--new-date", type=date.fromisoformat, required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--confirm", help="Must exactly match the login ID to apply")
    args = parser.parse_args()
    login_id = args.login_id.strip().lower()
    apply_change = args.confirm == login_id

    with psycopg.connect(database_url(), row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT m.id AS member_id, m.member_code::text, m.joined_on,
                       p.id AS profile_id, p.full_name
                FROM profiles p
                JOIN members m ON m.profile_id = p.id
                WHERE lower(p.login_id::text) = lower(%s)
                FOR UPDATE OF p, m
                """,
                (login_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise SystemExit("Member login ID was not found.")
            if row["member_code"].casefold() != args.expected_member_code.strip().casefold():
                raise SystemExit("Member code does not match the requested login ID.")
            if row["joined_on"] != args.expected_current_date:
                raise SystemExit(
                    f"Current joining date is {row['joined_on']}, not {args.expected_current_date}."
                )
            cursor.execute(
                """
                SELECT count(*)
                FROM case_obligations co
                JOIN death_cases dc ON dc.id = co.death_case_id
                WHERE co.member_id = %s AND dc.death_date < %s
                """,
                (row["member_id"], args.new_date),
            )
            earlier_obligations = cursor.fetchone()["count"]
            if earlier_obligations:
                raise SystemExit(
                    "Joining date was not changed because earlier obligations already exist."
                )
            print(json.dumps({
                "mode": "apply" if apply_change else "dry-run",
                "login_id": login_id,
                "member_code": row["member_code"],
                "current_joined_on": row["joined_on"].isoformat(),
                "new_joined_on": args.new_date.isoformat(),
                "earlier_obligations": earlier_obligations,
            }, indent=2))
            if not apply_change:
                connection.rollback()
                print(f'No changes made. Re-run with --confirm "{login_id}".')
                return
            cursor.execute(
                "UPDATE members SET joined_on = %s, version = version + 1 WHERE id = %s",
                (args.new_date, row["member_id"]),
            )
            cursor.execute(
                """
                INSERT INTO audit_logs (
                    actor_profile_id, actor_role, action, entity_type,
                    entity_id, before_data, after_data, request_id, metadata
                )
                SELECT id, 'ADMIN', 'MEMBER_JOINING_DATE_CORRECTED', 'member', %s,
                       %s::jsonb, %s::jsonb, %s, %s::jsonb
                FROM profiles
                WHERE role = 'ADMIN' AND account_status = 'ACTIVE'
                ORDER BY created_at
                LIMIT 1
                """,
                (
                    row["member_id"],
                    json.dumps({"joined_on": row["joined_on"].isoformat()}),
                    json.dumps({
                        "joined_on": args.new_date.isoformat(),
                        "reason": args.reason.strip(),
                    }),
                    uuid.uuid4(),
                    json.dumps({"source": "member_joining_date_correction_script"}),
                ),
            )
        connection.commit()
    print("Member joining date corrected and audited.")


if __name__ == "__main__":
    main()
