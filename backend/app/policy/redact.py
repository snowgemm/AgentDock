"""Best-effort secret redaction for audit records, approval displays and tool output."""
from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED]"
_SENSITIVE_KEY = re.compile(r"(secret|token|passw|api[_-]?key|authorization|credential|private[_-]?key|cookie)", re.I)
_SECRET_VALUE = re.compile(
    r"(sk-[A-Za-z0-9_-]{8,}|Bearer\s+[A-Za-z0-9._~+/=-]{8,}|ghp_[A-Za-z0-9]{16,}|"
    r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}|AKIA[0-9A-Z]{12,})"
)
MAX_DEPTH = 6
MAX_STRING = 2_000


def redact(value: Any, depth: int = 0) -> Any:
    if depth > MAX_DEPTH:
        return REDACTED
    if isinstance(value, dict):
        return {
            str(key): REDACTED if _SENSITIVE_KEY.search(str(key)) else redact(item, depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item, depth + 1) for item in value][:100]
    if isinstance(value, str):
        return _SECRET_VALUE.sub(REDACTED, value)[:MAX_STRING]
    return value
