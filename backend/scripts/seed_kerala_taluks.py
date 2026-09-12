"""Idempotently seed the approved Kerala district and taluk/CRO/TSO master list."""

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


DISTRICTS = [
    ("KSD", "Kasargod", ["Kasargod", "Hosdurg", "Vellarikundu", "Manjeswaram"]),
    ("KNR", "Kannur", ["Kannur", "Iritty", "Thalassery", "Taliparambu", "Payyannur"]),
    ("WYD", "Wayanad", ["Mananthavady", "Vythiri", "Sultan Bathery"]),
    ("KKD", "Kozhikode", [
        "Kozhikode", "Koyilandi", "Vadakara", "Thamarassery", "CRO South", "CRO North",
    ]),
    ("MPM", "Malappuram", [
        "Eranadu", "Kondotty", "Thirurangady", "Tirur", "Nilambur", "Perinthalmanna",
        "Ponnani",
    ]),
    ("PKD", "Palakkad", ["Palakkad", "Pattambi", "Ottappalam", "Alathur", "Mannarkkad"]),
    ("TSR", "Thrissur", [
        "Thrissur", "Thalappilly", "Kunnamkulam", "Chavakkad", "Kodungallur",
        "Mukundapuram", "Chalakudy",
    ]),
    ("EKM", "Ernakulam", [
        "Kochi (CRO)", "Kochi TSO (Vypin)", "Kochi TSO (Kumbalangi)", "EKM (CRO)",
        "Paravoor", "Aluva", "Kunnathunadu", "Muvattupuzha", "Kothamangalam", "Kanayannur",
    ]),
    ("IDK", "Idukki", ["Thodupuzha"]),
    ("KTM", "Kottayam", ["Kottayam", "Kanjirapally", "Meenachil", "Vaikom", "Changanassery"]),
    ("PTA", "Pathanamthitta", ["Thiruvalla", "Mallappally", "Ranni", "Kozhencherry"]),
    ("ALP", "Alappuzha", [
        "Mavelikkara", "Karthikapally", "Kuttanadu", "Chengannur", "Ambalapuzha",
    ]),
    ("KLM", "Kollam", ["Kollam", "Kottarakkara", "Karunagapally", "Kunnathur"]),
    ("TVM", "Thiruvananthapuram", ["Neyyatinkkara", "TVM", "TVM CRO (South)"]),
]


def records() -> list[dict[str, str]]:
    return [
        {"code": f"{prefix}-{index:02d}", "name": name, "district": district}
        for prefix, district, names in DISTRICTS
        for index, name in enumerate(names, start=1)
    ]


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
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    taluks = records()
    if len(taluks) != 69:
        raise SystemExit(f"Expected 69 records, found {len(taluks)}.")
    if len({item["code"] for item in taluks}) != len(taluks):
        raise SystemExit("Generated taluk codes are not unique.")
    if len({item["name"].casefold() for item in taluks}) != len(taluks):
        raise SystemExit("Taluk names are not unique.")

    with psycopg.connect(database_url(), row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, login_id
                FROM profiles
                WHERE role = 'ADMIN' AND account_status = 'ACTIVE'
                  AND lower(login_id::text) = lower(%s)
                """,
                (args.admin_login.strip(),),
            )
            admin = cursor.fetchone()
            if admin is None:
                raise SystemExit("The active Admin profile was not found.")

            cursor.execute(
                "SELECT code::text AS code, name FROM taluks WHERE is_active"
            )
            existing = cursor.fetchall()
            existing_codes = {item["code"].casefold() for item in existing}
            existing_names = {item["name"].casefold() for item in existing}
            conflicts = [
                item for item in taluks
                if (item["code"].casefold() in existing_codes)
                != (item["name"].casefold() in existing_names)
            ]
            if conflicts:
                raise SystemExit(
                    "Existing active data conflicts with the approved list: "
                    + json.dumps(conflicts, ensure_ascii=True)
                )
            pending = [
                item for item in taluks
                if item["code"].casefold() not in existing_codes
                and item["name"].casefold() not in existing_names
            ]
            print(json.dumps({
                "mode": "apply" if args.apply else "dry-run",
                "approved_records": len(taluks),
                "already_present": len(taluks) - len(pending),
                "to_insert": len(pending),
                "districts": len(DISTRICTS),
            }, indent=2))
            if not args.apply:
                connection.rollback()
                print("No changes made. Re-run with --apply after reviewing the count.")
                return

            request_id = uuid.uuid4()
            for item in pending:
                cursor.execute(
                    """
                    INSERT INTO taluks (code, name, district, is_active)
                    VALUES (%s, %s, %s, true)
                    RETURNING id
                    """,
                    (item["code"], item["name"], item["district"]),
                )
                taluk_id = cursor.fetchone()["id"]
                cursor.execute(
                    """
                    INSERT INTO audit_logs (
                        actor_profile_id, actor_role, action, entity_type,
                        entity_id, after_data, request_id, metadata
                    ) VALUES (%s, 'ADMIN', 'TALUK_CREATED', 'taluk',
                              %s, %s::jsonb, %s, %s::jsonb)
                    """,
                    (
                        admin["id"],
                        taluk_id,
                        json.dumps(item),
                        request_id,
                        json.dumps({"source": "approved_kerala_master_import"}),
                    ),
                )
        connection.commit()

    print(f"Imported {len(pending)} taluk/CRO/TSO records across {len(DISTRICTS)} districts.")


if __name__ == "__main__":
    main()
