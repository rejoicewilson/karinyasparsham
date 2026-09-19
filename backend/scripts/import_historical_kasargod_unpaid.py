"""Atomically import historical cases 24-34 as unpaid Kasargod obligations."""

import argparse
import json
import sys
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg.rows import dict_row


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from import_historical_kasargod_payments import case_timestamp, database_url  # noqa: E402
from validate_historical_deaths import load_rows, normalized_taluk  # noqa: E402


CONFIRMATION = "IMPORT-KASARGOD-UNPAID-CASES-24-34"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--from-case", type=int, default=24)
    parser.add_argument("--through-case", type=int, default=34)
    parser.add_argument("--taluk", default="Kasargod")
    parser.add_argument("--admin-login", default="admin")
    parser.add_argument("--newly-eligible-member-code", default="KSD-M040")
    parser.add_argument("--expected-obligations", type=int, required=True)
    parser.add_argument("--expected-required-amount", type=Decimal, required=True)
    parser.add_argument("--confirm")
    args = parser.parse_args()
    apply_change = args.confirm == CONFIRMATION

    source_rows = load_rows(args.source.resolve())
    selected = [
        row for row in source_rows
        if args.from_case <= int(row["legacy_no"]) <= args.through_case
    ]
    expected_sequence = list(range(args.from_case, args.through_case + 1))
    if [int(row["legacy_no"]) for row in selected] != expected_sequence:
        raise SystemExit("Historical case range is incomplete or out of order.")

    case_specs = []
    for row in sorted(selected, key=lambda item: (date.fromisoformat(item["death_date"]), int(item["legacy_no"]))):
        death_date = date.fromisoformat(row["death_date"])
        case_specs.append({
            "legacy_no": int(row["legacy_no"]),
            "case_number": f"HIST-{int(row['legacy_no']):03d}",
            "name": row["name"].strip(),
            "phone": row["phone"].strip(),
            "source_taluk": normalized_taluk(row["taluk"]),
            "death_date": death_date,
            "sequence_month": death_date.replace(day=1),
            "amount": Decimal(row["amount"]),
        })
    case_specs.sort(key=lambda item: item["legacy_no"])

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
            target_taluk = cursor.fetchone()
            if target_taluk is None:
                raise SystemExit("Target taluk was not found.")
            cursor.execute(
                "SELECT agent_profile_id FROM agent_taluk_assignments "
                "WHERE taluk_id = %s AND ends_at IS NULL",
                (target_taluk["id"],),
            )
            assignment = cursor.fetchone()
            if assignment is None:
                raise SystemExit("Target taluk does not have an active agent assignment.")

            sequence_months = sorted({spec["sequence_month"] for spec in case_specs})
            cursor.execute(
                """
                SELECT sequence_month, max(monthly_sequence) AS last_sequence
                FROM death_cases
                WHERE sequence_month = ANY(%s)
                GROUP BY sequence_month
                """,
                (sequence_months,),
            )
            monthly_sequence = {
                row["sequence_month"]: row["last_sequence"] for row in cursor.fetchall()
            }
            for spec in sorted(case_specs, key=lambda item: (item["death_date"], item["legacy_no"])):
                next_sequence = monthly_sequence.get(spec["sequence_month"], 0) + 1
                monthly_sequence[spec["sequence_month"]] = next_sequence
                spec["monthly_sequence"] = next_sequence

            case_numbers = [spec["case_number"] for spec in case_specs]
            cursor.execute(
                "SELECT case_number::text FROM death_cases WHERE case_number = ANY(%s)",
                (case_numbers,),
            )
            existing_case_numbers = {row["case_number"] for row in cursor.fetchall()}
            if existing_case_numbers and existing_case_numbers != set(case_numbers):
                raise SystemExit("A partial unpaid historical import exists; no changes were made.")

            expected = []
            for spec in case_specs:
                cursor.execute(
                    """
                    SELECT m.id, m.member_code::text, p.account_status::text,
                           m.deceased_at, t.name AS taluk_name
                    FROM members m JOIN profiles p ON p.id = m.profile_id
                    JOIN taluks t ON t.id = m.taluk_id
                    WHERE p.phone = %s
                    """,
                    (spec["phone"],),
                )
                deceased_matches = cursor.fetchall()
                if len(deceased_matches) != 1:
                    raise SystemExit(
                        f"Historical case {spec['legacy_no']} does not have one unique phone match."
                    )
                deceased = deceased_matches[0]
                if deceased["taluk_name"].casefold() != spec["source_taluk"].casefold():
                    raise SystemExit(f"Historical case {spec['legacy_no']} taluk differs from the member record.")
                if deceased["account_status"] != "DECEASED":
                    raise SystemExit(f"Historical case {spec['legacy_no']} member is not marked deceased.")
                if deceased["deceased_at"].date() != spec["death_date"]:
                    raise SystemExit(f"Historical case {spec['legacy_no']} death date differs from the member record.")
                spec["deceased_member_id"] = deceased["id"]

                cursor.execute(
                    """
                    SELECT m.id, m.member_code::text
                    FROM members m JOIN profiles p ON p.id = m.profile_id
                    WHERE m.taluk_id = %s
                      AND m.joined_on <= %s
                      AND (m.deceased_at IS NULL OR m.deceased_at::date > %s)
                      AND m.id <> %s
                    ORDER BY m.member_code
                    """,
                    (
                        target_taluk["id"], spec["death_date"], spec["death_date"],
                        spec["deceased_member_id"],
                    ),
                )
                expected.extend((spec, member) for member in cursor.fetchall())

            expected_amount = sum((spec["amount"] for spec, _ in expected), Decimal("0"))
            newly_eligible_cases = [
                spec["legacy_no"] for spec, member in expected
                if member["member_code"].casefold() == args.newly_eligible_member_code.casefold()
            ]
            if newly_eligible_cases != [34]:
                raise SystemExit(
                    "The newly eligible member must have exactly one obligation, for case 34."
                )
            if len(expected) != args.expected_obligations:
                raise SystemExit(
                    f"Expected {args.expected_obligations} obligations, calculated {len(expected)}."
                )
            if expected_amount != args.expected_required_amount:
                raise SystemExit(
                    f"Expected required amount {args.expected_required_amount}, calculated {expected_amount}."
                )

            cursor.execute(
                """
                SELECT count(*) AS obligations,
                       coalesce(sum(co.required_amount), 0) AS required,
                       coalesce(sum(co.collected_amount), 0) AS collected,
                       coalesce(sum(co.verified_amount), 0) AS verified
                FROM case_obligations co JOIN death_cases dc ON dc.id = co.death_case_id
                WHERE dc.case_number = ANY(%s) AND co.taluk_id_snapshot = %s
                """,
                (case_numbers, target_taluk["id"]),
            )
            existing_totals = cursor.fetchone()
            cursor.execute(
                """
                SELECT count(*) AS collections
                FROM collection_transactions ct
                JOIN case_obligations co ON co.id = ct.case_obligation_id
                JOIN death_cases dc ON dc.id = co.death_case_id
                WHERE dc.case_number = ANY(%s) AND ct.taluk_id = %s
                """,
                (case_numbers, target_taluk["id"]),
            )
            existing_collections = cursor.fetchone()["collections"]
            cursor.execute(
                """
                SELECT count(*) AS obligations
                FROM case_obligations co
                JOIN death_cases dc ON dc.id = co.death_case_id
                JOIN members m ON m.id = co.member_id
                WHERE dc.case_number = ANY(%s) AND m.member_code = %s
                """,
                (case_numbers, args.newly_eligible_member_code),
            )
            newly_eligible_existing = cursor.fetchone()["obligations"]

            summary = {
                "mode": "apply" if apply_change else "dry-run",
                "historical_cases": len(case_specs),
                "kasargod_unpaid_obligations": len(expected),
                "outstanding_amount": str(expected_amount),
                "newly_eligible_member_cases": newly_eligible_cases,
                "existing_cases": len(existing_case_numbers),
                "existing_obligations": existing_totals["obligations"],
                "existing_required": str(existing_totals["required"]),
                "existing_collected": str(existing_totals["collected"]),
                "existing_verified": str(existing_totals["verified"]),
                "existing_collections": existing_collections,
                "notifications_created": 0,
                "deposits_created": 0,
            }
            print(json.dumps(summary, indent=2))

            if existing_case_numbers:
                if (
                    existing_totals["obligations"] != len(expected)
                    or existing_totals["required"] != expected_amount
                    or existing_totals["collected"] != 0
                    or existing_totals["verified"] != 0
                    or existing_collections != 0
                    or newly_eligible_existing != 1
                ):
                    raise SystemExit("Existing unpaid historical ledger differs from the approved import.")
                connection.rollback()
                print("Historical Kasargod unpaid ledger already matches; no changes made.")
                return
            if not apply_change:
                connection.rollback()
                print(f'No changes made. Re-run with --confirm "{CONFIRMATION}".')
                return

            case_ids = {}
            for spec in case_specs:
                case_id = uuid.uuid4()
                case_ids[spec["legacy_no"]] = case_id
                created_at = case_timestamp(spec["death_date"])
                cursor.execute(
                    """
                    INSERT INTO death_cases (
                        id, case_number, deceased_member_id, death_date, title, details,
                        photo_object_path, sequence_month, monthly_sequence, default_amount,
                        contribution_amount, is_amount_overridden, status, created_by, created_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, '', %s, %s, %s, %s, false,
                        'OPEN', %s, %s
                    )
                    """,
                    (
                        case_id, spec["case_number"], spec["deceased_member_id"], spec["death_date"],
                        f"Historical helping request for {spec['name']}",
                        "Historical case reconstructed from pre-application records.",
                        spec["sequence_month"], spec["monthly_sequence"], spec["amount"],
                        spec["amount"], admin["id"], created_at,
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO audit_logs (
                        actor_profile_id, actor_role, action, entity_type, entity_id,
                        before_data, after_data, request_id, metadata, created_at
                    ) VALUES (%s, 'ADMIN', 'HISTORICAL_DEATH_CASE_IMPORTED', 'death_case', %s,
                              NULL, %s::jsonb, %s, %s::jsonb, %s)
                    """,
                    (
                        admin["id"], case_id,
                        json.dumps({
                            "case_number": spec["case_number"],
                            "legacy_no": spec["legacy_no"],
                            "amount": str(spec["amount"]),
                        }),
                        uuid.uuid4(), json.dumps({"source": "pre_application_records"}), created_at,
                    ),
                )

            for spec, member in expected:
                created_at = case_timestamp(spec["death_date"])
                cursor.execute(
                    """
                    INSERT INTO case_obligations (
                        id, death_case_id, member_id, taluk_id_snapshot,
                        responsible_agent_id, original_agent_id, required_amount,
                        collected_amount, verified_amount, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, 0, 0, %s, %s)
                    """,
                    (
                        uuid.uuid4(), case_ids[spec["legacy_no"]], member["id"], target_taluk["id"],
                        assignment["agent_profile_id"], assignment["agent_profile_id"],
                        spec["amount"], created_at, created_at,
                    ),
                )

            cursor.execute(
                """
                INSERT INTO audit_logs (
                    actor_profile_id, actor_role, action, entity_type, entity_id,
                    before_data, after_data, request_id, metadata
                ) VALUES (%s, 'ADMIN', 'HISTORICAL_KASARGOD_UNPAID_IMPORTED', 'historical_import',
                          NULL, NULL, %s::jsonb, %s, %s::jsonb)
                """,
                (
                    admin["id"],
                    json.dumps({
                        "from_case": args.from_case,
                        "through_case": args.through_case,
                        "obligations": len(expected),
                        "outstanding_amount": str(expected_amount),
                    }),
                    uuid.uuid4(), json.dumps({"source": "pre_application_records"}),
                ),
            )
        connection.commit()
    print("Historical Kasargod unpaid cases and obligations imported atomically.")


if __name__ == "__main__":
    main()
