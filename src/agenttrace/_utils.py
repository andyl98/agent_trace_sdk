"""Internal utilities for agenttrace."""

from __future__ import annotations

import datetime
import json
import uuid
from typing import Any
from zoneinfo import ZoneInfo

# Use the real Pacific time zone so timestamps track daylight saving time.
PST = ZoneInfo("America/Los_Angeles")


def pst_now_iso() -> str:
    """Return current Pacific time as an ISO 8601 string."""
    return datetime.datetime.now(PST).isoformat()


# Keep as alias for backwards compatibility in external callers
utc_now_iso = pst_now_iso


def new_id() -> str:
    """Generate a new UUID4 hex string (32 chars, no dashes)."""
    return uuid.uuid4().hex


def safe_json_dumps(obj: Any, max_bytes: int = 65536) -> str:
    """JSON-serialize with truncation and fallback for non-serializable types."""
    try:
        raw = json.dumps(obj, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        raw = json.dumps({"_error": "unserializable"})
    if len(raw.encode("utf-8")) > max_bytes:
        raw = raw[: max_bytes - 20] + '..."_truncated":true}'
    return raw


def redact_dict(d: dict[str, Any], keys_to_redact: list[str]) -> dict[str, Any]:
    """Return a copy with specified keys replaced by '[REDACTED]'. Case-insensitive."""
    lower_keys = {k.lower() for k in keys_to_redact}
    return {k: "[REDACTED]" if k.lower() in lower_keys else v for k, v in d.items()}
