from __future__ import annotations

import hashlib, hmac, secrets
from dataclasses import dataclass, field
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError

OBVIOUS_PASSWORDS = {"admin", "password", "password123", "qwerty123456", "123456789012", "letmein123456"}
_ph = PasswordHasher()

@dataclass(frozen=True)
class Session:
    user_id: int
    token_hash: str


def validate_password(login: str, password: str, *, bootstrap: bool = False) -> None:
    if len(password) < 12:
        raise ValueError("Password must be at least 12 characters")
    if password.lower() == login.lower():
        raise ValueError("Password must not match login")
    if password.lower() in OBVIOUS_PASSWORDS:
        raise ValueError("Password is too obvious")
    if login == "admin" and password == "admin" and not bootstrap:
        raise ValueError("admin password is bootstrap-only")


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(hash_value: str, password: str) -> bool:
    try:
        return _ph.verify(hash_value, password)
    except (VerifyMismatchError, VerificationError):
        return False


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_session(user_id: int) -> tuple[str, Session]:
    token = secrets.token_urlsafe(32)
    return token, Session(user_id=user_id, token_hash=hash_token(token))


def csrf_token(session_token: str) -> str:
    return hmac.new(session_token.encode(), b"csrf", hashlib.sha256).hexdigest()


def verify_csrf(session_token: str, csrf_value: str) -> bool:
    return hmac.compare_digest(csrf_token(session_token), csrf_value or "")

@dataclass
class LoginRateLimiter:
    max_failures: int = 5
    window_seconds: int = 900
    failures: dict[str, list[int]] = field(default_factory=dict)

    def record_failure(self, login: str, now: int) -> None:
        items = [t for t in self.failures.get(login, []) if now - t <= self.window_seconds]
        items.append(now)
        self.failures[login] = items

    def is_blocked(self, login: str, now: int) -> bool:
        self.failures[login] = [t for t in self.failures.get(login, []) if now - t <= self.window_seconds]
        return len(self.failures[login]) >= self.max_failures
