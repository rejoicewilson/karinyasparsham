from datetime import datetime, timezone

import httpx
import jwt
import structlog
from fastapi import APIRouter, Cookie, Depends, Header, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.api.responses import success
from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import ACCESS_COOKIE_CHUNK_LIMIT, access_token_from_request, get_authenticated_profile
from app.models.domain import AccountStatus, Profile
from app.schemas.api import LoginRequest, PasswordChangeRequest


router = APIRouter()
settings = get_settings()
logger = structlog.get_logger()


def set_session_cookies(response: Response, session: dict) -> None:
    secure = settings.APP_ENV != "development"
    access_token = session["access_token"]
    chunks = [access_token[index:index + 3000] for index in range(0, len(access_token), 3000)]
    if len(chunks) > ACCESS_COOKIE_CHUNK_LIMIT:
        raise AppError("AUTH_TOKEN_TOO_LARGE", "The authentication token is too large.", 502)
    response.delete_cookie("access_token", path="/")
    for index, chunk in enumerate(chunks):
        response.set_cookie(
            f"access_token_{index}", chunk, httponly=True, secure=secure,
            samesite="lax", max_age=int(session.get("expires_in", 3600)), path="/",
        )
    for index in range(len(chunks), ACCESS_COOKIE_CHUNK_LIMIT):
        response.delete_cookie(f"access_token_{index}", path="/")
    response.set_cookie(
        "refresh_token", session["refresh_token"], httponly=True, secure=secure,
        samesite="strict", max_age=60 * 60 * 24 * 30, path="/api/v1/auth",
    )


def profile_payload(profile: Profile) -> dict:
    return {
        "id": profile.id,
        "login_id": profile.login_id,
        "full_name": profile.full_name,
        "role": profile.role,
        "must_change_password": profile.must_change_password,
    }


@router.post("/login")
async def login(payload: LoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    profile = await db.scalar(select(Profile).where(Profile.login_id == payload.login_id))
    if profile is None:
        raise AppError("AUTH_INVALID_CREDENTIALS", "Invalid login ID or password.", 401)
    if profile.account_status != AccountStatus.ACTIVE:
        raise AppError("ACCOUNT_INACTIVE", "This account is not active.", 403)

    async with httpx.AsyncClient(timeout=15) as client:
        auth_response = await client.post(
            f"{str(settings.SUPABASE_URL).rstrip('/')}/auth/v1/token?grant_type=password",
            headers={"apikey": settings.SUPABASE_PUBLISHABLE_KEY},
            json={"email": profile.auth_email_alias, "password": payload.password},
        )
    if auth_response.status_code != 200:
        raise AppError("AUTH_INVALID_CREDENTIALS", "Invalid login ID or password.", 401)
    session = auth_response.json()
    logger.info(
        "auth_session_issued",
        algorithm=jwt.get_unverified_header(session["access_token"]).get("alg"),
        access_token_length=len(session["access_token"]),
        access_cookie_chunks=(len(session["access_token"]) + 2999) // 3000,
    )
    set_session_cookies(response, session)
    profile.last_login_at = datetime.now(timezone.utc)
    await db.commit()
    return success(request, {"profile": profile_payload(profile)})


@router.get("/session")
async def session(request: Request, profile: Profile = Depends(get_authenticated_profile)):
    return success(request, {"profile": profile_payload(profile)})


@router.post("/refresh")
async def refresh_session(
    request: Request,
    response: Response,
    refresh_token: str | None = Cookie(default=None),
):
    if not refresh_token:
        raise AppError("AUTH_INVALID_CREDENTIALS", "Refresh session is unavailable.", 401)
    async with httpx.AsyncClient(timeout=15) as client:
        auth_response = await client.post(
            f"{str(settings.SUPABASE_URL).rstrip('/')}/auth/v1/token?grant_type=refresh_token",
            headers={"apikey": settings.SUPABASE_PUBLISHABLE_KEY},
            json={"refresh_token": refresh_token},
        )
    if auth_response.status_code != 200:
        raise AppError("AUTH_INVALID_CREDENTIALS", "Session is invalid or expired.", 401)
    set_session_cookies(response, auth_response.json())
    return success(request, {"refreshed": True})


@router.post("/change-password")
async def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    response: Response,
    authorization: str | None = Header(default=None),
    profile: Profile = Depends(get_authenticated_profile),
    db: AsyncSession = Depends(get_db),
):
    token = access_token_from_request(request, authorization)
    if not token:
        raise AppError("AUTH_INVALID_CREDENTIALS", "Authentication is required.", 401)
    new_password = payload.new_password.get_secret_value()
    async with httpx.AsyncClient(timeout=15) as client:
        auth_response = await client.put(
            f"{str(settings.SUPABASE_URL).rstrip('/')}/auth/v1/user",
            headers={
                "apikey": settings.SUPABASE_PUBLISHABLE_KEY,
                "Authorization": f"Bearer {token}",
            },
            json={"password": new_password},
        )
        if auth_response.status_code != 200:
            raise AppError("PASSWORD_CHANGE_FAILED", "Password could not be changed.", 502)
        session_response = await client.post(
            f"{str(settings.SUPABASE_URL).rstrip('/')}/auth/v1/token?grant_type=password",
            headers={"apikey": settings.SUPABASE_PUBLISHABLE_KEY},
            json={"email": profile.auth_email_alias, "password": new_password},
        )
    if session_response.status_code != 200:
        raise AppError(
            "AUTH_SESSION_REFRESH_FAILED",
            "Password changed, but a new session could not be created. Sign in again.",
            401,
        )
    set_session_cookies(response, session_response.json())
    profile.must_change_password = False
    await db.commit()
    return success(request, {"profile": profile_payload(profile)})


@router.post("/logout", status_code=204)
async def logout(response: Response):
    response.delete_cookie("access_token", path="/")
    for index in range(ACCESS_COOKIE_CHUNK_LIMIT):
        response.delete_cookie(f"access_token_{index}", path="/")
    response.delete_cookie("refresh_token", path="/api/v1/auth")
