"""Permanently remove one confirmed duplicate imported member and generated ledger."""

import argparse
import asyncio
import json
import sys
import uuid
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg.rows import dict_row


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.supabase_admin import delete_auth_user  # noqa: E402
from import_historical_kasargod_payments import database_url  # noqa: E402


async def remove_duplicate(args: argparse.Namespace) -> None:
    apply_change = args.confirm == args.member_code
    auth_user_id = None

    with psycopg.connect(database_url(), row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT m.id AS member_id, m.member_code::text, m.ard_no,
                       p.id AS profile_id, p.auth_user_id, p.full_name, p.phone,
                       p.account_status::text, t.name AS taluk_name
                FROM members m
                JOIN profiles p ON p.id = m.profile_id
                JOIN taluks t ON t.id = m.taluk_id
                WHERE lower(m.member_code::text) = lower(%s)
                FOR UPDATE OF m, p
                """,
                (args.member_code,),
            )
            target = cursor.fetchone()
            if target is None:
                raise SystemExit("Duplicate member was not found.")
            if not (
                target["full_name"] == args.expected_name
                and target["phone"] == args.expected_phone
                and target["ard_no"] == args.expected_ard
                and target["taluk_name"].casefold() == args.expected_taluk.casefold()
            ):
                raise SystemExit("Duplicate member identity does not match the approved deletion.")

            cursor.execute(
                """
                SELECT m.member_code::text, m.ard_no, p.full_name, p.phone
                FROM members m JOIN profiles p ON p.id = m.profile_id
                WHERE lower(m.member_code::text) = lower(%s)
                """,
                (args.keep_member_code,),
            )
            retained = cursor.fetchone()
            if retained is None or not (
                retained["full_name"] == args.expected_name
                and retained["phone"] == args.expected_phone
                and retained["ard_no"] == args.keep_expected_ard
            ):
                raise SystemExit("The correct member to retain does not match the approved identity.")

            cursor.execute(
                "SELECT count(*) AS count FROM death_cases WHERE deceased_member_id = %s",
                (target["member_id"],),
            )
            if cursor.fetchone()["count"]:
                raise SystemExit("Refusing to remove a member linked as deceased in a death case.")

            cursor.execute(
                """
                SELECT count(*) AS obligations,
                       count(ct.id) AS collections,
                       coalesce(sum(ct.amount) FILTER (WHERE ct.status = 'VERIFIED'), 0) AS verified_amount,
                       count(di.id) AS deposit_items
                FROM case_obligations co
                LEFT JOIN collection_transactions ct ON ct.case_obligation_id = co.id
                LEFT JOIN deposit_items di ON di.collection_transaction_id = ct.id
                WHERE co.member_id = %s
                """,
                (target["member_id"],),
            )
            ledger = cursor.fetchone()
            guards = (
                ledger["obligations"] == args.expected_obligations,
                ledger["collections"] == args.expected_collections,
                ledger["verified_amount"] == args.expected_verified_amount,
                ledger["deposit_items"] == 0,
            )
            if not all(guards):
                raise SystemExit("Duplicate member ledger differs from the approved deletion totals.")

            summary = {
                "mode": "apply" if apply_change else "dry-run",
                "remove": dict(target),
                "retain": dict(retained),
                "obligations_to_remove": ledger["obligations"],
                "collections_to_remove": ledger["collections"],
                "verified_amount_to_remove": str(ledger["verified_amount"]),
                "deposit_items": ledger["deposit_items"],
            }
            summary["remove"].pop("auth_user_id")
            print(json.dumps(summary, indent=2, default=str))
            if not apply_change:
                connection.rollback()
                print(f'No changes made. Re-run with --confirm "{args.member_code}".')
                return

            cursor.execute(
                "DELETE FROM notification_outbox WHERE recipient_id IN "
                "(SELECT id FROM notification_recipients WHERE profile_id = %s)",
                (target["profile_id"],),
            )
            cursor.execute("DELETE FROM notification_recipients WHERE profile_id = %s", (target["profile_id"],))
            cursor.execute("DELETE FROM push_subscriptions WHERE profile_id = %s", (target["profile_id"],))
            cursor.execute("DELETE FROM idempotency_keys WHERE actor_profile_id = %s", (target["profile_id"],))
            cursor.execute("DELETE FROM audit_logs WHERE actor_profile_id = %s", (target["profile_id"],))

            # These append-only guards are bypassed only for this validated import correction.
            # PostgreSQL rolls the trigger changes back with the transaction if any delete fails.
            cursor.execute("ALTER TABLE collection_transactions DISABLE TRIGGER no_delete_collections")
            cursor.execute("ALTER TABLE case_obligations DISABLE TRIGGER no_delete_obligations")
            cursor.execute("ALTER TABLE permanent_membership_accounts DISABLE TRIGGER no_delete_permanent_accounts")
            cursor.execute("DELETE FROM collection_transactions WHERE member_id = %s", (target["member_id"],))
            cursor.execute("DELETE FROM case_obligations WHERE member_id = %s", (target["member_id"],))
            cursor.execute("DELETE FROM permanent_membership_accounts WHERE member_id = %s", (target["member_id"],))
            cursor.execute("ALTER TABLE permanent_membership_accounts ENABLE TRIGGER no_delete_permanent_accounts")
            cursor.execute("ALTER TABLE case_obligations ENABLE TRIGGER no_delete_obligations")
            cursor.execute("ALTER TABLE collection_transactions ENABLE TRIGGER no_delete_collections")
            cursor.execute("DELETE FROM members WHERE id = %s", (target["member_id"],))
            cursor.execute("DELETE FROM profiles WHERE id = %s", (target["profile_id"],))
            cursor.execute(
                """
                INSERT INTO audit_logs (
                    actor_profile_id, actor_role, action, entity_type, entity_id,
                    before_data, after_data, request_id, metadata
                )
                SELECT id, 'ADMIN', 'DUPLICATE_IMPORTED_MEMBER_REMOVED', 'member', %s,
                       %s::jsonb, %s::jsonb, %s, %s::jsonb
                FROM profiles
                WHERE role = 'ADMIN' AND account_status = 'ACTIVE'
                ORDER BY created_at LIMIT 1
                """,
                (
                    target["member_id"],
                    json.dumps({
                        "member_code": target["member_code"],
                        "full_name": target["full_name"],
                        "phone": target["phone"],
                        "ard_no": target["ard_no"],
                        "obligations": ledger["obligations"],
                        "collections": ledger["collections"],
                        "verified_amount": str(ledger["verified_amount"]),
                    }),
                    json.dumps({"removed": True, "retained_member_code": retained["member_code"]}),
                    uuid.uuid4(),
                    json.dumps({"source": "approved_duplicate_correction"}),
                ),
            )
            auth_user_id = target["auth_user_id"]
        connection.commit()

    await delete_auth_user(auth_user_id)
    print(f"Removed duplicate {args.member_code}; retained {args.keep_member_code}.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--member-code", required=True)
    parser.add_argument("--expected-name", required=True)
    parser.add_argument("--expected-phone", required=True)
    parser.add_argument("--expected-ard", required=True)
    parser.add_argument("--expected-taluk", required=True)
    parser.add_argument("--keep-member-code", required=True)
    parser.add_argument("--keep-expected-ard", required=True)
    parser.add_argument("--expected-obligations", required=True, type=int)
    parser.add_argument("--expected-collections", required=True, type=int)
    parser.add_argument("--expected-verified-amount", required=True, type=Decimal)
    parser.add_argument("--confirm")
    asyncio.run(remove_duplicate(parser.parse_args()))


if __name__ == "__main__":
    main()
