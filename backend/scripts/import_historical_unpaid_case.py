"""Atomically import one historical case with unpaid obligations for eligible members."""

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


CONFIRMATION = "IMPORT-HISTORICAL-UNPAID-CASE"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--case", type=int, required=True)
    parser.add_argument("--admin-login", default="admin")
    parser.add_argument("--expected-obligations", type=int)
    parser.add_argument("--expected-required-amount", type=Decimal)
    parser.add_argument("--confirm")
    args = parser.parse_args()
    apply_change = args.confirm == CONFIRMATION

    matching = [
        row for row in load_rows(args.source.resolve())
        if int(row["legacy_no"]) == args.case
    ]
    if len(matching) != 1:
        raise SystemExit(f"Expected exactly one source row for historical case {args.case}.")

    row = matching[0]
    death_date = date.fromisoformat(row["death_date"])
    amount = Decimal(row["amount"])
    case_number = f"HIST-{args.case:03d}"
    eligibility_cutoff = death_date.replace(day=1)

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
                """
                SELECT m.id, m.member_code::text, p.full_name, p.account_status::text,
                       m.deceased_at, t.name AS taluk_name
                FROM members m
                JOIN profiles p ON p.id = m.profile_id
                JOIN taluks t ON t.id = m.taluk_id
                WHERE p.phone = %s
                """,
                (row["phone"].strip(),),
            )
            deceased_matches = cursor.fetchall()
            if len(deceased_matches) != 1:
                raise SystemExit("Historical deceased member does not have one unique phone match.")
            deceased = deceased_matches[0]
            if deceased["full_name"].strip().casefold() != row["name"].strip().casefold():
                raise SystemExit("Historical deceased member name differs from the source row.")
            if deceased["taluk_name"].casefold() != normalized_taluk(row["taluk"]).casefold():
                raise SystemExit("Historical deceased member taluk differs from the source row.")
            if deceased["account_status"] != "DECEASED":
                raise SystemExit("Historical deceased member is not marked deceased.")
            if deceased["deceased_at"].date() != death_date:
                raise SystemExit("Historical deceased member death date differs from the source row.")

            cursor.execute(
                """
                SELECT m.id, m.member_code::text, m.taluk_id,
                       ata.agent_profile_id, t.name AS taluk_name
                FROM members m
                JOIN profiles p ON p.id = m.profile_id
                JOIN taluks t ON t.id = m.taluk_id AND t.is_active
                LEFT JOIN agent_taluk_assignments ata
                  ON ata.taluk_id = m.taluk_id AND ata.ends_at IS NULL
                WHERE p.account_status = 'ACTIVE'
                  AND m.joined_on < %s
                  AND m.id <> %s
                ORDER BY t.name, m.member_code
                """,
                (eligibility_cutoff, deceased["id"]),
            )
            eligible = cursor.fetchall()
            unassigned = sorted({member["taluk_name"] for member in eligible if member["agent_profile_id"] is None})
            if unassigned:
                raise SystemExit("Eligible members lack active agents in: " + ", ".join(unassigned))

            expected_required = amount * len(eligible)
            breakdown: dict[str, int] = {}
            for member in eligible:
                breakdown[member["taluk_name"]] = breakdown.get(member["taluk_name"], 0) + 1

            cursor.execute(
                "SELECT id FROM death_cases WHERE case_number = %s",
                (case_number,),
            )
            existing_case = cursor.fetchone()
            existing = {
                "obligations": 0,
                "required": Decimal("0"),
                "collected": Decimal("0"),
                "verified": Decimal("0"),
            }
            if existing_case:
                cursor.execute(
                    """
                    SELECT count(*) AS obligations,
                           coalesce(sum(required_amount), 0) AS required,
                           coalesce(sum(collected_amount), 0) AS collected,
                           coalesce(sum(verified_amount), 0) AS verified
                    FROM case_obligations WHERE death_case_id = %s
                    """,
                    (existing_case["id"],),
                )
                existing = cursor.fetchone()

            summary = {
                "mode": "apply" if apply_change else "dry-run",
                "case_number": case_number,
                "deceased_member_code": deceased["member_code"],
                "death_date": death_date.isoformat(),
                "contribution_amount": str(amount),
                "eligibility_cutoff": eligibility_cutoff.isoformat(),
                "eligible_obligations": len(eligible),
                "required_amount": str(expected_required),
                "taluk_breakdown": breakdown,
                "existing_case": existing_case is not None,
                "existing_obligations": existing["obligations"],
                "notifications_created": 0,
                "deposits_created": 0,
            }
            print(json.dumps(summary, indent=2))

            if existing_case:
                if (
                    existing["obligations"] != len(eligible)
                    or existing["required"] != expected_required
                    or existing["collected"] != 0
                    or existing["verified"] != 0
                ):
                    raise SystemExit("Existing historical case ledger differs from the source.")
                connection.rollback()
                print("Historical case already matches; no changes made.")
                return

            if not apply_change:
                connection.rollback()
                print(f'No changes made. Re-run with --confirm "{CONFIRMATION}" and expected totals.')
                return
            if args.expected_obligations != len(eligible):
                raise SystemExit("Expected-obligations guard does not match the dry-run result.")
            if args.expected_required_amount != expected_required:
                raise SystemExit("Expected-required-amount guard does not match the dry-run result.")

            cursor.execute(
                """
                SELECT coalesce(max(monthly_sequence), 0) + 1 AS next_sequence
                FROM death_cases WHERE sequence_month = %s
                """,
                (eligibility_cutoff,),
            )
            monthly_sequence = cursor.fetchone()["next_sequence"]
            case_id = uuid.uuid4()
            created_at = case_timestamp(death_date)
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
                    case_id, case_number, deceased["id"], death_date,
                    f"Historical helping request for {row['name'].strip()}",
                    "Historical case reconstructed from pre-application records.",
                    eligibility_cutoff, monthly_sequence, amount, amount,
                    admin["id"], created_at,
                ),
            )

            for member in eligible:
                cursor.execute(
                    """
                    INSERT INTO case_obligations (
                        id, death_case_id, member_id, taluk_id_snapshot,
                        responsible_agent_id, original_agent_id, required_amount,
                        collected_amount, verified_amount, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, 0, 0, %s, %s)
                    """,
                    (
                        uuid.uuid4(), case_id, member["id"], member["taluk_id"],
                        member["agent_profile_id"], member["agent_profile_id"], amount,
                        created_at, created_at,
                    ),
                )

            cursor.execute(
                """
                INSERT INTO monthly_case_counters (sequence_month, last_sequence, updated_at)
                VALUES (%s, %s, now())
                ON CONFLICT (sequence_month) DO UPDATE
                SET last_sequence = greatest(monthly_case_counters.last_sequence, excluded.last_sequence),
                    updated_at = now()
                """,
                (eligibility_cutoff, monthly_sequence),
            )
            cursor.execute(
                """
                INSERT INTO audit_logs (
                    actor_profile_id, actor_role, action, entity_type, entity_id,
                    before_data, after_data, request_id, metadata, created_at
                ) VALUES (
                    %s, 'ADMIN', 'HISTORICAL_UNPAID_CASE_IMPORTED', 'death_case', %s,
                    NULL, %s::jsonb, %s, %s::jsonb, %s
                )
                """,
                (
                    admin["id"], case_id,
                    json.dumps({
                        "case_number": case_number,
                        "legacy_no": args.case,
                        "amount": str(amount),
                        "obligations": len(eligible),
                        "required_amount": str(expected_required),
                    }),
                    uuid.uuid4(), json.dumps({"source": "pre_application_records"}), created_at,
                ),
            )
        connection.commit()
    print("Historical unpaid case and obligations imported atomically.")


if __name__ == "__main__":
    main()
