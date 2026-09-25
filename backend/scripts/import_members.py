"""Idempotently import members from a Markdown table."""

import argparse
import asyncio
import csv
import json
import re
import sys
import uuid
from datetime import date
from pathlib import Path

from sqlalchemy import func, select


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.database import SessionFactory  # noqa: E402
from app.models.domain import (  # noqa: E402
    AccountStatus,
    AgentTalukAssignment,
    AuditLog,
    Member,
    PermanentMembershipAccount,
    Profile,
    Taluk,
    UserRole,
)
from app.services.supabase_admin import create_auth_user, delete_auth_user  # noqa: E402


PHONE_PATTERN = re.compile(r"^[0-9]{10}$")


def parse_phone_overrides(values: list[str]) -> dict[int, str]:
    overrides: dict[int, str] = {}
    for value in values:
        source_number, separator, phone = value.partition("=")
        try:
            number = int(source_number)
        except ValueError as exc:
            raise SystemExit("Phone overrides must use SOURCE_NUMBER=PHONE.") from exc
        if not separator or not PHONE_PATTERN.fullmatch(phone.strip()):
            raise SystemExit("Phone overrides must use SOURCE_NUMBER=10_DIGIT_PHONE.")
        if number in overrides:
            raise SystemExit(f"Duplicate phone override for source number {number}.")
        overrides[number] = phone.strip()
    return overrides


