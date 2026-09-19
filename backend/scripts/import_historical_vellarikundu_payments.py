"""Reconstruct Vellarikundu historical payments and unpaid obligations."""

import argparse
import json
import sys
import uuid
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg.rows import dict_row


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from import_historical_kasargod_payments import case_timestamp, database_url  # noqa: E402
from validate_historical_deaths import load_rows  # noqa: E402


CONFIRMATION = "IMPORT-VELLARIKUNDU-HISTORICAL-LEDGER"
REQUEST_NAMESPACE = uuid.UUID("e54586b7-67bf-45c7-a4ba-a2adfdca99c4")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--taluk", default="Vellarikundu")
    parser.add_argument("--admin-login", default="admin")
    parser.add_argument("--shyamala-code", default="KSD-03-M002")
    parser.add_argument("--jose-code", default="KSD-03-M004")
    parser.add_argument("--expected-members", type=int)
    parser.add_argument("--expected-paid-obligations", type=int)
    parser.add_argument("--expected-verified-amount", type=Decimal)
    parser.add_argument("--expected-pending-obligations", type=int)
    parser.add_argument("--expected-pending-amount", type=Decimal)
    parser.add_argument("--confirm")
    args = parser.parse_args()
    apply_change = args.confirm == CONFIRMATION

    source_rows = load_rows(args.source.resolve())
    if [int(row["legacy_no"]) for row in source_rows] != list(range(1, 36)):
        raise SystemExit("Historical source must contain contiguous cases 1-35.")
    case_amounts = {
        f"HIST-{int(row['legacy_no']):03d}": Decimal(row["amount"])
        for row in source_rows
    }

    with psycopg.connect(database_url(), row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM profiles WHERE role = 'ADMIN' AND account_status = 'ACTIVE' "
                "AND lower(login_id::text) = lower(%s)",
                (args.admin_login,),
            )
            admin = cursor.fetchone()
            if admin is None:
                raise SystemExit("Active administrator was not found.")

            cursor.execute(
                "SELECT id FROM taluks WHERE is_active AND lower(name) = lower(%s)",
                (args.taluk,),
            )
            taluk = cursor.fetchone()
            if taluk is None:
                raise SystemExit("Active Vellarikundu taluk was not found.")
            cursor.execute(
                "SELECT agent_profile_id FROM agent_taluk_assignments "
                "WHERE taluk_id = %s AND ends_at IS NULL",
                (taluk["id"],),
            )
            assignment = cursor.fetchone()
            if assignment is None:
                raise SystemExit("Vellarikundu does not have an active agent assignment.")

            cursor.execute(
                """
                SELECT m.id, m.member_code::text, p.full_name, p.account_status::text,
                       m.deceased_at
                FROM members m
                JOIN profiles p ON p.id = m.profile_id
                WHERE m.taluk_id = %s
                ORDER BY m.member_code
                """,
                (taluk["id"],),
            )
            members = cursor.fetchall()
            member_by_code = {member["member_code"].casefold(): member for member in members}
            shyamala = member_by_code.get(args.shyamala_code.casefold())
            jose = member_by_code.get(args.jose_code.casefold())
            if shyamala is None or shyamala["full_name"].strip().casefold() != "shyamala a":
                raise SystemExit("Shyamala A member record was not found by the approved code.")
            if jose is None or jose["full_name"].strip().casefold() != "jose mathew":
                raise SystemExit("Jose Mathew member record was not found by the approved code.")
            if jose["account_status"] != "DECEASED":
                raise SystemExit("Jose Mathew must already be marked deceased.")

            cursor.execute(
                """
                SELECT id, case_number::text, death_date, contribution_amount
                FROM death_cases
                WHERE case_number::text LIKE 'HIST-%%'
                ORDER BY case_number
                """
            )
            cases = cursor.fetchall()
            case_by_number = {case["case_number"]: case for case in cases}
            if set(case_by_number) != set(case_amounts):
                raise SystemExit("Database historical cases do not exactly match source cases 1-35.")
            for case_number, amount in case_amounts.items():
                if case_by_number[case_number]["contribution_amount"] != amount:
                    raise SystemExit(f"{case_number} amount differs from the source.")

            desired: dict[tuple[uuid.UUID, uuid.UUID], dict[str, object]] = {}
            paid_specs = []
            pending_specs = []
            for member in members:
                code = member["member_code"].casefold()
                if code == args.shyamala_code.casefold():
                    paid_through = 20
                    pending_from = None
                elif code == args.jose_code.casefold():
                    paid_through = 29
                    pending_from = None
                else:
                    paid_through = 30
                    pending_from = 31

                for sequence in range(1, paid_through + 1):
                    case = case_by_number[f"HIST-{sequence:03d}"]
                    spec = {"member": member, "case": case, "amount": case["contribution_amount"], "paid": True}
                    desired[(member["id"], case["id"])] = spec
                    paid_specs.append(spec)
                if pending_from is not None:
                    for sequence in range(pending_from, 36):
                        case = case_by_number[f"HIST-{sequence:03d}"]
                        spec = {"member": member, "case": case, "amount": case["contribution_amount"], "paid": False}
                        desired[(member["id"], case["id"])] = spec
                        pending_specs.append(spec)

            cursor.execute(
                """
                SELECT co.id, co.member_id, co.death_case_id, co.taluk_id_snapshot,
                       co.required_amount,
                       co.collected_amount, co.verified_amount, m.member_code::text,
                       dc.case_number::text,
                       EXISTS (SELECT 1 FROM collection_transactions ct WHERE ct.case_obligation_id = co.id) AS has_collection,
                       (SELECT count(*) FROM collection_transactions ct WHERE ct.case_obligation_id = co.id) AS collection_count,
                       (SELECT count(*) FROM collection_transactions ct
                        WHERE ct.case_obligation_id = co.id AND ct.status = 'VERIFIED') AS verified_collection_count,
                       (SELECT coalesce(sum(ct.amount), 0) FROM collection_transactions ct
                        WHERE ct.case_obligation_id = co.id AND ct.status = 'VERIFIED') AS verified_collection_amount,
                       EXISTS (SELECT 1 FROM deposit_items di JOIN collection_transactions ct ON ct.id = di.collection_transaction_id
                               WHERE ct.case_obligation_id = co.id) AS has_deposit
                FROM case_obligations co
                JOIN members m ON m.id = co.member_id
                JOIN death_cases dc ON dc.id = co.death_case_id
                WHERE m.taluk_id = %s AND dc.case_number::text LIKE 'HIST-%%'
                """,
                (taluk["id"],),
            )
            existing_rows = cursor.fetchall()
            wrong_snapshots = [
                (row["member_code"], row["case_number"])
                for row in existing_rows
                if row["taluk_id_snapshot"] != taluk["id"]
            ]
            if wrong_snapshots:
                raise SystemExit(f"Existing obligations have a different taluk snapshot: {wrong_snapshots}")
            existing = {(row["member_id"], row["death_case_id"]): row for row in existing_rows}
            extra = [row for key, row in existing.items() if key not in desired]
            if any(row["has_collection"] or row["has_deposit"] for row in extra):
                raise SystemExit("An ineligible existing obligation has financial child records.")
            extra_identity = sorted((row["member_code"], row["case_number"]) for row in extra)
            if extra_identity not in ([], [(args.shyamala_code, "HIST-035")]):
                raise SystemExit(f"Unexpected ineligible obligations: {extra_identity}")

            missing_paid = [spec for key, spec in desired.items() if spec["paid"] and key not in existing]
            missing_pending = [spec for key, spec in desired.items() if not spec["paid"] and key not in existing]
            for key, spec in desired.items():
                row = existing.get(key)
                if row is None:
                    continue
                expected_amount = spec["amount"]
                expected_paid = bool(spec["paid"])
                if row["required_amount"] != expected_amount:
                    raise SystemExit(f"Existing obligation amount differs for {row['member_code']} {row['case_number']}.")
                if expected_paid and (row["collected_amount"] != expected_amount or row["verified_amount"] != expected_amount):
                    raise SystemExit(f"Existing paid obligation differs for {row['member_code']} {row['case_number']}.")
                if not expected_paid and (row["collected_amount"] != 0 or row["verified_amount"] != 0):
                    raise SystemExit(f"Existing pending obligation differs for {row['member_code']} {row['case_number']}.")
                if expected_paid and (
                    row["collection_count"] != 1
                    or row["verified_collection_count"] != 1
                    or row["verified_collection_amount"] != expected_amount
                ):
                    raise SystemExit(f"Verified collection differs for {row['member_code']} {row['case_number']}.")
                if not expected_paid and row["collection_count"] != 0:
                    raise SystemExit(f"Pending obligation has a collection for {row['member_code']} {row['case_number']}.")

            paid_amount = sum((spec["amount"] for spec in paid_specs), Decimal("0"))
            pending_amount = sum((spec["amount"] for spec in pending_specs), Decimal("0"))
            summary = {
                "mode": "apply" if apply_change else "dry-run",
                "members": len(members),
                "shyamala_paid_through": 20,
                "shyamala_will_be_inactive": shyamala["account_status"] != "INACTIVE",
                "jose_paid_through": 29,
                "other_members": len(members) - 2,
                "other_members_paid_through": 30,
                "paid_obligations": len(paid_specs),
                "verified_amount": str(paid_amount),
                "pending_obligations": len(pending_specs),
                "pending_amount": str(pending_amount),
                "existing_obligations": len(existing_rows),
                "missing_paid_obligations": len(missing_paid),
                "missing_pending_obligations": len(missing_pending),
                "ineligible_unpaid_obligations_to_remove": extra_identity,
                "notifications_created": 0,
                "deposits_created": 0,
            }
            print(json.dumps(summary, indent=2))

            if not apply_change:
                connection.rollback()
                print(f'No changes made. Re-run with --confirm "{CONFIRMATION}" and expected totals.')
                return
            guards = (
                args.expected_members == len(members),
                args.expected_paid_obligations == len(paid_specs),
                args.expected_verified_amount == paid_amount,
                args.expected_pending_obligations == len(pending_specs),
                args.expected_pending_amount == pending_amount,
            )
            if not all(guards):
                raise SystemExit("One or more expected-total guards do not match the dry run.")

            if shyamala["account_status"] != "INACTIVE":
                cursor.execute(
                    "UPDATE profiles SET account_status = 'INACTIVE', must_change_password = false WHERE id = "
                    "(SELECT profile_id FROM members WHERE id = %s)",
                    (shyamala["id"],),
                )
                cursor.execute(
                    """
                    INSERT INTO audit_logs (
                        actor_profile_id, actor_role, action, entity_type, entity_id,
                        before_data, after_data, request_id, metadata
                    ) VALUES (%s, 'ADMIN', 'MEMBER_DEACTIVATED_HISTORICAL', 'member', %s,
                              %s::jsonb, %s::jsonb, %s, %s::jsonb)
                    """,
                    (
                        admin["id"], shyamala["id"],
                        json.dumps({"account_status": shyamala["account_status"]}),
                        json.dumps({"account_status": "INACTIVE", "paid_through_case": 20}),
                        uuid.uuid4(), json.dumps({"source": "pre_application_records"}),
                    ),
                )

            if extra:
                cursor.execute("ALTER TABLE case_obligations DISABLE TRIGGER no_delete_obligations")
                for obligation in extra:
                    cursor.execute("DELETE FROM case_obligations WHERE id = %s", (obligation["id"],))
                    cursor.execute(
                        """
                        INSERT INTO audit_logs (
                            actor_profile_id, actor_role, action, entity_type, entity_id,
                            before_data, after_data, request_id, metadata
                        ) VALUES (%s, 'ADMIN', 'INELIGIBLE_HISTORICAL_OBLIGATION_REMOVED',
                                  'case_obligation', %s, %s::jsonb, NULL, %s, %s::jsonb)
                        """,
                        (
                            admin["id"], obligation["id"],
                            json.dumps({
                                "member_code": obligation["member_code"],
                                "case_number": obligation["case_number"],
                                "required_amount": str(obligation["required_amount"]),
                                "collected_amount": str(obligation["collected_amount"]),
                                "verified_amount": str(obligation["verified_amount"]),
                            }),
                            uuid.uuid4(),
                            json.dumps({"reason": "Member left after historical case 20"}),
                        ),
                    )
                cursor.execute("ALTER TABLE case_obligations ENABLE TRIGGER no_delete_obligations")

            for key, spec in desired.items():
                if key in existing:
                    continue
                member = spec["member"]
                case = spec["case"]
                amount = spec["amount"]
                paid = bool(spec["paid"])
                timestamp = case_timestamp(case["death_date"])
                obligation_id = uuid.uuid4()
                cursor.execute(
                    """
                    INSERT INTO case_obligations (
                        id, death_case_id, member_id, taluk_id_snapshot,
                        responsible_agent_id, original_agent_id, required_amount,
                        collected_amount, verified_amount, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        obligation_id, case["id"], member["id"], taluk["id"],
                        assignment["agent_profile_id"], assignment["agent_profile_id"], amount,
                        amount if paid else Decimal("0"), amount if paid else Decimal("0"),
                        timestamp, timestamp,
                    ),
                )
                if paid:
                    case_sequence = int(case["case_number"].split("-")[1])
                    cursor.execute(
                        """
                        INSERT INTO collection_transactions (
                            id, receipt_number, collection_type, member_id, agent_profile_id,
                            taluk_id, case_obligation_id, permanent_account_id, amount, method,
                            external_reference, note, collected_at, status, created_by,
                            client_request_id, created_at, updated_at
                        ) VALUES (
                            %s, %s, 'DEATH_CONTRIBUTION', %s, %s, %s, %s, NULL, %s, 'OTHER',
                            %s, %s, %s, 'VERIFIED', %s, %s, %s, %s
                        )
                        """,
                        (
                            uuid.uuid4(), f"HRC-VKD-{case_sequence:03d}-{member['member_code']}",
                            member["id"], assignment["agent_profile_id"], taluk["id"], obligation_id,
                            amount, f"Historical case {case_sequence}",
                            "Verified payment reconstructed from pre-application records.",
                            timestamp, admin["id"],
                            uuid.uuid5(REQUEST_NAMESPACE, f"{case_sequence}:{member['id']}"),
                            timestamp, timestamp,
                        ),
                    )

            cursor.execute(
                """
                INSERT INTO audit_logs (
                    actor_profile_id, actor_role, action, entity_type, entity_id,
                    before_data, after_data, request_id, metadata
                ) VALUES (%s, 'ADMIN', 'HISTORICAL_VELLARIKUNDU_LEDGER_IMPORTED',
                          'historical_import', NULL, NULL, %s::jsonb, %s, %s::jsonb)
                """,
                (
                    admin["id"],
                    json.dumps({
                        "paid_obligations": len(paid_specs),
                        "verified_amount": str(paid_amount),
                        "pending_obligations": len(pending_specs),
                        "pending_amount": str(pending_amount),
                    }),
                    uuid.uuid4(), json.dumps({"source": "pre_application_records"}),
                ),
            )
        connection.commit()
    print("Historical Vellarikundu ledger imported atomically.")


if __name__ == "__main__":
    main()
