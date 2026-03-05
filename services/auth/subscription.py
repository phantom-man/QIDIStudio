"""
services/auth/subscription.py — Startup subscription gate for QIDIStudio.

Called once at slicer startup by the Python sidecar. Flow:

  1. Compute device fingerprint
  2. Load cached JWT from ~/.qidistudio/auth.token
  3. If cached token valid → return tier (no network call)
  4. If expired or missing → call auth endpoint to refresh
  5. If network unavailable → use grace period (72h after expiry)
  6. Return effective tier ('free' | 'trial' | 'monthly' | 'yearly' | 'lifetime')

The returned tier is used by preset_fetcher.py to decide what data to download.

Usage:
    from services.auth.subscription import SubscriptionCheck, resolve_tier

    result = await resolve_tier()
    print(result.tier)       # "monthly"
    print(result.is_pro)     # True
    print(result.expires_at) # datetime(...)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from dotenv import load_dotenv

from services.auth.fingerprint import get_device_fingerprint, get_platform
from services.auth.token import (
    clear_token_cache,
    get_tier_from_token,
    load_cached_token,
    save_token_to_cache,
    verify_token,
)

load_dotenv()

_AUTH_BASE_URL = os.getenv("QIDISTUDIO_AUTH_URL", "https://auth.qidistudio.com")
_GRACE_PERIOD_HOURS = int(os.getenv("AUTH_GRACE_PERIOD_HOURS", "72"))


# ── Result type ───────────────────────────────────────────────────────────────


@dataclass
class SubscriptionCheck:
    tier: str  # free | trial | monthly | yearly | lifetime
    is_pro: bool
    expires_at: datetime | None
    fingerprint: str
    source: str  # "cache" | "network" | "grace" | "offline_free"
    error: str | None = None

    @classmethod
    def free(
        cls, fingerprint: str, source: str = "offline_free", error: str | None = None
    ) -> "SubscriptionCheck":
        return cls(
            tier="free",
            is_pro=False,
            expires_at=None,
            fingerprint=fingerprint,
            source=source,
            error=error,
        )

    @classmethod
    def from_token_payload(
        cls, payload: dict[str, Any], fingerprint: str, source: str
    ) -> "SubscriptionCheck":
        tier = payload.get("tier", "free")
        exp_ts = payload.get("exp")
        expires_at = datetime.fromtimestamp(exp_ts, tz=timezone.utc) if exp_ts else None
        return cls(
            tier=tier,
            is_pro=tier in ("trial", "monthly", "yearly", "lifetime"),
            expires_at=expires_at,
            fingerprint=fingerprint,
            source=source,
        )


# ── Grace period cache ────────────────────────────────────────────────────────

import pathlib
import json

_GRACE_FILE = pathlib.Path.home() / ".qidistudio" / "grace.json"


def _enter_grace_period(tier: str, expires_at: datetime) -> None:
    """Record when grace period started so we can enforce the 72h cap."""
    _GRACE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _GRACE_FILE.write_text(
        json.dumps(
            {
                "tier": tier,
                "token_expired_at": expires_at.isoformat(),
                "grace_started_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    )


def _check_grace_period(original_tier: str) -> SubscriptionCheck | None:
    """
    If we're inside the 72h grace window, return original tier.
    If grace expired, return None (caller will downgrade to free).
    """
    if not _GRACE_FILE.exists():
        return None
    try:
        data = json.loads(_GRACE_FILE.read_text())
        grace_started = datetime.fromisoformat(data["grace_started_at"])
        if datetime.now(timezone.utc) <= grace_started + timedelta(
            hours=_GRACE_PERIOD_HOURS
        ):
            fp = get_device_fingerprint()
            return SubscriptionCheck(
                tier=data["tier"],
                is_pro=True,
                expires_at=grace_started + timedelta(hours=_GRACE_PERIOD_HOURS),
                fingerprint=fp,
                source="grace",
            )
        # Grace expired
        _GRACE_FILE.unlink(missing_ok=True)
    except Exception:
        _GRACE_FILE.unlink(missing_ok=True)
    return None


# ── Network refresh ───────────────────────────────────────────────────────────


async def _refresh_from_network(fingerprint: str) -> SubscriptionCheck:
    """
    Call the auth service to get/refresh a JWT for this device.
    Returns SubscriptionCheck with source="network".
    """
    payload = {
        "fingerprint": fingerprint,
        "platform": get_platform(),
        "client_version": os.getenv("QIDISTUDIO_VERSION", "unknown"),
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{_AUTH_BASE_URL}/v1/token/refresh", json=payload)
            resp.raise_for_status()
            data = resp.json()

        token = data.get("token")
        if not token:
            return SubscriptionCheck.free(
                fingerprint, source="network", error="No token in response"
            )

        # Verify the token before caching
        token_payload = verify_token(token, expected_fingerprint=fingerprint)
        save_token_to_cache(token, fingerprint)
        # Clear any stale grace period
        _GRACE_FILE.unlink(missing_ok=True)

        return SubscriptionCheck.from_token_payload(
            token_payload, fingerprint, source="network"
        )

    except httpx.HTTPStatusError as e:
        if e.response.status_code in (401, 403):
            # Rejected by server → downgrade to free
            clear_token_cache()
            return SubscriptionCheck.free(fingerprint, source="network", error=str(e))
        raise
    except (httpx.RequestError, Exception) as e:
        raise RuntimeError(f"Auth network call failed: {e}") from e


# ── Main entry point ──────────────────────────────────────────────────────────


async def resolve_tier() -> SubscriptionCheck:
    """
    Resolve the effective subscription tier for this device.

    Priority order:
      1. Valid cached JWT on disk (fast path — no network)
      2. Network refresh if cache expired
      3. Grace period fallback (72h window after token expiry)
      4. Free tier as final fallback

    This is designed to be called once per slicer startup and cached
    in memory for the rest of the session.
    """
    fingerprint = get_device_fingerprint()

    # 1. Check cache
    cached_token = load_cached_token(fingerprint)
    if cached_token:
        try:
            payload = verify_token(cached_token, expected_fingerprint=fingerprint)
            return SubscriptionCheck.from_token_payload(
                payload, fingerprint, source="cache"
            )
        except ValueError:
            # Token invalid (tampered / wrong key) — clear it
            clear_token_cache()

    # 2. Try network refresh
    try:
        return await _refresh_from_network(fingerprint)
    except RuntimeError:
        pass  # Network unavailable — fall through to grace period

    # Determine if we have a recently-expired token to use for grace period
    expired_tier = "free"
    try:
        if cached_token:
            expired_tier = get_tier_from_token(cached_token)
    except Exception:
        pass

    # 3. Grace period
    grace = _check_grace_period(expired_tier)
    if grace:
        return grace

    # Enter a new grace period if we had a pro tier (token just expired, network down)
    if expired_tier not in ("free",):
        try:
            import base64, json as _json

            part = cached_token.split(".")[1] if cached_token else ""
            if part:
                padding = 4 - len(part) % 4
                import base64 as b64

                claims = _json.loads(b64.urlsafe_b64decode(part + "=" * padding))
                exp = claims.get("exp", 0)
                if exp:
                    expired_at = datetime.fromtimestamp(exp, tz=timezone.utc)
                    _enter_grace_period(expired_tier, expired_at)
                    grace = _check_grace_period(expired_tier)
                    if grace:
                        return grace
        except Exception:
            pass

    # 4. Free tier fallback
    return SubscriptionCheck.free(fingerprint, source="offline_free")


def resolve_tier_sync() -> SubscriptionCheck:
    """
    Synchronous wrapper — uses asyncio.run() so it can be called from non-async code
    (e.g. the C++ process spawner before the asyncio event loop is set up).
    """
    import asyncio

    return asyncio.run(resolve_tier())
