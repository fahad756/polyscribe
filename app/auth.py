from __future__ import annotations

import base64
import hashlib
import hmac
import time

from .config import Settings


SESSION_PREFIX = "authenticated"


def auth_enabled(settings: Settings) -> bool:
    return bool(settings.app_password)


def _signature(settings: Settings, payload: str) -> str:
    return hmac.new(
        settings.secret_key.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def make_session_cookie(settings: Settings) -> str:
    payload = f"{SESSION_PREFIX}:{int(time.time())}"
    signed = f"{payload}:{_signature(settings, payload)}"
    return base64.urlsafe_b64encode(signed.encode("utf-8")).decode("ascii")


def verify_session_cookie(settings: Settings, cookie_value: str | None) -> bool:
    if not auth_enabled(settings) or not cookie_value:
        return not auth_enabled(settings)
    try:
        decoded = base64.urlsafe_b64decode(cookie_value.encode("ascii")).decode("utf-8")
        prefix, issued_at_raw, supplied_signature = decoded.rsplit(":", 2)
        payload = f"{prefix}:{issued_at_raw}"
        issued_at = int(issued_at_raw)
    except (ValueError, TypeError, UnicodeDecodeError):
        return False

    if prefix != SESSION_PREFIX:
        return False
    if int(time.time()) - issued_at > settings.session_max_age_seconds:
        return False

    expected_signature = _signature(settings, payload)
    return hmac.compare_digest(supplied_signature, expected_signature)


def password_matches(settings: Settings, supplied_password: str) -> bool:
    return hmac.compare_digest(settings.app_password, supplied_password)

