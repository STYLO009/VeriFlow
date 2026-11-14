"""Argument validation and sanitisation for AI graph tools.

Every argument that reaches a graph tool passes through here (in addition to
the Pydantic ``args_schema``), so an LLM cannot inject arbitrary identifiers,
windows or oversized traversals. Nothing here ever executes model-supplied
code: only fixed, read-only tool handlers exist.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from ..config import VALID_PROFILES, VALID_WINDOWS

ACCOUNT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:\-]{0,63}$")
TRANSACTION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:\-]{0,63}$")
INJECTION_PATTERNS = (
    re.compile(r"\bignore\s+(all\s+)?(previous|prior|above)\b", re.IGNORECASE),
    re.compile(r"\bdisregard\s+(the\s+)?(system|previous|instructions)\b", re.IGNORECASE),
    re.compile(r"\bsystem\s+prompt\b", re.IGNORECASE),
    re.compile(r"\bnew\s+instructions?\b", re.IGNORECASE),
    re.compile(r"\bact\s+as\s+an?\s+unrestricted\b", re.IGNORECASE),
)


class ToolValidationError(ValueError):
    """Invalid tool argument - reported to the model, never executed."""

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


class ToolExecutionError(RuntimeError):
    """A read-only graph tool failed while executing."""


def validate_account_id(value: Any, field: str = "account_id") -> str:
    if not isinstance(value, str):
        raise ToolValidationError(field, "must be a string")
    text = value.strip()
    if not text:
        raise ToolValidationError(field, "must not be empty")
    if not ACCOUNT_ID_RE.match(text):
        raise ToolValidationError(
            field,
            "must be 1-64 chars of [A-Za-z0-9_.:-] starting with a letter or digit",
        )
    return text


def validate_transaction_id(value: Any, field: str = "transaction_id") -> str:
    if not isinstance(value, str):
        raise ToolValidationError(field, "must be a string")
    text = value.strip()
    if not text:
        raise ToolValidationError(field, "must not be empty")
    if not TRANSACTION_ID_RE.match(text):
        raise ToolValidationError(field, "contains unsupported characters")
    return text


def validate_window(value: Any, default: str = "24h", field: str = "window") -> str:
    if value is None or value == "":
        return default
    if not isinstance(value, str):
        raise ToolValidationError(field, "must be a string")
    text = value.strip().lower()
    if text not in VALID_WINDOWS:
        raise ToolValidationError(
            field, f"must be one of {', '.join(VALID_WINDOWS)} (got {value!r})"
        )
    return text


def validate_profile(value: Any, default: str = "FAST", field: str = "profile") -> str:
    if value is None or value == "":
        return default
    if not isinstance(value, str):
        raise ToolValidationError(field, "must be a string")
    text = value.strip().upper()
    if text not in VALID_PROFILES:
        raise ToolValidationError(
            field, f"must be one of {', '.join(VALID_PROFILES)} (got {value!r})"
        )
    return text


def validate_int(
    value: Any,
    field: str,
    minimum: int | None = None,
    maximum: int | None = None,
    default: int | None = None,
) -> int:
    if value is None or value == "":
        if default is not None:
            return default
        raise ToolValidationError(field, "is required")
    if isinstance(value, bool):
        raise ToolValidationError(field, "must be an integer")
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ToolValidationError(field, f"must be an integer (got {value!r})") from None
    if minimum is not None and number < minimum:
        raise ToolValidationError(field, f"must be >= {minimum} (got {number})")
    if maximum is not None and number > maximum:
        raise ToolValidationError(field, f"must be <= {maximum} (got {number})")
    return number


def validate_float(
    value: Any,
    field: str,
    minimum: float | None = None,
    maximum: float | None = None,
    default: float | None = None,
) -> float | None:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        raise ToolValidationError(field, "must be a number")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ToolValidationError(field, f"must be a number (got {value!r})") from None
    if minimum is not None and number < minimum:
        raise ToolValidationError(field, f"must be >= {minimum}")
    if maximum is not None and number > maximum:
        raise ToolValidationError(field, f"must be <= {maximum}")
    return number


def validate_bool(value: Any, field: str, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ("true", "false", "1", "0"):
        return value.lower() in ("true", "1")
    raise ToolValidationError(field, "must be a boolean")


def validate_account_list(
    value: Any, field: str = "account_ids", minimum: int = 1, maximum: int = 10
) -> list[str]:
    if value is None:
        raise ToolValidationError(field, "is required")
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        raise ToolValidationError(field, "must be a list of account ids")
    items = list(value)
    if len(items) < minimum:
        raise ToolValidationError(field, f"needs at least {minimum} account id(s)")
    if len(items) > maximum:
        raise ToolValidationError(field, f"supports at most {maximum} account ids")
    return [validate_account_id(v, field=f"{field}[{i}]") for i, v in enumerate(items)]


def validate_question(value: Any, field: str = "question", max_length: int = 4000) -> str:
    if not isinstance(value, str):
        raise ToolValidationError(field, "must be a string")
    # drop control characters, keep printable text + newlines/tabs
    text = "".join(ch for ch in value if ch.isprintable() or ch in ("\n", "\t")).strip()
    if not text:
        raise ToolValidationError(field, "must not be empty")
    if len(text) > max_length:
        text = text[:max_length]
    return text


def find_injection_markers(text: str) -> list[str]:
    """Detect prompt-injection style content in *untrusted* data.

    Used only to tag/wrap content as untrusted for the model - never to
    execute or obey it.
    """
    if not isinstance(text, str):
        return []
    return [p.pattern for p in INJECTION_PATTERNS if p.search(text)]


def clamp_sequence(items: Iterable[Any], maximum: int) -> list[Any]:
    return list(items)[:maximum]


__all__ = [
    "ToolExecutionError",
    "ToolValidationError",
    "clamp_sequence",
    "find_injection_markers",
    "validate_account_id",
    "validate_account_list",
    "validate_bool",
    "validate_float",
    "validate_int",
    "validate_profile",
    "validate_question",
    "validate_transaction_id",
    "validate_window",
]
