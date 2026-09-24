"""Reconstruct a taluk ledger when every active member paid through one case."""

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


CONFIRMATION = "IMPORT-UNIFORM-HISTORICAL-TALUK-LEDGER"
REQUEST_NAMESPACE = uuid.UUID("a45e194c-6a2c-49a4-95f3-519d2154dc96")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--taluk", required=True)
    parser.add_argument("--paid-through-case", type=int, required=True)
    parser.add_argument("--through-case", type=int, required=True)
    parser.add_argument("--receipt-prefix", required=True)
    parser.add_argument("--dropped-member-code")
    parser.add_argument("--dropped-paid-through-case", type=int)
    parser.add_argument("--excluded-member-code")
    parser.add_argument("--admin-login", default="admin")
    parser.add_argument("--expected-members", type=int)
    parser.add_argument("--expected-paid-obligations", type=int)
    parser.add_argument("--expected-verified-amount", type=Decimal)
    parser.add_argument("--expected-pending-obligations", type=int)
    parser.add_argument("--expected-pending-amount", type=Decimal)
    parser.add_argument("--confirm")
    args = parser.parse_args()
    apply_change = args.confirm == CONFIRMATION

    if args.paid_through_case < 0 or args.paid_through_case > args.through_case:
        raise SystemExit("Paid-through case must be between zero and through-case.")
    if (args.dropped_member_code is None) != (args.dropped_paid_through_case is None):
        raise SystemExit("Dropped member code and paid-through case must be supplied together.")
    if args.dropped_paid_through_case is not None and not (
        0 <= args.dropped_paid_through_case <= args.paid_through_case
    ):
        raise SystemExit("Dropped member paid-through case is outside the allowed range.")
    source_rows = load_rows(args.source.resolve())
    selected_rows = [row for row in source_rows if int(row["legacy_no"]) <= args.through_case]
    if [int(row["legacy_no"]) for row in selected_rows] != list(range(1, args.through_case + 1)):
        raise SystemExit("Historical source cases must be contiguous from case 1.")
    case_amounts = {
        f"HIST-{int(row['legacy_no']):03d}": Decimal(row["amount"])
        for row in selected_rows
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
                raise SystemExit(f"Active taluk {args.taluk!r} was not found.")
            cursor.execute(
                "SELECT agent_profile_id FROM agent_taluk_assignments "
                "WHERE taluk_id = %s AND ends_at IS NULL",
                (taluk["id"],),
            )
            assignment = cursor.fetchone()
            if assignment is None:
                raise SystemExit(f"{args.taluk} does not have an active agent assignment.")

            cursor.execute(
                """
                SELECT m.id, m.member_code::text, p.account_status::text
                FROM members m
                JOIN profiles p ON p.id = m.profile_id
                WHERE m.taluk_id = %s
                ORDER BY m.member_code
                """,
                (taluk["id"],),
            )
            members = cursor.fetchall()
            dropped = None
            if args.dropped_member_code:
                matches = [
                    member for member in members
                    if member["member_code"].casefold() == args.dropped_member_code.casefold()
                ]
                if len(matches) != 1:
                    raise SystemExit("Dropped member code did not match exactly one member.")
                dropped = matches[0]
            excluded = None
            if args.excluded_member_code:
                matches = [
                    member for member in members
                    if member["member_code"].casefold() == args.excluded_member_code.casefold()
                ]
                if len(matches) != 1:
                    raise SystemExit("Excluded member code did not match exactly one member.")
                excluded = matches[0]
                if dropped is not None and excluded["id"] == dropped["id"]:
                    raise SystemExit("Dropped and excluded members must be different.")
            non_active = [
                member["member_code"] for member in members
                if member["account_status"] != "ACTIVE"
                and not (
                    dropped is not None
                    and member["id"] == dropped["id"]
                    and member["account_status"] == "INACTIVE"
                )
            ]
            if non_active:
                raise SystemExit("Every member must be active for this uniform import: " + ", ".join(non_active))

            cursor.execute(
                """
                SELECT id, case_number::text, death_date, contribution_amount
                FROM death_cases
                WHERE case_number::text = ANY(%s)
                ORDER BY case_number
                """,
                (list(case_amounts),),
            )
            cases = cursor.fetchall()
            case_by_number = {case["case_number"]: case for case in cases}
            if set(case_by_number) != set(case_amounts):
                raise SystemExit("Database historical cases do not match the requested source range.")
            for case_number, amount in case_amounts.items():
                if case_by_number[case_number]["contribution_amount"] != amount:
                    raise SystemExit(f"{case_number} amount differs from the source.")

            desired = {}
            paid_specs = []
            pending_specs = []
            for member in members:
                if excluded is not None and member["id"] == excluded["id"]:
                    continue
                is_dropped = dropped is not None and member["id"] == dropped["id"]
                member_paid_through = (
                    args.dropped_paid_through_case if is_dropped else args.paid_through_case
                )
                member_through = member_paid_through if is_dropped else args.through_case
                for sequence in range(1, member_through + 1):
                    case = case_by_number[f"HIST-{sequence:03d}"]
                    paid = sequence <= member_paid_through
                    spec = {
                        "member": member,
                        "case": case,
                        "sequence": sequence,
                        "amount": case["contribution_amount"],
                        "paid": paid,
                    }
                    desired[(member["id"], case["id"])] = spec
                    (paid_specs if paid else pending_specs).append(spec)

            cursor.execute(
                """
                SELECT co.id, co.member_id, co.death_case_id, co.taluk_id_snapshot,
                       co.required_amount, co.collected_amount, co.verified_amount,
                       m.member_code::text, dc.case_number::text,
                       (SELECT count(*) FROM collection_transactions ct
                        WHERE ct.case_obligation_id = co.id) AS collection_count,
                       (SELECT count(*) FROM collection_transactions ct
                        WHERE ct.case_obligation_id = co.id AND ct.status = 'VERIFIED') AS verified_collection_count,
                       (SELECT coalesce(sum(ct.amount), 0) FROM collection_transactions ct
                        WHERE ct.case_obligation_id = co.id AND ct.status = 'VERIFIED') AS verified_collection_amount
                FROM case_obligations co
                JOIN members m ON m.id = co.member_id
                JOIN death_cases dc ON dc.id = co.death_case_id
                WHERE m.taluk_id = %s AND dc.case_number::text = ANY(%s)
                """,
                (taluk["id"], list(case_amounts)),
            )
            existing_rows = cursor.fetchall()
            existing = {(row["member_id"], row["death_case_id"]): row for row in existing_rows}
            extras = [row for key, row in existing.items() if key not in desired]
            if extras:
                raise SystemExit("Unexpected existing historical obligations were found.")

            missing_paid = [spec for key, spec in desired.items() if spec["paid"] and key not in existing]
            missing_pending = [spec for key, spec in desired.items() if not spec["paid"] and key not in existing]
            for key, spec in desired.items():
                row = existing.get(key)
                if row is None:
                    continue
                amount = spec["amount"]
                paid = bool(spec["paid"])
                if row["taluk_id_snapshot"] != taluk["id"] or row["required_amount"] != amount:
                    raise SystemExit(f"Existing obligation differs for {row['member_code']} {row['case_number']}.")
                if paid and (
                    row["collected_amount"] != amount
                    or row["verified_amount"] != amount
                    or row["collection_count"] != 1
                    or row["verified_collection_count"] != 1
                    or row["verified_collection_amount"] != amount
                ):
                    raise SystemExit(f"Existing paid ledger differs for {row['member_code']} {row['case_number']}.")
                if not paid and (
                    row["collected_amount"] != 0
                    or row["verified_amount"] != 0
                    or row["collection_count"] != 0
                ):
                    raise SystemExit(f"Existing pending ledger differs for {row['member_code']} {row['case_number']}.")

            paid_amount = sum((spec["amount"] for spec in paid_specs), Decimal("0"))
            pending_amount = sum((spec["amount"] for spec in pending_specs), Decimal("0"))
            summary = {
                "mode": "apply" if apply_change else "dry-run",
                "taluk": args.taluk,
                "members": len(members),
                "paid_through_case": args.paid_through_case,
                "through_case": args.through_case,
                "dropped_member_code": dropped["member_code"] if dropped else None,
                "dropped_paid_through_case": args.dropped_paid_through_case,
                "excluded_member_code": excluded["member_code"] if excluded else None,
                "dropped_member_will_be_inactive": bool(
                    dropped and dropped["account_status"] != "INACTIVE"
                ),
                "paid_obligations": len(paid_specs),
                "verified_amount": str(paid_amount),
                "pending_obligations": len(pending_specs),
                "pending_amount": str(pending_amount),
                "existing_obligations": len(existing_rows),
                "missing_paid_obligations": len(missing_paid),
                "missing_pending_obligations": len(missing_pending),
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

            if dropped and dropped["account_status"] != "INACTIVE":
                cursor.execute(
                    "UPDATE profiles SET account_status = 'INACTIVE', must_change_password = false "
                    "WHERE id = (SELECT profile_id FROM members WHERE id = %s)",
                    (dropped["id"],),
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
                        admin["id"], dropped["id"],
                        json.dumps({"account_status": dropped["account_status"]}),
                        json.dumps({
                            "account_status": "INACTIVE",
                            "paid_through_case": args.dropped_paid_through_case,
                        }),
                        uuid.uuid4(), json.dumps({"source": "pre_application_records"}),
                    ),
                )

            for key, spec in desired.items():
                if key in existing:
                    continue
                member = spec["member"]
                case = spec["case"]
                sequence = spec["sequence"]
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
                            uuid.uuid4(), f"{args.receipt_prefix}-{sequence:03d}-{member['member_code']}",
                            member["id"], assignment["agent_profile_id"], taluk["id"], obligation_id,
                            amount, f"Historical case {sequence}",
                            "Verified payment reconstructed from pre-application records.",
                            timestamp, admin["id"],
                            uuid.uuid5(
                                REQUEST_NAMESPACE,
                                f"{args.taluk.casefold()}:{sequence}:{member['id']}",
                            ),
                            timestamp, timestamp,
                        ),
                    )

            cursor.execute(
                """
                INSERT INTO audit_logs (
                    actor_profile_id, actor_role, action, entity_type, entity_id,
                    before_data, after_data, request_id, metadata
                ) VALUES (%s, 'ADMIN', 'UNIFORM_HISTORICAL_TALUK_LEDGER_IMPORTED',
                          'historical_import', NULL, NULL, %s::jsonb, %s, %s::jsonb)
                """,
                (
                    admin["id"],
                    json.dumps({
                        "taluk": args.taluk,
                        "members": len(members),
                        "paid_through_case": args.paid_through_case,
                        "through_case": args.through_case,
                        "dropped_member_code": dropped["member_code"] if dropped else None,
                        "dropped_paid_through_case": args.dropped_paid_through_case,
                        "excluded_member_code": excluded["member_code"] if excluded else None,
                        "paid_obligations": len(paid_specs),
                        "verified_amount": str(paid_amount),
                        "pending_obligations": len(pending_specs),
                        "pending_amount": str(pending_amount),
                    }),
                    uuid.uuid4(), json.dumps({"source": "pre_application_records"}),
                ),
            )
        connection.commit()
    print(f"Historical {args.taluk} ledger imported atomically.")


if __name__ == "__main__":
    main()
