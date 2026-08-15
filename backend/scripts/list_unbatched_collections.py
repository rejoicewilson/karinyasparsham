"""List recorded collections that have not yet been submitted in a deposit."""

import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import psycopg


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402


def main() -> None:
    settings = get_settings()
    parsed = urlsplit(
        settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)
    )
    query = [("sslmode" if key == "ssl" else key, value) for key, value in parse_qsl(parsed.query)]
    database_url = urlunsplit((*parsed[:3], urlencode(query), parsed.fragment))

    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT ct.receipt_number, ct.amount, ct.collection_type::text,
                       ct.method::text, ct.status::text, mp.full_name, ap.login_id,
                       ct.collected_at, pma.collected_amount, pma.verified_amount,
                       pma.target_amount
                FROM collection_transactions ct
                JOIN members m ON m.id = ct.member_id
                JOIN profiles mp ON mp.id = m.profile_id
                JOIN profiles ap ON ap.id = ct.agent_profile_id
                LEFT JOIN permanent_membership_accounts pma ON pma.id = ct.permanent_account_id
                WHERE ct.status = 'RECORDED'
                ORDER BY ct.collected_at DESC
                """
            )
            for row in cursor.fetchall():
                print("|".join(str(value) for value in row))


if __name__ == "__main__":
    main()
