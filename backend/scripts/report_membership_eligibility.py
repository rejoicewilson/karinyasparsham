"""Report joining-date distribution and historical obligation eligibility conflicts."""

import json
import sys
from pathlib import Path

import psycopg
from psycopg.rows import dict_row


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend" / "scripts"))

from import_historical_kasargod_payments import database_url  # noqa: E402


def main() -> None:
    with psycopg.connect(database_url(), row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT t.name AS taluk, m.joined_on, count(*) AS members
                FROM members m
                JOIN profiles p ON p.id = m.profile_id
                JOIN taluks t ON t.id = m.taluk_id
                WHERE p.account_status <> 'DECEASED'
                GROUP BY t.name, m.joined_on
                ORDER BY t.name, m.joined_on
                """
            )
            distribution = cursor.fetchall()
            cursor.execute(
                """
                SELECT count(*) AS obligations,
                       coalesce(sum(co.required_amount), 0) AS required_amount
                FROM case_obligations co
                JOIN death_cases dc ON dc.id = co.death_case_id
                JOIN members m ON m.id = co.member_id
                WHERE dc.case_number::text LIKE 'HIST-%'
                  AND m.joined_on >= date_trunc('month', dc.death_date)::date
                """
            )
            conflicts = cursor.fetchone()
    print(json.dumps({
        "active_or_inactive_member_joining_dates": [
            {
                "taluk": row["taluk"],
                "joined_on": row["joined_on"].isoformat(),
                "members": row["members"],
            }
            for row in distribution
        ],
        "historical_obligations_conflicting_with_new_rule": conflicts["obligations"],
        "conflicting_required_amount": str(conflicts["required_amount"]),
    }, indent=2))


if __name__ == "__main__":
    main()
