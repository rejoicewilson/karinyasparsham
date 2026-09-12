"""Reversibly archive the current test workspace while retaining its sole admin."""

import argparse
import json
import sys
import uuid
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import psycopg
from psycopg.rows import dict_row


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402


CONFIRMATION = "ARCHIVE CURRENT TEST DATA"


def database_url() -> str:
    configured = get_settings().DATABASE_URL.replace(
        "postgresql+asyncpg://", "postgresql://", 1
    )
    parsed = urlsplit(configured)
    query = [
        ("sslmode" if key == "ssl" else key, value)
        for key, value in parse_qsl(parsed.query)
    ]
    return urlunsplit((*parsed[:3], urlencode(query), parsed.fragment))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admin-login", default="admin")
    parser.add_argument("--backup-dir", type=Path, required=True)
    parser.add_argument("--confirm", help=f'Required value: "{CONFIRMATION}"')
    args = parser.parse_args()

    manifest_path = args.backup_dir.resolve() / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"Verified backup manifest was not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not manifest.get("table_counts") or not manifest.get("files"):
        raise SystemExit("Backup manifest is incomplete; archive was refused.")

    apply_archive = args.confirm == CONFIRMATION
    with psycopg.connect(database_url(), row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, login_id, full_name
                FROM profiles
                WHERE role = 'ADMIN' AND account_status = 'ACTIVE'
                FOR UPDATE
                """
            )
            active_admins = cursor.fetchall()
            matching_admins = [
                item for item in active_admins
                if item["login_id"].lower() == args.admin_login.strip().lower()
            ]
            if len(active_admins) != 1 or len(matching_admins) != 1:
                raise SystemExit(
                    "Archive requires exactly one active Admin matching --admin-login."
                )
            admin = matching_admins[0]

            count_queries = {
                "non_admin_profiles": "SELECT count(*) FROM profiles WHERE role <> 'ADMIN'",
                "taluks": "SELECT count(*) FROM taluks WHERE is_active",
                "active_assignments": (
                    "SELECT count(*) FROM agent_taluk_assignments WHERE ends_at IS NULL"
                ),
                "active_banks": "SELECT count(*) FROM bank_accounts WHERE ends_at IS NULL",
                "death_cases": "SELECT count(*) FROM death_cases",
                "collections": "SELECT count(*) FROM collection_transactions",
                "deposits": "SELECT count(*) FROM deposit_batches",
                "notifications": "SELECT count(*) FROM notification_recipients",
            }
            counts = {}
            for name, query in count_queries.items():
                cursor.execute(query)
                counts[name] = cursor.fetchone()["count"]

            print(json.dumps({
                "mode": "apply" if apply_archive else "dry-run",
                "admin_retained": admin["login_id"],
                "backup": str(manifest_path),
                "records": counts,
            }, indent=2, default=str))
            if not apply_archive:
                connection.rollback()
                print(f'No changes made. Re-run with --confirm "{CONFIRMATION}".')
                return

            cursor.execute("SELECT clock_timestamp() AS archived_at")
            archived_at = cursor.fetchone()["archived_at"]
            archive_tag = archived_at.strftime("%Y%m%d%H%M%S")

            cursor.execute(
                """
                UPDATE notification_recipients
                SET recipient_payload = coalesce(recipient_payload, '{}'::jsonb)
                    || jsonb_build_object('archived', true, 'archived_at', %s::text),
                    read_at = coalesce(read_at, %s),
                    push_status = 'ARCHIVED'
                """,
                (archived_at.isoformat(), archived_at),
            )
            cursor.execute(
                """
                UPDATE notification_outbox o
                SET status = 'SENT', locked_at = NULL,
                    last_error = 'Archived before production data entry'
                FROM notification_recipients r
                WHERE r.id = o.recipient_id
                  AND (r.recipient_payload ->> 'archived')::boolean IS TRUE
                """
            )
            cursor.execute(
                """
                UPDATE push_subscriptions ps
                SET revoked_at = coalesce(revoked_at, %s)
                FROM profiles p
                WHERE p.id = ps.profile_id AND p.role <> 'ADMIN'
                """,
                (archived_at,),
            )
            cursor.execute(
                "UPDATE agent_taluk_assignments SET ends_at = %s WHERE ends_at IS NULL",
                (archived_at,),
            )
            cursor.execute(
                "UPDATE bank_accounts SET ends_at = %s WHERE ends_at IS NULL",
                (archived_at,),
            )
            cursor.execute(
                """
                UPDATE death_cases
                SET status = 'CANCELLED', cancelled_at = coalesce(cancelled_at, %s)
                WHERE status <> 'CANCELLED'
                """,
                (archived_at,),
            )
            cursor.execute(
                """
                UPDATE profiles
                SET account_status = 'INACTIVE'
                WHERE role <> 'ADMIN' AND account_status <> 'INACTIVE'
                """
            )
            cursor.execute(
                """
                UPDATE members
                SET member_code = concat(
                    'ARCHIVED-', %s::text, '-', left(id::text, 8), '-', member_code
                )
                WHERE member_code NOT LIKE 'ARCHIVED-%%'
                """,
                (archive_tag,),
            )
            cursor.execute(
                """
                UPDATE taluks
                SET code = concat(
                        'ARCHIVED-', %s::text, '-', left(id::text, 8), '-', code
                    ),
                    name = concat('[Archived ', %s::text, '] ', name),
                    is_active = false
                WHERE is_active
                """,
                (archive_tag, archive_tag),
            )

            boundary = {
                "archived_at": archived_at.isoformat(),
                "archive_tag": archive_tag,
                "admin_login": admin["login_id"],
                "backup_manifest": str(manifest_path),
                "counts": counts,
            }
            cursor.execute(
                """
                INSERT INTO app_settings (key, value, description, updated_by)
                VALUES ('production_data_boundary', %s::jsonb,
                        'Boundary between archived testing data and real production data', %s)
                ON CONFLICT (key) DO UPDATE
                SET value = excluded.value,
                    description = excluded.description,
                    updated_by = excluded.updated_by
                """,
                (json.dumps(boundary), admin["id"]),
            )
            cursor.execute(
                """
                INSERT INTO audit_logs (
                    actor_profile_id, actor_role, action, entity_type, entity_id,
                    before_data, after_data, request_id, metadata
                ) VALUES (%s, 'ADMIN', 'TEST_WORKSPACE_ARCHIVED',
                          'app_setting', NULL, %s::jsonb, %s::jsonb, %s, %s::jsonb)
                """,
                (
                    admin["id"],
                    json.dumps({"production_data_boundary": None}),
                    json.dumps(boundary),
                    uuid.uuid4(),
                    json.dumps({"reversible": True, "backup_verified": True}),
                ),
            )
        connection.commit()

    print(f"Archived current test workspace at {archived_at.isoformat()}.")
    print(f"Retained active Admin: {admin['login_id']} ({admin['full_name']})")


if __name__ == "__main__":
    main()
