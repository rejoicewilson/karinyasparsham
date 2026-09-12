"""Safely deactivate a member account while retaining auditable ledger history."""

import argparse
import json
import secrets
import sys
import uuid
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
import psycopg
from psycopg.rows import dict_row


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402
from app.services.supabase_admin import service_headers  # noqa: E402


def database_url() -> str:
    configured = get_settings().DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)
    parsed = urlsplit(configured)
    query = [("sslmode" if key == "ssl" else key, value) for key, value in parse_qsl(parsed.query)]
    return urlunsplit((*parsed[:3], urlencode(query), parsed.fragment))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--login-id", required=True)
    parser.add_argument("--expected-member-code", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--confirm", help="Must exactly match the login ID to apply")
    args = parser.parse_args()
    login_id = args.login_id.strip().lower()
    apply_change = args.confirm == login_id

    with psycopg.connect(database_url(), row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT m.id AS member_id, m.member_code::text, m.taluk_id, p.id AS profile_id,
                       p.auth_user_id, p.account_status::text,
                       (SELECT count(*) FROM case_obligations co WHERE co.member_id = m.id) AS obligations,
                       (SELECT count(*) FROM collection_transactions ct WHERE ct.member_id = m.id) AS collections
                FROM profiles p
                JOIN members m ON m.profile_id = p.id
                WHERE lower(p.login_id::text) = lower(%s)
                FOR UPDATE OF p, m
                """,
                (login_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise SystemExit("Member login ID was not found.")
            if row["member_code"].casefold() != args.expected_member_code.strip().casefold():
                raise SystemExit("Member code does not match the requested login ID.")
            cursor.execute(
                """
                SELECT count(*)
                FROM members m
                JOIN profiles p ON p.id = m.profile_id
                WHERE m.taluk_id = %s AND p.account_status = 'ACTIVE'
                """,
                (row["taluk_id"],),
            )
            active_members = cursor.fetchone()["count"]
            print(json.dumps({
                "mode": "apply" if apply_change else "dry-run",
                "login_id": login_id,
                "member_code": row["member_code"],
                "current_status": row["account_status"],
                "obligations_retained": row["obligations"],
                "collections_retained": row["collections"],
                "active_members_in_taluk": active_members,
            }, indent=2))
            if not apply_change:
                connection.rollback()
                print(f'No changes made. Re-run with --confirm "{login_id}".')
                return
            if row["account_status"] != "INACTIVE":
                cursor.execute(
                    """
                    UPDATE profiles
                    SET account_status = 'INACTIVE', must_change_password = true
                    WHERE id = %s
                    """,
                    (row["profile_id"],),
                )
                cursor.execute(
                    """
                    INSERT INTO audit_logs (
                        actor_profile_id, actor_role, action, entity_type,
                        entity_id, before_data, after_data, request_id, metadata
                    )
                    SELECT id, 'ADMIN', 'MEMBER_DEACTIVATED', 'member', %s,
                           %s::jsonb, %s::jsonb, %s, %s::jsonb
                    FROM profiles
                    WHERE role = 'ADMIN' AND account_status = 'ACTIVE'
                    ORDER BY created_at
                    LIMIT 1
                    """,
                    (
                        row["member_id"],
                        json.dumps({"account_status": row["account_status"]}),
                        json.dumps({"account_status": "INACTIVE", "reason": args.reason.strip()}),
                        uuid.uuid4(),
                        json.dumps({"source": "member_deactivation_script"}),
                    ),
                )
        connection.commit()

    settings = get_settings()
    replacement_password = secrets.token_urlsafe(48)
    with httpx.Client(timeout=20) as client:
        response = client.put(
            f"{str(settings.SUPABASE_URL).rstrip('/')}/auth/v1/admin/users/{row['auth_user_id']}",
            headers=service_headers(),
            json={"password": replacement_password, "email_confirm": True},
        )
    if response.status_code != 200:
        raise SystemExit(
            "Member was deactivated in the app, but Auth credential invalidation failed "
            f"(HTTP {response.status_code}). Retry this command."
        )
    print("Member deactivated and Auth credentials invalidated.")


if __name__ == "__main__":
    main()
