"""Bounded summarization of tool outputs for model context.

Rules:
* Never drop transaction-id references until it is absolutely necessary;
  when they must be reduced, an explicit truncation marker is added so the
  model (and the audit trail) can see that evidence was omitted.
* Never silently rewrite values - trimming is always flagged.
"""

from __future__ import annotations

import json
from typing import Any

TRUNCATION_KEY = "_context_limit"
TRANSACTION_KEY_HINTS = ("transaction_id", "tx_id", "transaction_ids")


def _dumps(obj: Any) -> str:
    try:
        return json.dumps(obj, default=str, separators=(",", ":"))
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return str(obj)


def _is_transaction_key(key: str) -> bool:
    lowered = key.lower()
    return any(hint in lowered for hint in TRANSACTION_KEY_HINTS)


def _fit_list(items: list[Any], budget: int) -> list[Any]:
    """Keep as many list items as fit inside ``budget`` characters."""
    kept: list[Any] = []
    used = 2  # []
    for item in items:
        piece = _dumps(item)
        if used + len(piece) + 1 > budget:
            break
        kept.append(item)
        used += len(piece) + 1
    return kept


def _trim(obj: Any, budget: int, depth: int = 0) -> Any:
    if budget < 64:
        return {"_truncated": True, "reason": "budget_exhausted", "depth": depth}
    if depth > 12:
        return {"_truncated": True, "reason": "max_depth"}

    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        used = 2
        deferred: list[tuple[str, Any]] = []

        # pass 1: transaction references get priority
        for key, value in obj.items():
            if not _is_transaction_key(key):
                continue
            size = len(_dumps(value)) + len(key) + 6
            if used + size <= budget:
                out[key] = value
                used += size
            elif isinstance(value, list):
                keep = _fit_list(value, max(64, budget - used - 32))
                out[key] = keep
                used += len(_dumps(keep))
                if len(keep) < len(value):
                    out[TRUNCATION_KEY] = {
                        "field": key,
                        "kept": len(keep),
                        "omitted": len(value) - len(keep),
                    }
            else:
                deferred.append((key, value))

        # pass 2: everything else in original order
        for key, value in obj.items():
            if _is_transaction_key(key) and key in out:
                continue
            size = len(_dumps(value)) + len(key) + 6
            if used + size <= budget:
                out[key] = value
                used += size
                continue
            remaining = budget - used
            if remaining > 200:
                shrunk = _trim(value, remaining - 20, depth + 1)
                out[key] = shrunk
                used += len(_dumps(shrunk))
            else:
                deferred.append((key, value))

        if deferred:
            out.setdefault(
                TRUNCATION_KEY,
                {"dropped_fields": [k for k, _ in deferred], "original_chars": len(_dumps(obj))},
            )
        return out

    if isinstance(obj, list):
        keep = _fit_list(obj, budget - 64)
        if len(keep) < len(obj):
            keep = keep + [
                {
                    "_truncated": True,
                    "omitted_items": len(obj) - len(keep),
                    "original_chars": len(_dumps(obj)),
                }
            ]
        return keep

    raw = _dumps(obj)
    if len(raw) <= budget:
        return obj
    text = str(obj)
    return text[: max(0, budget - 24)] + "...[truncated]"


def summarize_payload(payload: Any, budget: int) -> tuple[Any, bool]:
    """Return ``(payload_or_trimmed_copy, was_truncated)`` within ``budget``."""
    if payload is None:
        return None, False
    raw = _dumps(payload)
    if len(raw) <= budget:
        return payload, False
    return _trim(payload, budget), True


def summarize_text(text: str, budget: int) -> tuple[str, bool]:
    if len(text) <= budget:
        return text, False
    return text[: max(0, budget - 20)] + "...[truncated]", True


__all__ = ["summarize_payload", "summarize_text", "TRUNCATION_KEY"]
