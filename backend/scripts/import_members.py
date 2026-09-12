"""Idempotently import members from a three-column Markdown table."""

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


def table_rows(path: Path) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip().startswith("|"):
            continue
        columns = [item.strip() for item in raw_line.strip().strip("|").split("|")]
        if len(columns) != 3 or columns[0].casefold() == "taluk" or set(columns[0]) <= {"-", ":"}:
            continue
        rows.append((columns[0], columns[1], columns[2]))
    return rows


async def import_members(args: argparse.Namespace) -> None:
    source = Path(args.source).resolve()
    rows = table_rows(source)
    if len(rows) != args.expected_count:
        raise SystemExit(f"Expected {args.expected_count} members, found {len(rows)}.")
    if any(not name for _, name, _ in rows):
        raise SystemExit("Every member must have a name.")
    if any(not PHONE_PATTERN.fullmatch(phone) for _, _, phone in rows):
        raise SystemExit("Every phone number must contain exactly 10 digits.")
    if any(taluk.casefold() != args.taluk.casefold() for taluk, _, _ in rows):
        raise SystemExit(f"Every source row must belong to {args.taluk}.")

    records = [
        {
            "member_code": f"{args.code_prefix}-M{index:03d}",
            "login_id": f"mem-{args.login_prefix}-{index:03d}",
            "full_name": name,
            "phone": phone,
        }
        for index, (_, name, phone) in enumerate(rows, start=1)
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
        for profile, member, permanent_account_id in existing_rows:
            expected = expected_by_login[str(profile.login_id).casefold()]
            valid = (
                str(member.member_code).casefold() == expected["member_code"].casefold()
                and profile.full_name == expected["full_name"]
                and profile.phone == expected["phone"]
                and profile.account_status == AccountStatus.ACTIVE
                and profile.must_change_password is True
                and member.taluk_id == taluk.id
                and member.joined_on == args.joined_on
                and permanent_account_id is not None
            )
            if not valid:
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
            "shared_phone_rows": len(records) - len({record["phone"] for record in records}),
            "taluk": args.taluk,
            "joined_on": args.joined_on.isoformat(),
        }, indent=2))
        if not args.apply:
            return

        credentials: list[dict[str, str]] = []
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
                        "taluk_id": str(taluk.id),
                        "joined_on": args.joined_on.isoformat(),
                    },
                    request_id=uuid.uuid4(),
                    metadata={"source": "approved_member_import"},
                ))
                await db.commit()
                credentials.append({
                    "member_code": record["member_code"],
                    "full_name": record["full_name"],
                    "login_id": record["login_id"],
                    "temporary_password": record["phone"],
                })
                if position % 10 == 0 or position == len(pending):
                    print(f"Created {position}/{len(pending)} members.")
            except Exception:
                await db.rollback()
                if auth_user_id is not None:
                    await delete_auth_user(auth_user_id)
                raise

    output = Path(args.credentials_output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    write_header = not output.exists()
    with output.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["member_code", "full_name", "login_id", "temporary_password"])
        if write_header:
            writer.writeheader()
        writer.writerows(credentials)
    print(f"Imported {len(pending)} members. Credentials saved to {output}.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="Path to a Markdown table with Taluk, Name, and Phone Number columns")
    parser.add_argument("--taluk", required=True)
    parser.add_argument("--joined-on", required=True, type=date.fromisoformat)
    parser.add_argument("--expected-count", required=True, type=int)
    parser.add_argument("--code-prefix", required=True)
    parser.add_argument("--login-prefix", required=True)
    parser.add_argument("--credentials-output", required=True)
    parser.add_argument("--admin-login", default="admin")
    parser.add_argument("--apply", action="store_true")
    asyncio.run(import_members(parser.parse_args()))


if __name__ == "__main__":
    main()
