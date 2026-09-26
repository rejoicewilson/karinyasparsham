"""Void one incorrectly reconstructed historical payment with full audit data."""

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg.rows import dict_row


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from import_historical_kasargod_payments import database_url  # noqa: E402


CONFIRMATION = "VOID-HISTORICAL-PAYMENT-CORRECTION"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--member-code", required=True)
    parser.add_argument("--case-number", required=True)
    parser.add_argument("--receipt-number", required=True)
    parser.add_argument("--expected-amount", type=Decimal, required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--confirm")
    args = parser.parse_args()
    apply_change = args.confirm == CONFIRMATION

    with psycopg.connect(database_url(), row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT ct.id AS collection_id, ct.status::text, ct.amount,
                       ct.receipt_number::text, co.id AS obligation_id,
                       co.required_amount, co.collected_amount, co.verified_amount,
                       m.id AS member_id, m.member_code::text, dc.case_number::text,
                       (SELECT count(*) FROM deposit_items di
                        WHERE di.collection_transaction_id = ct.id) AS deposit_items
                FROM collection_transactions ct
                JOIN case_obligations co ON co.id = ct.case_obligation_id
                JOIN members m ON m.id = co.member_id
                JOIN death_cases dc ON dc.id = co.death_case_id
                WHERE lower(m.member_code::text) = lower(%s)
                  AND lower(dc.case_number::text) = lower(%s)
                  AND lower(ct.receipt_number::text) = lower(%s)
                FOR UPDATE OF ct, co
                """,
                (args.member_code, args.case_number, args.receipt_number),
            )
            row = cursor.fetchone()
            if row is None:
                raise SystemExit("The exact historical payment was not found.")
            if (
                row["status"] != "VERIFIED"
                or row["amount"] != args.expected_amount
                or row["required_amount"] != args.expected_amount
                or row["collected_amount"] != args.expected_amount
                or row["verified_amount"] != args.expected_amount
                or row["deposit_items"] != 0
            ):
                raise SystemExit("The historical payment does not match the correction guards.")

            summary = {
                "mode": "apply" if apply_change else "dry-run",
                "member_code": row["member_code"],
                "case_number": row["case_number"],
                "receipt_number": row["receipt_number"],
                "amount_to_void": str(row["amount"]),
                "resulting_required": str(row["required_amount"]),
                "resulting_collected": "0",
                "resulting_verified": "0",
                "resulting_status": "Unpaid",
            }
            print(json.dumps(summary, indent=2))
            if not apply_change:
                connection.rollback()
                print(f'No changes made. Re-run with --confirm "{CONFIRMATION}".')
                return

            cursor.execute(
                "SELECT id FROM profiles WHERE role = 'ADMIN' AND account_status = 'ACTIVE' "
                "ORDER BY created_at LIMIT 1"
            )
            admin = cursor.fetchone()
            if admin is None:
                raise SystemExit("Active administrator was not found.")
            now = datetime.now(timezone.utc)
            cursor.execute(
                """
                UPDATE collection_transactions
                SET status = 'VOIDED', voided_by = %s, voided_at = %s, void_reason = %s
                WHERE id = %s
                """,
                (admin["id"], now, args.reason.strip(), row["collection_id"]),
            )
            cursor.execute(
                """
                UPDATE case_obligations
                SET collected_amount = 0, verified_amount = 0
                WHERE id = %s
                """,
                (row["obligation_id"],),
            )
            cursor.execute(
                """
                INSERT INTO audit_logs (
                    actor_profile_id, actor_role, action, entity_type, entity_id,
                    before_data, after_data, request_id, metadata
                ) VALUES (%s, 'ADMIN', 'HISTORICAL_PAYMENT_VOIDED_CORRECTION',
                          'collection_transaction', %s, %s::jsonb, %s::jsonb, %s, %s::jsonb)
                """,
                (
                    admin["id"], row["collection_id"],
                    json.dumps({
                        "status": row["status"],
                        "collected_amount": str(row["collected_amount"]),
                        "verified_amount": str(row["verified_amount"]),
                    }),
                    json.dumps({
                        "status": "VOIDED",
                        "collected_amount": "0",
                        "verified_amount": "0",
                        "reason": args.reason.strip(),
                    }),
                    uuid.uuid4(),
                    json.dumps({"source": "historical_ledger_correction"}),
                ),
            )
        connection.commit()
    print("Historical payment voided; obligation is now unpaid.")


if __name__ == "__main__":
    main()
