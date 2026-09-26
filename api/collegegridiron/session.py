"""Validate a TPE session against the shared wagechecker accounts API."""

from __future__ import annotations

import json
import time
import urllib.request
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from collegegridiron.config import TPE_API_URL

COOKIE = "tpe_session"
TTL = 45
_cache: dict[str, tuple[float, dict | None]] = {}


def read_token(request: Request) -> str | None:
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        token = header[7:].strip()
        if token:
            return token
    return request.cookies.get(COOKIE)


def _fetch_user(token: str) -> dict | None:
    if not TPE_API_URL:
        return None
    req = urllib.request.Request(
        f"{TPE_API_URL}/api/auth/me",
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "collegegridiron-desk",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=4) as res:
            data = json.loads(res.read().decode())
    except Exception:
        return None
    if not isinstance(data, dict) or not data.get("id"):
        return None
    return data


def user_for_token(token: str | None) -> dict | None:
    if not token:
        return None
    now = time.time()
    cached = _cache.get(token)
    if cached and now - cached[0] < TTL:
        return cached[1]
    user = _fetch_user(token)
    _cache[token] = (now, user)
    if len(_cache) > 200:
        for key, (stamp, _) in list(_cache.items()):
            if now - stamp > TTL:
                _cache.pop(key, None)
    return user


def require_user(request: Request) -> dict:
    user = user_for_token(read_token(request))
    if not user:
        raise HTTPException(401, "Sign in required.")
    return user


def optional_user(request: Request) -> dict | None:
    return user_for_token(read_token(request))


User = Annotated[dict, Depends(require_user)]
OptionalUser = Annotated[dict | None, Depends(optional_user)]
