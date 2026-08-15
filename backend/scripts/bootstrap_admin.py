"""Create the first Supabase Auth admin and matching application profile."""

import argparse
import getpass
import sys
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402
from app.services.supabase_admin import service_headers  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--login-id", required=True)
    parser.add_argument("--full-name", required=True)
    parser.add_argument("--phone")
    args = parser.parse_args()
    password = getpass.getpass("Temporary admin password: ")
    if len(password) < 8:
        raise SystemExit("Password must contain at least 8 characters.")

    settings = get_settings()
    login_id = args.login_id.strip().lower()
    alias = f"{login_id}@{settings.AUTH_ALIAS_DOMAIN}"
    base = str(settings.SUPABASE_URL).rstrip("/")
    headers = service_headers()

    with httpx.Client(timeout=20) as client:
        auth_response = client.post(
            f"{base}/auth/v1/admin/users",
            headers=headers,
            json={
                "email": alias,
                "password": password,
                "email_confirm": True,
                "user_metadata": {"display_name": args.full_name},
            },
        )
        if auth_response.status_code not in (200, 201):
            raise SystemExit(f"Auth user creation failed (HTTP {auth_response.status_code}).")
        auth_user_id = auth_response.json()["id"]
        profile_response = client.post(
            f"{base}/rest/v1/profiles",
            headers={**headers, "Prefer": "return=minimal"},
            json={
                "auth_user_id": auth_user_id,
                "login_id": login_id,
                "auth_email_alias": alias,
                "role": "ADMIN",
                "full_name": args.full_name.strip(),
                "phone": args.phone,
                "account_status": "ACTIVE",
                "must_change_password": True,
            },
        )
        if profile_response.status_code not in (200, 201):
            client.delete(f"{base}/auth/v1/admin/users/{auth_user_id}", headers=headers)
            raise SystemExit(
                f"Profile creation failed (HTTP {profile_response.status_code}); Auth user rolled back."
            )
    print(f"Created admin profile for login ID: {login_id}")


if __name__ == "__main__":
    main()
