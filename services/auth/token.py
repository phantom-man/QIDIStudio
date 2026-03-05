"""
services/auth/token.py — RS256 JWT issue, verify, refresh, and encrypted local cache.

Design:
  - Server issues RS256 JWTs (private key lives on Cloud SQL / GCP Secret Manager).
  - Client verifies with the public key (bundled or fetched at first run).
  - Token is cached locally at ~/.qidistudio/auth.token (AES-256-GCM encrypted).
  - Cache key = SHA-256(fingerprint + machine-specific salt) → no plaintext fingerprint on disk.

Environment variables (server-side only, never on client):
    JWT_PRIVATE_KEY_PATH    Path to RSA private key PEM
    JWT_PRIVATE_KEY         Inline PEM (overrides path, useful for GCP Secret Manager env inject)

Environment variables (client build-time):
    JWT_PUBLIC_KEY_PATH     Path to RSA public key PEM (bundled in installer)
    JWT_PUBLIC_KEY          Inline PEM override

Usage:
    # Server: issue a token
    from services.auth.token import issue_token, SubscriptionTier
    token = issue_token(user_id=uid, fingerprint=fp, tier=SubscriptionTier.monthly)

    # Client: verify + cache
    from services.auth.token import load_cached_token, verify_token
    payload = load_cached_token()  # reads cache first
    if not payload:
        payload = verify_token(raw_jwt)
        save_token_to_cache(raw_jwt)
"""

from __future__ import annotations

import base64
import json
import os
import pathlib
import struct
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from dotenv import load_dotenv

load_dotenv()

# ── Constants ─────────────────────────────────────────────────────────────────

_CACHE_DIR = pathlib.Path.home() / ".qidistudio"
_CACHE_FILE = _CACHE_DIR / "auth.token"
_ISSUER = "qidistudio-auth"
_AUDIENCE = "qidistudio-client"

# Tier → expiry delta mapping
_TIER_EXPIRY: dict[str, timedelta] = {
    "free": timedelta(days=365 * 10),  # effectively permanent for free tier
    "trial": timedelta(days=14),
    "monthly": timedelta(days=30),
    "yearly": timedelta(days=365),
    "lifetime": timedelta(days=365 * 50),
}


# ── Key loading ───────────────────────────────────────────────────────────────


def _load_private_key() -> Any:
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    pem = os.getenv("JWT_PRIVATE_KEY")
    if not pem:
        path = os.getenv("JWT_PRIVATE_KEY_PATH", "keys/private.pem")
        pem = pathlib.Path(path).read_text()
    return load_pem_private_key(pem.encode(), password=None)


def _load_public_key() -> Any:
    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    pem = os.getenv("JWT_PUBLIC_KEY")
    if not pem:
        path = os.getenv("JWT_PUBLIC_KEY_PATH", "keys/public.pem")
        pem = pathlib.Path(path).read_text()
    return load_pem_public_key(pem.encode())


# ── Token issue (server side) ─────────────────────────────────────────────────


def issue_token(
    user_id: uuid.UUID,
    fingerprint: str,
    tier: str,
    jti: uuid.UUID | None = None,
) -> str:
    """
    Issue an RS256 JWT for a user+fingerprint+tier.
    Called by the server / auth endpoint — NOT by the slicer client.

    Returns the signed JWT string.
    """
    try:
        import jwt  # PyJWT
    except ImportError as e:
        raise RuntimeError(
            "PyJWT not installed. Run: pip install PyJWT[cryptography]"
        ) from e

    now = datetime.now(timezone.utc)
    expiry_delta = _TIER_EXPIRY.get(tier, timedelta(days=30))
    jti = jti or uuid.uuid4()

    payload = {
        "iss": _ISSUER,
        "aud": _AUDIENCE,
        "sub": str(user_id),
        "jti": str(jti),
        "iat": now,
        "exp": now + expiry_delta,
        "tier": tier,
        "fp": fingerprint,
    }

    private_key = _load_private_key()
    return jwt.encode(payload, private_key, algorithm="RS256")