def table_records(path: Path) -> list[dict[str, str | int | None]]:
    rows: list[dict[str, str | int | None]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip().startswith("|"):
            continue
        columns = [item.strip() for item in raw_line.strip().strip("|").split("|")]
        if columns[0].casefold() in {"taluk", "no", "no."} or set(columns[0]) <= {"-", ":"}:
            continue
        if len(columns) == 3:
            rows.append({
                "source_number": None, "taluk": columns[0], "ard_no": None,
                "full_name": columns[1], "phone": columns[2],
            })
        elif len(columns) == 4:
            rows.append({
                "source_number": None, "taluk": columns[0], "ard_no": columns[1] or None,
                "full_name": columns[2], "phone": columns[3],
            })
        elif len(columns) == 5:
            if not columns[0].isdigit() or int(columns[0]) != len(rows) + 1:
                raise SystemExit("Numbered member rows must be consecutive, starting at 1.")
            rows.append({
                "source_number": int(columns[0]), "taluk": columns[1],
                "ard_no": columns[2] or None, "full_name": columns[3], "phone": columns[4],
            })
    return rows


def table_rows(path: Path) -> list[tuple[str, str | None, str, str]]:
    return [
        (str(row["taluk"]), row["ard_no"], str(row["full_name"]), str(row["phone"]))
        for row in table_records(path)
    ]


async def import_members(args: argparse.Namespace) -> None:
    source = Path(args.source).resolve()
    source_rows = table_records(source)
    excluded_numbers = set(args.exclude_source_number)
    phone_overrides = parse_phone_overrides(args.phone_override)
    available_numbers = {
        int(row["source_number"])
        for row in source_rows
        if row["source_number"] is not None
    }
    if excluded_numbers - available_numbers:
        raise SystemExit("One or more excluded source numbers were not found in the numbered table.")
    if set(phone_overrides) - available_numbers:
        raise SystemExit("One or more phone override source numbers were not found.")
    if set(phone_overrides).intersection(excluded_numbers):
        raise SystemExit("Excluded source rows cannot also have phone overrides.")
    for row in source_rows:
        source_number = row["source_number"]
        if source_number in phone_overrides:
            row["phone"] = phone_overrides[int(source_number)]
    rows = [row for row in source_rows if row["source_number"] not in excluded_numbers]
    if len(rows) != args.expected_count:
        raise SystemExit(f"Expected {args.expected_count} members, found {len(rows)}.")
    if any(not row["full_name"] for row in rows):
        raise SystemExit("Every member must have a name.")
    if any(not PHONE_PATTERN.fullmatch(str(row["phone"])) for row in rows):
        raise SystemExit("Every phone number must contain exactly 10 digits.")
    if any(row["ard_no"] is not None and not str(row["ard_no"]).isdigit() for row in rows):
        raise SystemExit("Every ARD number must contain digits only.")
    if any(str(row["taluk"]).casefold() != args.taluk.casefold() for row in rows):
        raise SystemExit(f"Every source row must belong to {args.taluk}.")

    records = [
        {
            "member_code": f"{args.code_prefix}-M{index:03d}",
            "login_id": f"mem-{args.login_prefix}-{index:03d}",
            "ard_no": row["ard_no"],
            "full_name": str(row["full_name"]),
            "phone": str(row["phone"]),
        }
        for position, row in enumerate(rows, start=1)
        for index in [int(row["source_number"]) if row["source_number"] is not None else position]
    ]

    async with SessionFactory() as db:
        admin = await db.scalar(
            select(Profile).where(
                Profile.role == UserRole.ADMIN,
                Profile.account_status == AccountStatus.ACTIVE,
                func.lower(Profile.login_id) == args.admin_login.casefold(),
            )
        )
        if admin is None:
            raise SystemExit("The active administrator profile was not found.")
        taluk = await db.scalar(
            select(Taluk).where(Taluk.is_active.is_(True), func.lower(Taluk.name) == args.taluk.casefold())
        )
        if taluk is None:
            raise SystemExit(f"Active taluk {args.taluk!r} was not found.")
        assignment = await db.scalar(
            select(AgentTalukAssignment.id).where(
                AgentTalukAssignment.taluk_id == taluk.id,
                AgentTalukAssignment.ends_at.is_(None),
            )
        )
        if assignment is None:
            raise SystemExit(f"{args.taluk} does not have an active collection agent.")

        existing_rows = (await db.execute(
            select(Profile, Member, PermanentMembershipAccount.id)
            .join(Member, Member.profile_id == Profile.id)
            .outerjoin(PermanentMembershipAccount, PermanentMembershipAccount.member_id == Member.id)
            .where(Profile.login_id.in_([record["login_id"] for record in records]))
        )).all()
        login_ids = [profile.login_id for profile, _, _ in existing_rows]
        member_codes = [item[0] for item in (await db.execute(
            select(Member.member_code).where(Member.member_code.in_([record["member_code"] for record in records]))
        )).all()]
        existing_logins = {str(value).casefold() for value in login_ids}
        existing_codes = {str(value).casefold() for value in member_codes}
        conflicts = [
            record for record in records
            if (record["login_id"].casefold() in existing_logins)
            != (record["member_code"].casefold() in existing_codes)
        ]
        if conflicts:
            raise SystemExit("Existing login IDs and member codes do not form matching import records.")
        expected_by_login = {record["login_id"].casefold(): record for record in records}
        mismatches: list[str] = []
        ard_updates: list[tuple[Member, dict[str, str | None]]] = []
        for profile, member, permanent_account_id in existing_rows:
            expected = expected_by_login[str(profile.login_id).casefold()]
            base_valid = (
                str(member.member_code).casefold() == expected["member_code"].casefold()
                and profile.full_name == expected["full_name"]
                and profile.phone == expected["phone"]
                and profile.account_status == AccountStatus.ACTIVE
                and profile.must_change_password is True
                and member.taluk_id == taluk.id
                and member.joined_on == args.joined_on
                and permanent_account_id is not None
            )
            if not base_valid:
                mismatches.append(expected["login_id"])
            elif member.ard_no == expected["ard_no"]:
                continue
            elif member.ard_no is None and expected["ard_no"] is not None:
                ard_updates.append((member, expected))
            else:
                mismatches.append(expected["login_id"])
        if mismatches:
            raise SystemExit(
                "Existing member records differ from the approved import: " + ", ".join(mismatches)
            )
        pending = [
            record for record in records
            if record["login_id"].casefold() not in existing_logins
        ]
        print(json.dumps({
            "mode": "apply" if args.apply else "dry-run",
            "source_members": len(records),
            "already_present": len(records) - len(pending),
            "to_create": len(pending),
            "ard_numbers": sum(record["ard_no"] is not None for record in records),
            "ard_to_update": len(ard_updates),
            "shared_phone_rows": len(records) - len({record["phone"] for record in records}),
            "excluded_source_numbers": sorted(excluded_numbers),
            "phone_override_source_numbers": sorted(phone_overrides),
            "taluk": args.taluk,
            "joined_on": args.joined_on.isoformat(),
        }, indent=2))
        if not args.apply:
            return

        for member, record in ard_updates:
            member.ard_no = record["ard_no"]
            db.add(AuditLog(
                actor_profile_id=admin.id,
                actor_role=admin.role,
                action="MEMBER_ARD_NUMBER_ADDED",
                entity_type="member",
                entity_id=member.id,
                before_data={"ard_no": None},
                after_data={"ard_no": record["ard_no"]},
                request_id=uuid.uuid4(),
                metadata={"source": "approved_member_import"},
            ))
        if ard_updates:
            await db.commit()

        output = Path(args.credentials_output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        write_header = not output.exists()
        existing_credential_codes: set[str] = set()
        if output.exists():
            with output.open(newline="", encoding="utf-8") as handle:
                existing_credential_codes = {
                    row["member_code"] for row in csv.DictReader(handle)
                }
        for position, record in enumerate(pending, start=1):
            auth_user_id: uuid.UUID | None = None
            try:
                auth_user_id, alias = await create_auth_user(
                    record["login_id"], record["phone"], record["full_name"], "MEMBER"
                )
                profile = Profile(
                    auth_user_id=auth_user_id,
                    login_id=record["login_id"],
                    auth_email_alias=alias,
                    role=UserRole.MEMBER,
                    full_name=record["full_name"],
                    phone=record["phone"],
                    must_change_password=True,
                    created_by=admin.id,
                )
                db.add(profile)
                await db.flush()
                member = Member(
                    profile_id=profile.id,
                    member_code=record["member_code"],
                    ard_no=record["ard_no"],
                    taluk_id=taluk.id,
                    joined_on=args.joined_on,
                )
                db.add(member)
                await db.flush()
                db.add(AuditLog(
                    actor_profile_id=admin.id,
                    actor_role=admin.role,
                    action="MEMBER_CREATED",
                    entity_type="member",
                    entity_id=member.id,
                    after_data={
                        "login_id": record["login_id"],
                        "member_code": record["member_code"],
                        "ard_no": record["ard_no"],
                        "taluk_id": str(taluk.id),
                        "joined_on": args.joined_on.isoformat(),
                    },
                    request_id=uuid.uuid4(),
                    metadata={"source": "approved_member_import"},
                ))
                await db.commit()
                credential = {
                    "member_code": record["member_code"],
                    "full_name": record["full_name"],
                    "login_id": record["login_id"],
                    "temporary_password": record["phone"],
                }
                if record["member_code"] not in existing_credential_codes:
                    with output.open("a", newline="", encoding="utf-8") as handle:
                        writer = csv.DictWriter(
                            handle,
                            fieldnames=[
                                "member_code", "full_name", "login_id", "temporary_password",
                            ],
                        )
                        if write_header:
                            writer.writeheader()
                            write_header = False
                        writer.writerow(credential)
                    existing_credential_codes.add(record["member_code"])
                if position % 10 == 0 or position == len(pending):
                    print(f"Created {position}/{len(pending)} members.")
            except Exception:
                await db.rollback()
                if auth_user_id is not None:
                    await delete_auth_user(auth_user_id)
                raise

    print(f"Imported {len(pending)} members. Credentials saved to {output}.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="Path to a Markdown table with Taluk, optional ARD, Name, and Phone Number columns")
    parser.add_argument("--taluk", required=True)
    parser.add_argument("--joined-on", required=True, type=date.fromisoformat)
    parser.add_argument("--expected-count", required=True, type=int)
    parser.add_argument("--code-prefix", required=True)
    parser.add_argument("--login-prefix", required=True)
    parser.add_argument("--credentials-output", required=True)
    parser.add_argument("--exclude-source-number", action="append", default=[], type=int)
    parser.add_argument("--phone-override", action="append", default=[])
    parser.add_argument("--admin-login", default="admin")
    parser.add_argument("--apply", action="store_true")
    asyncio.run(import_members(parser.parse_args()))


if __name__ == "__main__":
    main()
