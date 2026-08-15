"""Reset an application user's Supabase Auth password and require first-login change."""

import argparse
import getpass
import secrets
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
    parser.add_argument(
        "--generate",
        action="store_true",
        help="Generate a secure temporary password instead of prompting for one.",
    )
    args = parser.parse_args()
    if args.generate:
        password = secrets.token_urlsafe(12)
    else:
        password = getpass.getpass("New temporary password: ")
        confirm = getpass.getpass("Confirm temporary password: ")
        if password != confirm:
            raise SystemExit("Passwords do not match.")
    if len(password) < 8:
        raise SystemExit("Password must contain at least 8 characters.")

    settings = get_settings()
    login_id = args.login_id.strip().lower()
    base = str(settings.SUPABASE_URL).rstrip("/")
    headers = service_headers()
    with httpx.Client(timeout=20) as client:
        profile_response = client.get(
            f"{base}/rest/v1/profiles",
            headers=headers,
            params={
                "login_id": f"eq.{login_id}",
                "select": "id,auth_user_id",
                "limit": "1",
            },
        )
        if profile_response.status_code != 200:
            raise SystemExit(
                f"Application profile lookup failed (HTTP {profile_response.status_code})."
            )
        profiles = profile_response.json()
        if not profiles:
            raise SystemExit("Application profile was not found.")
        profile_id = profiles[0]["id"]
        auth_user_id = profiles[0]["auth_user_id"]

        response = client.put(
            f"{base}/auth/v1/admin/users/{auth_user_id}",
            headers=headers,
            json={"password": password, "email_confirm": True},
        )
        if response.status_code != 200:
            raise SystemExit(f"Supabase password reset failed (HTTP {response.status_code}).")

        profile_update = client.patch(
            f"{base}/rest/v1/profiles",
            headers={**headers, "Prefer": "return=minimal"},
            params={"id": f"eq.{profile_id}"},
            json={"must_change_password": True},
        )
        if profile_update.status_code not in (200, 204):
            raise SystemExit(
                "Auth password was reset, but the application profile flag could not be updated "
                f"(HTTP {profile_update.status_code})."
            )
    print(f"Password reset completed for login ID: {login_id}")
    if args.generate:
        print(f"Temporary password: {password}")


if __name__ == "__main__":
    main()