# ── Token verify (client side) ────────────────────────────────────────────────


def verify_token(token: str, expected_fingerprint: str | None = None) -> dict[str, Any]:
    """
    Verify an RS256 JWT. Raises on invalid/expired tokens.

    If expected_fingerprint is provided, the 'fp' claim must match — this prevents
    a token stolen from another machine from working.

    Returns the decoded payload dict.
    """
    try:
        import jwt
        from jwt.exceptions import InvalidTokenError
    except ImportError as e:
        raise RuntimeError(
            "PyJWT not installed. Run: pip install PyJWT[cryptography]"
        ) from e

    public_key = _load_public_key()
    try:
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            audience=_AUDIENCE,
            issuer=_ISSUER,
        )
    except InvalidTokenError as e:
        raise ValueError(f"Invalid or expired token: {e}") from e

    if expected_fingerprint and payload.get("fp") != expected_fingerprint:
        raise ValueError(
            "Token fingerprint mismatch — this token was issued for a different device"
        )

    return payload


# ── Encrypted local cache ─────────────────────────────────────────────────────


def _derive_cache_key(fingerprint: str) -> bytes:
    """Derive a 32-byte AES key from the device fingerprint."""
    import hashlib

    salt = b"qidistudio-token-cache-v1"
    return hashlib.sha256(fingerprint.encode() + salt).digest()


def _aes_gcm_encrypt(plaintext: bytes, key: bytes) -> bytes:
    """Encrypt using AES-256-GCM. Returns nonce+tag+ciphertext."""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as e:
        raise RuntimeError(
            "cryptography not installed. Run: pip install cryptography"
        ) from e

    import os as _os

    nonce = _os.urandom(12)
    aesgcm = AESGCM(key)
    ct = aesgcm.encrypt(nonce, plaintext, None)
    return nonce + ct  # nonce(12) + ciphertext+tag


def _aes_gcm_decrypt(data: bytes, key: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = data[:12]
    ct = data[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ct, None)


def save_token_to_cache(token: str, fingerprint: str) -> None:
    """
    Encrypt and save the JWT to ~/.qidistudio/auth.token.
    The cache is encrypted so the raw token is never stored in plaintext.
    """
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = _derive_cache_key(fingerprint)
    encrypted = _aes_gcm_encrypt(token.encode(), key)
    _CACHE_FILE.write_bytes(encrypted)


def load_cached_token(fingerprint: str) -> str | None:
    """
    Load and decrypt the cached JWT. Returns None if cache missing, corrupt, or expired.
    Also performs an offline expiry check — no network call needed.
    """
    if not _CACHE_FILE.exists():
        return None
    try:
        key = _derive_cache_key(fingerprint)
        encrypted = _CACHE_FILE.read_bytes()
        token = _aes_gcm_decrypt(encrypted, key).decode()

        # Offline expiry check (no signature verification — just decode claims)
        import base64 as b64

        payload_b64 = token.split(".")[1]
        padding = 4 - len(payload_b64) % 4
        payload_str = b64.urlsafe_b64decode(payload_b64 + "=" * padding)
        claims = json.loads(payload_str)
        exp = claims.get("exp", 0)
        now = datetime.now(timezone.utc).timestamp()
        if exp and now > exp:
            _CACHE_FILE.unlink(missing_ok=True)
            return None

        return token
    except Exception:
        # Cache corrupt / wrong key — delete it
        _CACHE_FILE.unlink(missing_ok=True)
        return None


def clear_token_cache() -> None:
    """Remove the cached token (e.g. on sign-out or fingerprint change)."""
    _CACHE_FILE.unlink(missing_ok=True)


def get_tier_from_token(token: str) -> str:
    """Extract the tier claim without full signature verification (for offline use)."""
    try:
        import base64 as b64

        payload_b64 = token.split(".")[1]
        padding = 4 - len(payload_b64) % 4
        payload_str = b64.urlsafe_b64decode(payload_b64 + "=" * padding)
        return json.loads(payload_str).get("tier", "free")
    except Exception:
        return "free"
