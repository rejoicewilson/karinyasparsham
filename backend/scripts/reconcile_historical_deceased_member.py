"""Reconcile one historical deceased member with an approved roster identity."""

import argparse
import json
import sys
import uuid
from pathlib import Path

import psycopg
from psycopg.rows import dict_row


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from import_historical_kasargod_payments import database_url  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-member-code", required=True)
    parser.add_argument("--expected-phone", required=True)
    parser.add_argument("--expected-taluk", required=True)
    parser.add_argument("--expected-case-number", required=True)
    parser.add_argument("--new-member-code", required=True)
    parser.add_argument("--new-name", required=True)
    parser.add_argument("--ard-no", required=True)
    parser.add_argument("--confirm", help="Must exactly match the new member code")
    args = parser.parse_args()
    apply_change = args.confirm == args.new_member_code

    with psycopg.connect(database_url(), row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT m.id AS member_id, m.member_code::text, m.ard_no,
                       p.id AS profile_id, p.full_name, p.phone,
                       p.account_status::text, t.name AS taluk_name,
                       dc.id AS case_id, dc.case_number::text, dc.title
                FROM members m
                JOIN profiles p ON p.id = m.profile_id
                JOIN taluks t ON t.id = m.taluk_id
                JOIN death_cases dc ON dc.deceased_member_id = m.id
                WHERE lower(m.member_code::text) = lower(%s)
                FOR UPDATE OF m, p, dc
                """,
                (args.current_member_code,),
            )
            row = cursor.fetchone()
            if row is None:
                raise SystemExit("Historical deceased member was not found.")
            expected = (
                row["phone"] == args.expected_phone
                and row["taluk_name"].casefold() == args.expected_taluk.casefold()
                and row["case_number"].casefold() == args.expected_case_number.casefold()
                and row["account_status"] == "DECEASED"
            )
            if not expected:
                raise SystemExit("Historical deceased member does not match the expected identity.")
            cursor.execute(
                "SELECT id FROM members WHERE lower(member_code::text) = lower(%s) AND id <> %s",
                (args.new_member_code, row["member_id"]),
            )
            if cursor.fetchone() is not None:
                raise SystemExit("The new member code is already assigned to another member.")

            new_title = f"Historical helping request for {args.new_name.strip()}"
            summary = {
                "mode": "apply" if apply_change else "dry-run",
                "current_member_code": row["member_code"],
                "new_member_code": args.new_member_code,
                "current_name": row["full_name"],
                "new_name": args.new_name.strip(),
                "ard_no": args.ard_no,
                "case_number": row["case_number"],
                "current_case_title": row["title"],
                "new_case_title": new_title,
            }
            print(json.dumps(summary, indent=2))
            if not apply_change:
                connection.rollback()
                print(f'No changes made. Re-run with --confirm "{args.new_member_code}".')
                return

            cursor.execute(
                "UPDATE profiles SET full_name = %s WHERE id = %s",
                (args.new_name.strip(), row["profile_id"]),
            )
            cursor.execute(
                "UPDATE members SET member_code = %s, ard_no = %s, version = version + 1 WHERE id = %s",
                (args.new_member_code, args.ard_no, row["member_id"]),
            )
            cursor.execute(
                "UPDATE death_cases SET title = %s, version = version + 1 WHERE id = %s",
                (new_title, row["case_id"]),
            )
            cursor.execute(
                """
                INSERT INTO audit_logs (
                    actor_profile_id, actor_role, action, entity_type, entity_id,
                    before_data, after_data, request_id, metadata
                )
                SELECT id, 'ADMIN', 'HISTORICAL_DECEASED_MEMBER_RECONCILED',
                       'member', %s, %s::jsonb, %s::jsonb, %s, %s::jsonb
                FROM profiles
                WHERE role = 'ADMIN' AND account_status = 'ACTIVE'
                ORDER BY created_at
                LIMIT 1
                """,
                (
                    row["member_id"],
                    json.dumps({
                        "member_code": row["member_code"],
                        "full_name": row["full_name"],
                        "ard_no": row["ard_no"],
                        "case_title": row["title"],
                    }),
                    json.dumps({
                        "member_code": args.new_member_code,
                        "full_name": args.new_name.strip(),
                        "ard_no": args.ard_no,
                        "case_title": new_title,
                    }),
                    uuid.uuid4(),
                    json.dumps({"source": "approved_member_roster"}),
                ),
            )
        connection.commit()
    print("Historical deceased member reconciled and audited.")


if __name__ == "__main__":
    main()
