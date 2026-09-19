"""Atomically import historical cases and fully paid Kasargod obligations."""

import argparse
import csv
import json
import sys
import uuid
from collections import defaultdict
from datetime import date, datetime, time, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import psycopg
from psycopg.rows import dict_row


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402
from validate_historical_deaths import load_rows, normalized_taluk  # noqa: E402


CONFIRMATION = "IMPORT-KASARGOD-CASES-1-23"
REQUEST_NAMESPACE = uuid.UUID("938d39c6-e751-4b89-af54-88d79fe4b2e2")


def database_url() -> str:
    configured = get_settings().DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)
    parsed = urlsplit(configured)
    query = [("sslmode" if key == "ssl" else key, value) for key, value in parse_qsl(parsed.query)]
    return urlunsplit((*parsed[:3], urlencode(query), parsed.fragment))


def case_timestamp(value: date) -> datetime:
    return datetime.combine(value, time(hour=12), tzinfo=timezone.utc)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--through-case", type=int, default=23)
    parser.add_argument("--taluk", default="Kasargod")
    parser.add_argument("--admin-login", default="admin")
    parser.add_argument("--excluded-member-code", default="KSD-M040")
    parser.add_argument("--expected-obligations", type=int, required=True)
    parser.add_argument("--expected-verified-amount", type=Decimal, required=True)
    parser.add_argument("--confirm")
    args = parser.parse_args()
    apply_change = args.confirm == CONFIRMATION

    source_rows = load_rows(args.source.resolve())
    selected = [row for row in source_rows if int(row["legacy_no"]) <= args.through_case]
    if [int(row["legacy_no"]) for row in selected] != list(range(1, args.through_case + 1)):
        raise SystemExit("Historical cases must be contiguous and ordered from 1.")

    monthly_sequence: dict[tuple[int, int], int] = defaultdict(int)
    case_specs = []
    for row in sorted(selected, key=lambda item: (date.fromisoformat(item["death_date"]), int(item["legacy_no"]))):
        death_date = date.fromisoformat(row["death_date"])
        month_key = (death_date.year, death_date.month)
        monthly_sequence[month_key] += 1
        case_specs.append({
            "legacy_no": int(row["legacy_no"]),
            "case_number": f"HIST-{int(row['legacy_no']):03d}",
            "name": row["name"].strip(),
            "phone": row["phone"].strip(),
            "source_taluk": normalized_taluk(row["taluk"]),
            "death_date": death_date,
            "sequence_month": death_date.replace(day=1),
            "monthly_sequence": monthly_sequence[month_key],
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

            case_numbers = [spec["case_number"] for spec in case_specs]
            cursor.execute(
                "SELECT case_number::text FROM death_cases WHERE case_number = ANY(%s)",
                (case_numbers,),
            )
            existing_case_numbers = {row["case_number"] for row in cursor.fetchall()}
            if existing_case_numbers and existing_case_numbers != set(case_numbers):
                raise SystemExit("A partial historical import already exists; no changes were made.")

            expected = []
            for spec in case_specs:
                cursor.execute(
                    """
                    SELECT m.id, m.member_code::text, m.taluk_id, p.full_name,
                           p.account_status::text, m.deceased_at, t.name AS taluk_name
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
                eligible_members = cursor.fetchall()
                expected.extend((spec, member) for member in eligible_members)

            expected_amount = sum((spec["amount"] for spec, _ in expected), Decimal("0"))
            if any(
                member["member_code"].casefold() == args.excluded_member_code.casefold()
                for _, member in expected
            ):
                raise SystemExit("The explicitly excluded member is unexpectedly eligible.")
            if len(expected) != args.expected_obligations:
                raise SystemExit(
                    f"Expected {args.expected_obligations} obligations, calculated {len(expected)}."
                )
            if expected_amount != args.expected_verified_amount:
                raise SystemExit(
                    f"Expected verified amount {args.expected_verified_amount}, calculated {expected_amount}."
                )
            cursor.execute(
                """
                SELECT count(*) AS obligations, coalesce(sum(co.verified_amount), 0) AS verified
                FROM case_obligations co JOIN death_cases dc ON dc.id = co.death_case_id
                WHERE dc.case_number = ANY(%s) AND co.taluk_id_snapshot = %s
                """,
                (case_numbers, target_taluk["id"]),
            )
            existing_totals = cursor.fetchone()
            cursor.execute(
                """
                SELECT count(*) AS collections, coalesce(sum(ct.amount), 0) AS verified
                FROM collection_transactions ct
                JOIN case_obligations co ON co.id = ct.case_obligation_id
                JOIN death_cases dc ON dc.id = co.death_case_id
                WHERE dc.case_number = ANY(%s) AND ct.taluk_id = %s AND ct.status = 'VERIFIED'
                """,
                (case_numbers, target_taluk["id"]),
            )
            existing_collections = cursor.fetchone()
            cursor.execute(
                """
                SELECT count(*) AS obligations
                FROM case_obligations co
                JOIN death_cases dc ON dc.id = co.death_case_id
                JOIN members m ON m.id = co.member_id
                WHERE dc.case_number = ANY(%s) AND m.member_code = %s
                """,
                (case_numbers, args.excluded_member_code),
            )
            excluded_obligations = cursor.fetchone()["obligations"]
            summary = {
                "mode": "apply" if apply_change else "dry-run",
                "historical_cases": len(case_specs),
                "kasargod_obligations": len(expected),
                "verified_amount": str(expected_amount),
                "existing_cases": len(existing_case_numbers),
                "existing_obligations": existing_totals["obligations"],
                "existing_verified_amount": str(existing_totals["verified"]),
                "existing_verified_collections": existing_collections["collections"],
                "existing_collection_amount": str(existing_collections["verified"]),
                "excluded_member_obligations": excluded_obligations,
                "notifications_created": 0,
                "deposits_created": 0,
            }
            print(json.dumps(summary, indent=2))

            if existing_case_numbers:
                if (
                    existing_totals["obligations"] != len(expected)
                    or existing_totals["verified"] != expected_amount
                    or existing_collections["collections"] != len(expected)
                    or existing_collections["verified"] != expected_amount
                    or excluded_obligations != 0
                ):
                    raise SystemExit("Existing historical ledger totals differ from the approved import.")
                connection.rollback()
                print("Historical Kasargod ledger already matches; no changes made.")
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
                obligation_id = uuid.uuid4()
                collected_at = case_timestamp(spec["death_date"])
                cursor.execute(
                    """
                    INSERT INTO case_obligations (
                        id, death_case_id, member_id, taluk_id_snapshot,
                        responsible_agent_id, original_agent_id, required_amount,
                        collected_amount, verified_amount, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        obligation_id, case_ids[spec["legacy_no"]], member["id"], target_taluk["id"],
                        assignment["agent_profile_id"], assignment["agent_profile_id"], spec["amount"],
                        spec["amount"], spec["amount"], collected_at, collected_at,
                    ),
                )
                receipt_number = f"HRC-{spec['legacy_no']:03d}-{member['member_code']}"
                client_request_id = uuid.uuid5(
                    REQUEST_NAMESPACE, f"{spec['legacy_no']}:{member['id']}"
                )
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
                        uuid.uuid4(), receipt_number, member["id"], assignment["agent_profile_id"],
                        target_taluk["id"], obligation_id, spec["amount"],
                        f"Historical case {spec['legacy_no']}",
                        "Verified payment reconstructed from pre-application records.",
                        collected_at, admin["id"], client_request_id, collected_at, collected_at,
                    ),
                )

            cursor.execute(
                """
                INSERT INTO audit_logs (
                    actor_profile_id, actor_role, action, entity_type, entity_id,
                    before_data, after_data, request_id, metadata
                ) VALUES (%s, 'ADMIN', 'HISTORICAL_KASARGOD_PAYMENTS_IMPORTED', 'historical_import',
                          NULL, NULL, %s::jsonb, %s, %s::jsonb)
                """,
                (
                    admin["id"],
                    json.dumps({
                        "through_case": args.through_case,
                        "obligations": len(expected),
                        "verified_amount": str(expected_amount),
                    }),
                    uuid.uuid4(), json.dumps({"source": "pre_application_records"}),
                ),
            )
        connection.commit()
    print("Historical Kasargod cases and verified payments imported atomically.")


if __name__ == "__main__":
    main()
