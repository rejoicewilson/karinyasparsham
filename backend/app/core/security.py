import asyncio
import uuid
from dataclasses import dataclass

import httpx
import jwt
import structlog
from fastapi import Depends, Header, Request
from jwt import PyJWKClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import AppError
from app.models.domain import AccountStatus, Profile, UserRole


settings = get_settings()
jwks_client = PyJWKClient(str(settings.SUPABASE_JWKS_URL), cache_keys=True, lifespan=300)
ACCESS_COOKIE_CHUNK_LIMIT = 8
JWT_CLOCK_SKEW_SECONDS = 60
logger = structlog.get_logger()


def access_token_from_request(request: Request, authorization: str | None = None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    legacy = request.cookies.get("access_token")
    if legacy:
        return legacy
    chunks = []
    for index in range(ACCESS_COOKIE_CHUNK_LIMIT):
        chunk = request.cookies.get(f"access_token_{index}")
        if not chunk:
            break
        chunks.append(chunk)
    return "".join(chunks) or None


@dataclass(frozen=True)
class CurrentActor:
    profile_id: uuid.UUID
    auth_user_id: uuid.UUID
    login_id: str
    full_name: str
    role: UserRole


async def _validate_token(token: str) -> dict:
    algorithm = "unknown"
    try:
        header = jwt.get_unverified_header(token)
        algorithm = str(header.get("alg", "unknown"))
        if algorithm == "HS256":
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    f"{str(settings.SUPABASE_URL).rstrip('/')}/auth/v1/user",
                    headers={
                        "apikey": settings.SUPABASE_PUBLISHABLE_KEY,
                        "Authorization": f"Bearer {token}",
                    },
                )
            if response.status_code != 200:
                logger.warning(
                    "supabase_access_token_rejected",
                    algorithm=algorithm,
                    token_length=len(token),
                    supabase_status=response.status_code,
                )
                raise AppError("AUTH_INVALID_CREDENTIALS", "Session is invalid or expired.", 401)
            user = response.json()
            return {"sub": user["id"], "aud": "authenticated"}

        signing_key = await asyncio.to_thread(jwks_client.get_signing_key_from_jwt, token)
        return decode_asymmetric_token(token, signing_key.key)
    except AppError:
        raise
    except Exception as exc:
        logger.warning(
            "access_token_validation_failed",
            algorithm=algorithm,
            token_length=len(token),
            error_type=type(exc).__name__,
            error=str(exc),
        )
        raise AppError("AUTH_INVALID_CREDENTIALS", "Session is invalid or expired.", 401) from exc


def decode_asymmetric_token(token: str, signing_key) -> dict:
    return jwt.decode(
        token,
        signing_key,
        algorithms=["RS256", "ES256", "EdDSA"],
        audience="authenticated",
        issuer=str(settings.SUPABASE_JWT_ISSUER).rstrip("/"),
        leeway=JWT_CLOCK_SKEW_SECONDS,
        options={"require": ["exp", "sub", "aud", "iss"]},
    )


async def get_current_actor(
    request: Request,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> CurrentActor:
    profile = await get_authenticated_profile(request, authorization, db)
    if profile.must_change_password:
        raise AppError("PASSWORD_CHANGE_REQUIRED", "Password change is required.", 403)
    return CurrentActor(
        profile_id=profile.id,
        auth_user_id=profile.auth_user_id,
        login_id=profile.login_id,
        full_name=profile.full_name,
        role=profile.role,
    )


async def get_authenticated_profile(
    request: Request,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> Profile:
    """Resolve an active profile without enforcing the first-login password gate."""
    token = access_token_from_request(request, authorization)
    if not token:
        logger.warning(
            "access_token_missing",
            cookie_names=sorted(request.cookies.keys()),
            has_authorization=bool(authorization),
        )
        raise AppError("AUTH_INVALID_CREDENTIALS", "Authentication is required.", 401)

    claims = await _validate_token(token)
    try:
        auth_user_id = uuid.UUID(claims["sub"])
    except (KeyError, ValueError) as exc:
        raise AppError("AUTH_INVALID_CREDENTIALS", "Token subject is invalid.", 401) from exc

    profile = await db.scalar(select(Profile).where(Profile.auth_user_id == auth_user_id))
    if profile is None:
        raise AppError("AUTH_INVALID_CREDENTIALS", "Application profile was not found.", 401)
    if profile.account_status != AccountStatus.ACTIVE:
        raise AppError("ACCOUNT_INACTIVE", "This account is not active.", 403)
    return profile


def require_role(*roles: UserRole):
    async def dependency(actor: CurrentActor = Depends(get_current_actor)) -> CurrentActor:
        if actor.role not in roles:
            raise AppError("FORBIDDEN_RESOURCE", "You do not have access to this resource.", 403)
        return actor

    return dependency
