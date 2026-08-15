import uuid

import httpx

from app.core.config import get_settings
from app.core.errors import AppError


settings = get_settings()


def auth_alias(login_id: str) -> str:
    return f"{login_id.strip().lower()}@{settings.AUTH_ALIAS_DOMAIN}"


def service_headers() -> dict[str, str]:
    secret = settings.SUPABASE_SERVICE_ROLE_KEY
    headers = {"apikey": secret}
    if not secret.startswith("sb_secret_"):
        headers["Authorization"] = f"Bearer {secret}"
    return headers


async def create_auth_user(
    login_id: str, password: str, full_name: str, role: str
) -> tuple[uuid.UUID, str]:
    alias = auth_alias(login_id)
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"{str(settings.SUPABASE_URL).rstrip('/')}/auth/v1/admin/users",
            headers=service_headers(),
            json={
                "email": alias,
                "password": password,
                "email_confirm": True,
                "user_metadata": {"display_name": full_name, "app_role": role},
            },
        )
    if response.status_code not in (200, 201):
        if response.status_code in (400, 422):
            raise AppError("VERSION_CONFLICT", "Login ID already exists or is invalid.", 409)
        raise AppError("AUTH_PROVIDER_UNAVAILABLE", "Unable to create the login account.", 503)
    return uuid.UUID(response.json()["id"]), alias


async def delete_auth_user(auth_user_id: uuid.UUID) -> None:
    async with httpx.AsyncClient(timeout=20) as client:
        await client.delete(
            f"{str(settings.SUPABASE_URL).rstrip('/')}/auth/v1/admin/users/{auth_user_id}",
            headers=service_headers(),
        )
