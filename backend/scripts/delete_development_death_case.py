"""Hard-delete an uncollected death case from a development database."""

import argparse
import json
import sys
import uuid
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import psycopg


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-number", required=True)
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    if settings.APP_ENV.lower() == "production":
        raise SystemExit("Hard deletion is disabled when APP_ENV=production.")
    if not args.confirm:
        raise SystemExit("Pass --confirm after verifying the case number.")

    parsed_url = urlsplit(
        settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)
    )
    query = [("sslmode" if key == "ssl" else key, value) for key, value in parse_qsl(parsed_url.query)]
    database_url = urlunsplit((*parsed_url[:3], urlencode(query), parsed_url.fragment))
    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT dc.id, dc.case_number, dc.deceased_member_id, dc.sequence_month,
                       dc.monthly_sequence, dc.created_by, p.id, p.full_name,
                       p.account_status::text, m.deceased_at
                FROM death_cases dc
                JOIN members m ON m.id = dc.deceased_member_id
                JOIN profiles p ON p.id = m.profile_id
                WHERE dc.case_number = %s
                FOR UPDATE OF dc, m, p
                """,
                (args.case_number.strip(),),
            )
            case = cursor.fetchone()
            if case is None:
                raise SystemExit("Death case was not found.")

            case_id, case_number, member_id, sequence_month, sequence_number = case[:5]
            created_by, profile_id, member_name, account_status, deceased_at = case[5:]
            cursor.execute(
                """
                SELECT count(*)
                FROM collection_transactions ct
                JOIN case_obligations co ON co.id = ct.case_obligation_id
                WHERE co.death_case_id = %s AND ct.status <> 'VOIDED'
                """,
                (case_id,),
            )
            collection_count = cursor.fetchone()[0]
            if collection_count:
                raise SystemExit(
                    f"Deletion refused: {collection_count} non-voided collection(s) exist."
                )

            cursor.execute(
                "SELECT count(*) FROM case_obligations WHERE death_case_id = %s",
                (case_id,),
            )
            obligation_count = cursor.fetchone()[0]

            cursor.execute(
                """
                DELETE FROM notification_outbox
                WHERE recipient_id IN (
                    SELECT nr.id FROM notification_recipients nr
                    JOIN notification_events ne ON ne.id = nr.event_id
                    WHERE ne.related_entity_type = 'death_case'
                      AND ne.related_entity_id = %s
                )
                """,
                (case_id,),
            )
            cursor.execute(
                """
                DELETE FROM notification_recipients
                WHERE event_id IN (
                    SELECT id FROM notification_events
                    WHERE related_entity_type = 'death_case' AND related_entity_id = %s
                )
                """,
                (case_id,),
            )
            cursor.execute(
                """
                DELETE FROM notification_events
                WHERE related_entity_type = 'death_case' AND related_entity_id = %s
                """,
                (case_id,),
            )

            cursor.execute("ALTER TABLE case_obligations DISABLE TRIGGER no_delete_obligations")
            cursor.execute("ALTER TABLE death_cases DISABLE TRIGGER no_delete_death_cases")
            cursor.execute("DELETE FROM case_obligations WHERE death_case_id = %s", (case_id,))
            cursor.execute("DELETE FROM death_cases WHERE id = %s", (case_id,))
            cursor.execute("ALTER TABLE case_obligations ENABLE TRIGGER no_delete_obligations")
            cursor.execute("ALTER TABLE death_cases ENABLE TRIGGER no_delete_death_cases")

            if account_status == "DECEASED" and deceased_at is not None:
                cursor.execute(
                    "UPDATE members SET deceased_at = NULL WHERE id = %s",
                    (member_id,),
                )
                cursor.execute(
                    "UPDATE profiles SET account_status = 'ACTIVE' WHERE id = %s",
                    (profile_id,),
                )

            cursor.execute(
                """
                SELECT coalesce(max(monthly_sequence), 0)
                FROM death_cases WHERE sequence_month = %s
                """,
                (sequence_month,),
            )
            remaining_sequence = cursor.fetchone()[0]
            cursor.execute(
                """
                UPDATE monthly_case_counters
                SET last_sequence = %s, updated_at = now()
                WHERE sequence_month = %s
                """,
                (remaining_sequence, sequence_month),
            )

            cursor.execute(
                """
                INSERT INTO audit_logs (
                    actor_profile_id, actor_role, action, entity_type, entity_id,
                    before_data, after_data, request_id, metadata
                ) VALUES (%s, 'ADMIN', 'DEVELOPMENT_DEATH_CASE_HARD_DELETED',
                          'death_case', %s, %s::jsonb, %s::jsonb, %s, %s::jsonb)
                """,
                (
                    created_by,
                    case_id,
                    json.dumps({
                        "case_number": str(case_number),
                        "member_name": member_name,
                        "monthly_sequence": sequence_number,
                        "obligations": obligation_count,
                    }),
                    json.dumps({"deleted": True, "member_restored": account_status == "DECEASED"}),
                    uuid.uuid4(),
                    json.dumps({"development_cleanup": True}),
                ),
            )
        connection.commit()

    print(
        f"Deleted {case_number}: {obligation_count} obligation(s); "
        f"restored member {member_name}."
    )


if __name__ == "__main__":
    main()
