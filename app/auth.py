from __future__ import annotations

import base64
import hashlib
import hmac
import time
from dataclasses import dataclass

from .config import Settings


ACCESS_COOKIE_NAME = "ps_access"
ACCESS_PREFIX = "access"
ACCESS_ROLES = {"admin", "demo"}


@dataclass(frozen=True)
class AccessSession:
    role: str
    owner_id: str
    issued_at: int

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def is_demo(self) -> bool:
        return self.role == "demo"


def _signature(settings: Settings, payload: str) -> str:
    return hmac.new(
        settings.secret_key.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def make_access_cookie(settings: Settings, role: str, owner_id: str) -> str:
    if role not in ACCESS_ROLES:
        raise ValueError("Invalid access role")
    payload = f"{ACCESS_PREFIX}:{role}:{owner_id}:{int(time.time())}"
    signed = f"{payload}:{_signature(settings, payload)}"
    return base64.urlsafe_b64encode(signed.encode("utf-8")).decode("ascii")


def read_access_cookie(settings: Settings, cookie_value: str | None) -> AccessSession | None:
    if not cookie_value:
        return None
    try:
        decoded = base64.urlsafe_b64decode(cookie_value.encode("ascii")).decode("utf-8")
        prefix, role, owner_id, issued_at_raw, supplied_signature = decoded.rsplit(":", 4)
        payload = f"{prefix}:{role}:{owner_id}:{issued_at_raw}"
        issued_at = int(issued_at_raw)
    except (ValueError, TypeError, UnicodeDecodeError):
        return None

    if prefix != ACCESS_PREFIX or role not in ACCESS_ROLES or not owner_id:
        return None
    if int(time.time()) - issued_at > settings.access_remember_max_age_seconds:
        return None

    expected_signature = _signature(settings, payload)
    if not hmac.compare_digest(supplied_signature, expected_signature):
        return None
    return AccessSession(role=role, owner_id=owner_id, issued_at=issued_at)


def admin_password_matches(settings: Settings, supplied_password: str) -> bool:
    if not settings.admin_password:
        return False
    return hmac.compare_digest(settings.admin_password, supplied_password)
