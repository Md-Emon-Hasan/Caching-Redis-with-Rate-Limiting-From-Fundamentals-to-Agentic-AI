"""
security.py
===========
Password hashing + session-ID generation. Small file, but two ideas here are
worth remembering because interviewers ask about both.

1) NEVER store raw passwords, and never use a fast hash (md5/sha256) alone.
   We use PBKDF2-HMAC-SHA256 with a random per-user salt and many iterations,
   which makes brute force expensive. (In production prefer argon2id or bcrypt
   via `passlib`; PBKDF2 is used here so the project has zero extra deps.)

2) A session ID is a *bearer secret*: whoever holds it IS the user.
   So it must be
     - generated with a CSPRNG (`secrets`, not `random`)
     - long enough (>=128 bits of entropy)
     - compared in constant time when you compare secrets
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

_PBKDF2_ITERATIONS = 200_000
_SALT_BYTES = 16


def hash_password(password: str) -> str:
    """Return 'pbkdf2$<iterations>$<salt_hex>$<hash_hex>' - self-describing."""
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time verification. Returns False on any malformed input."""
    try:
        algo, iterations, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations)
        )
    except (ValueError, TypeError):
        return False
    # compare_digest prevents timing attacks (do not use ==).
    return hmac.compare_digest(digest.hex(), hash_hex)


def new_session_id() -> str:
    """256 bits of entropy, URL-safe -> safe to put in a cookie."""
    return secrets.token_urlsafe(32)


def new_csrf_token() -> str:
    return secrets.token_urlsafe(24)
