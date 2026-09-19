"""Validate a historical death-case CSV against the current production data."""

import argparse
import csv
import json
import re
import sys
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import psycopg
from psycopg.rows import dict_row


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402


PHONE_PATTERN = re.compile(r"^[0-9]{10}$")
TALUK_ALIASES = {
    "kasaragod": "Kasargod",
    "mukundhapuram": "Mukundapuram",
    "kottarakara": "Kottarakkara",
    "koyilandy": "Koyilandi",
    "chaganassery": "Changanassery",
    "thirurangadi": "Thirurangady",
    "thamarasseri": "Thamarassery",
    "thalasserry": "Thalassery",
    "vellarikunnu": "Vellarikundu",
}


def normalized_database_url() -> str:
    configured = get_settings().DATABASE_URL.replace(
        "postgresql+asyncpg://", "postgresql://", 1
    )
    parsed = urlsplit(configured)
    query = [
        ("sslmode" if key == "ssl" else key, value)
        for key, value in parse_qsl(parsed.query)
    ]
    return urlunsplit((*parsed[:3], urlencode(query), parsed.fragment))


def normalized_taluk(value: str) -> str:
    cleaned = value.strip()
    return TALUK_ALIASES.get(cleaned.casefold(), cleaned)


def load_rows(source: Path) -> list[dict[str, str]]:
    with source.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    required = {"legacy_no", "name", "taluk", "phone", "death_date", "amount"}
    if not rows or not required.issubset(rows[0]):
        raise SystemExit("CSV columns must be: " + ", ".join(sorted(required)))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--expected-count", type=int, required=True)
    args = parser.parse_args()
    rows = load_rows(args.source.resolve())
    if len(rows) != args.expected_count:
        raise SystemExit(f"Expected {args.expected_count} rows, found {len(rows)}.")

    with psycopg.connect(normalized_database_url(), row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id, name FROM taluks WHERE is_active ORDER BY name")
            taluks = cursor.fetchall()
            cursor.execute(
                "SELECT m.id, m.member_code, p.full_name, p.phone, t.name AS taluk_name, "
                "p.account_status::text AS account_status "
                "FROM members m JOIN profiles p ON p.id = m.profile_id "
                "JOIN taluks t ON t.id = m.taluk_id"
            )
            members = cursor.fetchall()

    taluk_names = {row["name"].casefold(): row["name"] for row in taluks}
    results = []
    for raw in rows:
        issues: list[str] = []
        phone = raw["phone"].strip()
        taluk = normalized_taluk(raw["taluk"])
        try:
            death_date = date.fromisoformat(raw["death_date"].strip())
            if death_date > date.today():
                issues.append("future_death_date")
        except ValueError:
            death_date = None
            issues.append("invalid_death_date")
        try:
            if Decimal(raw["amount"].strip()) <= 0:
                issues.append("invalid_amount")
        except InvalidOperation:
            issues.append("invalid_amount")
        if not PHONE_PATTERN.fullmatch(phone):
            issues.append("missing_phone" if not phone else "invalid_phone")
        if taluk.casefold() not in taluk_names:
            issues.append("unmapped_taluk")

        candidates = []
        if PHONE_PATTERN.fullmatch(phone):
            candidates = [member for member in members if member["phone"] == phone]
        if not candidates and taluk.casefold() in taluk_names:
            candidates = [
                member for member in members
                if member["full_name"].strip().casefold() == raw["name"].strip().casefold()
                and member["taluk_name"].casefold() == taluk.casefold()
            ]
        if not candidates:
            issues.append("member_not_found")
        elif len(candidates) > 1:
            issues.append("ambiguous_member_match")

        results.append({
            "legacy_no": int(raw["legacy_no"]),
            "normalized_taluk": taluk,
            "matched_member_code": candidates[0]["member_code"] if len(candidates) == 1 else None,
            "matched_account_status": candidates[0]["account_status"] if len(candidates) == 1 else None,
            "issues": issues,
        })

    issue_counts: dict[str, int] = {}
    for result in results:
        for issue in result["issues"]:
            issue_counts[issue] = issue_counts.get(issue, 0) + 1
    print(json.dumps({
        "mode": "read-only-validation",
        "source_rows": len(rows),
        "ready_rows": sum(not result["issues"] for result in results),
        "issue_counts": issue_counts,
        "records": results,
    }, indent=2))


if __name__ == "__main__":
    main()
