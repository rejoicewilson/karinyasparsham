"""Idempotently import historical deceased people as disabled member records."""

import argparse
import asyncio
import csv
import secrets
import sys
import uuid
from datetime import date, datetime, time, timezone
from pathlib import Path

from sqlalchemy import func, select


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.database import SessionFactory  # noqa: E402
from app.models.domain import (  # noqa: E402
    AccountStatus,
    AuditLog,
    Member,
    Profile,
    Taluk,
    UserRole,
)
from app.services.supabase_admin import create_auth_user, delete_auth_user  # noqa: E402
from validate_historical_deaths import (  # noqa: E402
    PHONE_PATTERN,
    load_rows,
    normalized_taluk,
)


def deceased_at(value: str) -> datetime:
    return datetime.combine(date.fromisoformat(value), time.min, tzinfo=timezone.utc)


async def run(args: argparse.Namespace) -> None:
    rows = load_rows(args.source.resolve())
    if len(rows) != args.expected_count:
        raise SystemExit(f"Expected {args.expected_count} rows, found {len(rows)}.")
    if len({row["legacy_no"] for row in rows}) != len(rows):
        raise SystemExit("Historical sequence numbers must be unique.")
    if any(not PHONE_PATTERN.fullmatch(row["phone"].strip()) for row in rows):
        raise SystemExit("Every historical deceased member must have a 10-digit phone number.")
    if any(deceased_at(row["death_date"]) > datetime.now(timezone.utc) for row in rows):
        raise SystemExit("Death dates cannot be in the future.")

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

        taluks = (await db.scalars(select(Taluk).where(Taluk.is_active.is_(True)))).all()
        taluk_by_name = {taluk.name.casefold(): taluk for taluk in taluks}
        missing_taluks = sorted({
            normalized_taluk(row["taluk"])
            for row in rows
            if normalized_taluk(row["taluk"]).casefold() not in taluk_by_name
        })
        if missing_taluks:
            raise SystemExit("Unmapped taluks: " + ", ".join(missing_taluks))

        existing_rows = (await db.execute(
            select(Profile, Member)
            .join(Member, Member.profile_id == Profile.id)
            .where(Profile.phone.in_([row["phone"].strip() for row in rows]))
        )).all()
        member_by_phone: dict[str, tuple[Profile, Member]] = {}
        for profile, member in existing_rows:
            if profile.phone in member_by_phone:
                raise SystemExit(f"Multiple member records use phone {profile.phone}.")
            member_by_phone[str(profile.phone)] = (profile, member)

        plans = []
        for row in rows:
            sequence = int(row["legacy_no"])
            phone = row["phone"].strip()
            taluk = taluk_by_name[normalized_taluk(row["taluk"]).casefold()]
            existing = member_by_phone.get(phone)
            if existing:
                profile, member = existing
                if member.taluk_id != taluk.id:
                    raise SystemExit(
                        f"Record {sequence} matches {member.member_code}, but its taluk differs."
                    )
                action = "already_deceased" if profile.account_status == AccountStatus.DECEASED else "mark_deceased"
                member_code = str(member.member_code)
            else:
                action = "create_deceased"
                member_code = f"HIST-D{sequence:03d}"
            plans.append({
                "sequence": sequence,
                "row": row,
                "taluk": taluk,
                "existing": existing,
                "action": action,
                "member_code": member_code,
            })

        generated_codes = [plan["member_code"] for plan in plans if plan["action"] == "create_deceased"]
        generated_logins = [f"deceased-{plan['sequence']:03d}" for plan in plans if plan["action"] == "create_deceased"]
        if await db.scalar(select(func.count()).select_from(Member).where(Member.member_code.in_(generated_codes))):
            raise SystemExit("One or more generated historical member codes already exist unexpectedly.")
        if await db.scalar(select(func.count()).select_from(Profile).where(Profile.login_id.in_(generated_logins))):
            raise SystemExit("One or more generated historical login IDs already exist unexpectedly.")

        summary = {
            "mode": "apply" if args.apply else "dry-run",
            "source_rows": len(plans),
            "create_deceased": sum(plan["action"] == "create_deceased" for plan in plans),
            "mark_existing_deceased": sum(plan["action"] == "mark_deceased" for plan in plans),
            "already_deceased": sum(plan["action"] == "already_deceased" for plan in plans),
            "joined_on": args.joined_on.isoformat(),
            "creates_cases_or_financial_records": False,
        }
        print(summary)
        if not args.apply:
            return

        for position, plan in enumerate(plans, start=1):
            row = plan["row"]
            death_timestamp = deceased_at(row["death_date"])
            if plan["existing"]:
                profile, member = plan["existing"]
                if profile.account_status == AccountStatus.DECEASED:
                    if member.deceased_at != death_timestamp:
                        raise SystemExit(
                            f"Record {plan['sequence']} is already deceased with a different date."
                        )
                    continue
                before_status = profile.account_status.value
                profile.account_status = AccountStatus.DECEASED
                profile.must_change_password = False
                member.deceased_at = death_timestamp
                db.add(AuditLog(
                    actor_profile_id=admin.id,
                    actor_role=admin.role,
                    action="MEMBER_MARKED_DECEASED_HISTORICAL",
                    entity_type="member",
                    entity_id=member.id,
                    before_data={"account_status": before_status},
                    after_data={
                        "account_status": AccountStatus.DECEASED.value,
                        "deceased_at": death_timestamp.isoformat(),
                    },
                    request_id=uuid.uuid4(),
                    metadata_json={"source": "historical_deceased_import", "legacy_no": plan["sequence"]},
                ))
                await db.commit()
            else:
                auth_user_id = None
                try:
                    login_id = f"deceased-{plan['sequence']:03d}"
                    auth_user_id, alias = await create_auth_user(
                        login_id,
                        secrets.token_urlsafe(32),
                        row["name"].strip(),
                        UserRole.MEMBER.value,
                    )
                    profile = Profile(
                        auth_user_id=auth_user_id,
                        login_id=login_id,
                        auth_email_alias=alias,
                        role=UserRole.MEMBER,
                        full_name=row["name"].strip(),
                        phone=row["phone"].strip(),
                        account_status=AccountStatus.DECEASED,
                        must_change_password=False,
                        created_by=admin.id,
                    )
                    db.add(profile)
                    await db.flush()
                    member = Member(
                        profile_id=profile.id,
                        member_code=plan["member_code"],
                        taluk_id=plan["taluk"].id,
                        joined_on=args.joined_on,
                        deceased_at=death_timestamp,
                    )
                    db.add(member)
                    await db.flush()
                    db.add(AuditLog(
                        actor_profile_id=admin.id,
                        actor_role=admin.role,
                        action="HISTORICAL_DECEASED_MEMBER_IMPORTED",
                        entity_type="member",
                        entity_id=member.id,
                        before_data=None,
                        after_data={
                            "member_code": plan["member_code"],
                            "taluk_id": str(plan["taluk"].id),
                            "joined_on": args.joined_on.isoformat(),
                            "deceased_at": death_timestamp.isoformat(),
                        },
                        request_id=uuid.uuid4(),
                        metadata_json={"source": "historical_deceased_import", "legacy_no": plan["sequence"]},
                    ))
                    await db.commit()
                except Exception:
                    await db.rollback()
                    if auth_user_id is not None:
                        await delete_auth_user(auth_user_id)
                    raise
            if position % 10 == 0 or position == len(plans):
                print(f"Processed {position}/{len(plans)} historical deceased members.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--expected-count", type=int, required=True)
    parser.add_argument("--joined-on", type=date.fromisoformat, required=True)
    parser.add_argument("--admin-login", default="admin")
    parser.add_argument("--apply", action="store_true")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
