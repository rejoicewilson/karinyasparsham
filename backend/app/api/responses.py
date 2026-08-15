from typing import Any

from fastapi import Request


def success(request: Request, data: Any, **meta: Any) -> dict[str, Any]:
    return {
        "data": data,
        "meta": {"request_id": getattr(request.state, "request_id", None), **meta},
    }
