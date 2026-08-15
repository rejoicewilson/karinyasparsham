"""List application profile counts by role and account status."""

import argparse
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import psycopg


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--details", action="store_true", help="List each user's login ID and name.")
    args = parser.parse_args()
    settings = get_settings()
    parsed = urlsplit(
        settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)
    )
    query = [("sslmode" if key == "ssl" else key, value) for key, value in parse_qsl(parsed.query)]
    database_url = urlunsplit((*parsed[:3], urlencode(query), parsed.fragment))

    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            if args.details:
                cursor.execute(
                    """
                    SELECT role::text, login_id, full_name, account_status::text
                    FROM profiles
                    ORDER BY role, login_id
                    """
                )
                for role, login_id, full_name, account_status in cursor.fetchall():
                    print(f"{role}|{login_id}|{full_name}|{account_status}")
                return
            cursor.execute(
                """
                SELECT role::text, account_status::text, count(*)
                FROM profiles
                GROUP BY role, account_status
                ORDER BY role, account_status
                """
            )
            for role, account_status, count in cursor.fetchall():
                print(f"{role}|{account_status}|{count}")


if __name__ == "__main__":
    main()
