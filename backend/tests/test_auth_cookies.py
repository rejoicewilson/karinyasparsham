from starlette.requests import Request
from starlette.responses import Response

from app.api.v1.routes.auth import set_session_cookies
from app.core.security import access_token_from_request


def test_large_access_token_is_split_and_reconstructed():
    token = "header." + ("x" * 6900) + ".signature"
    response = Response()

    set_session_cookies(
        response,
        {"access_token": token, "refresh_token": "refresh", "expires_in": 3600},
    )

    set_cookie_headers = response.headers.getlist("set-cookie")
    active_chunks = [
        header for header in set_cookie_headers
        if header.startswith("access_token_") and "Max-Age=3600" in header
    ]
    assert len(active_chunks) == 3
    assert all(len(header) < 4096 for header in active_chunks)

    cookie_header = "; ".join(header.split(";", 1)[0] for header in active_chunks)
    request = Request({"type": "http", "headers": [(b"cookie", cookie_header.encode())]})
    assert access_token_from_request(request) == token


def test_legacy_access_cookie_remains_supported():
    request = Request({"type": "http", "headers": [(b"cookie", b"access_token=legacy-token")]})
    assert access_token_from_request(request) == "legacy-token"
