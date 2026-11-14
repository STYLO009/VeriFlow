"""Environment-driven configuration for the AI investigation layer.

Secrets are read from environment variables only. Nothing in this module ever
returns raw key material: ``redacted()`` is the single view used by status
endpoints so keys cannot leak into API responses, reports or audit logs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from typing import Any, Mapping

from ..env import load_env_file

# Canonical sliding windows accepted by the graph engine (see app/config.py).
VALID_WINDOWS: tuple[str, ...] = ("5s", "30s", "5m", "1h", "24h")
VALID_PROFILES: tuple[str, ...] = ("FAST", "STANDARD", "DEEP")


def _env_str(name: str, default: str | None = None) -> str | None:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw


def _env_float(name: str, default: float) -> float:
    raw = _env_str(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be a number, got {raw!r}") from exc


def _env_int(name: str, default: int) -> int:
    raw = _env_str(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be an integer, got {raw!r}") from exc


def _env_bool(name: str, default: bool) -> bool:
    raw = _env_str(name)
    if raw is None:
        return default
    return raw.lower() not in ("0", "false", "no", "off")


def _env_secret(*names: str) -> str | None:
    """First non-empty secret among ``names``.

    Template placeholders (``REPLACE_WITH_...``, ``<...>``, ``your-...``) are
    treated as *unset* so an unfilled ``.env`` never masquerades as a working
    key — a real but invalid key still surfaces as an AUTH error at request
    time (it is never silently hidden).
    """
    for name in names:
        raw = _env_str(name)
        if raw is None:
            continue
        probe = raw.strip()
        lowered = probe.lower()
        if lowered.startswith(("replace_with", "<", "your-", "your_", "xxx", "todo")):
            continue
        if len(probe) < 8:
            continue
        return probe
    return None


@dataclass(frozen=True)
class AIConfig:
    """Runtime configuration for the AI investigation layer."""

    # --- primary provider: Google Gemini ---------------------------------
    gemini_api_key: str | None = field(default=None)
    gemini_model: str = "gemini-2.5-flash"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"

    # --- secondary provider: Hugging Face Inference API -------------------
    huggingface_api_key: str | None = field(default=None)
    huggingface_model: str = "google/gemma-2-27b-it"
    huggingface_base_url: str = "https://router.huggingface.co/v1"

    # --- provider manager -------------------------------------------------
    provider_order: tuple[str, ...] = ("gemini", "huggingface")
    request_timeout_s: float = 45.0
    max_retries_per_provider: int = 1
    retry_backoff_s: float = 0.25
    max_tokens: int = 4096
    temperature: float = 0.1

    # --- bounded autonomy --------------------------------------------------
    max_tool_calls: int = 25
    max_steps: int = 8
    max_tools_per_step: int = 3
    max_wall_clock_s: float = 180.0
    max_stall_steps: int = 3
    recursion_limit: int = 60
    max_targets: int = 5
    max_llm_repairs: int = 1

    # --- evidence budgeting ------------------------------------------------
    tool_result_char_budget: int = 14_000
    evidence_context_char_budget: int = 40_000
    history_char_budget: int = 12_000

    # --- sessions / persistence / audit -----------------------------------
    state_dir: str | None = None
    audit_path: str | None = None
    cache_enabled: bool = True
    max_investigations: int = 200

    # --- graph access ------------------------------------------------------
    # When set, tools call the graph engine over HTTP (its own REST API).
    # When None (default) the same engine APIs are used in-process.
    graph_api_url: str | None = None
    graph_api_timeout_s: float = 15.0
    default_time_window: str = "24h"
    default_profile: str = "FAST"
    chat_max_extra_tool_calls: int = 4

    # ------------------------------------------------------------------ #
    @classmethod
    def from_env(cls, overrides: Mapping[str, Any] | None = None) -> "AIConfig":
        """Build config from ``MULEGRAPH_AI_*`` / provider key env vars."""
        # Ensure mulegraph/.env has been folded into os.environ (idempotent,
        # never overrides values already set in the process environment).
        load_env_file()
        gemini_key = _env_secret(
            "MULEGRAPH_AI_GEMINI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"
        )
        hf_key = _env_secret(
            "MULEGRAPH_AI_HF_API_KEY",
            "HF_API_KEY",
            "HUGGINGFACE_API_KEY",
        )
        data: dict[str, Any] = {
            "gemini_api_key": gemini_key,
            "gemini_model": _env_str("MULEGRAPH_AI_GEMINI_MODEL", "gemini-2.5-flash"),
            "gemini_base_url": _env_str(
                "MULEGRAPH_AI_GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"
            ),
            "huggingface_api_key": hf_key,
            "huggingface_model": _env_str(
                "MULEGRAPH_AI_HF_MODEL", "Qwen/Qwen2.5-72B-Instruct"
            ),
            "huggingface_base_url": _env_str(
                "MULEGRAPH_AI_HF_BASE_URL", "https://router.huggingface.co/v1"
            ),
            "request_timeout_s": _env_float("MULEGRAPH_AI_TIMEOUT_S", 45.0),
            "max_retries_per_provider": _env_int("MULEGRAPH_AI_MAX_RETRIES", 1),
            "max_tool_calls": _env_int("MULEGRAPH_AI_MAX_TOOL_CALLS", 25),
            "max_steps": _env_int("MULEGRAPH_AI_MAX_STEPS", 8),
            "max_tools_per_step": _env_int("MULEGRAPH_AI_MAX_TOOLS_PER_STEP", 3),
            "max_wall_clock_s": _env_float("MULEGRAPH_AI_MAX_WALL_CLOCK_S", 180.0),
            "max_tokens": _env_int("MULEGRAPH_AI_MAX_TOKENS", 4096),
            "temperature": _env_float("MULEGRAPH_AI_TEMPERATURE", 0.1),
            "state_dir": _env_str("MULEGRAPH_AI_STATE_DIR"),
            "audit_path": _env_str("MULEGRAPH_AI_AUDIT_PATH"),
            "cache_enabled": _env_bool("MULEGRAPH_AI_CACHE", True),
            "graph_api_url": _env_str("MULEGRAPH_AI_GRAPH_API_URL"),
            "default_time_window": _env_str("MULEGRAPH_AI_DEFAULT_WINDOW", "24h"),
            "default_profile": _env_str("MULEGRAPH_AI_DEFAULT_PROFILE", "FAST"),
        }
        if overrides:
            data.update({k: v for k, v in overrides.items() if k in data})
        return cls(**data)  # type: ignore[arg-type]

    # ------------------------------------------------------------------ #
    @property
    def has_primary(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def has_secondary(self) -> bool:
        return bool(self.huggingface_api_key)

    @property
    def any_provider_configured(self) -> bool:
        return self.has_primary or self.has_secondary

    def with_overrides(self, **kwargs: Any) -> "AIConfig":
        return replace(self, **{k: v for k, v in kwargs.items() if k in AIConfig.__dataclass_fields__})

    def redacted(self) -> dict[str, Any]:
        """Key-safe view of the config (never includes key material)."""
        return {
            "providers": [
                {
                    "id": "gemini",
                    "role": "primary",
                    "configured": self.has_primary,
                    "model": self.gemini_model,
                },
                {
                    "id": "huggingface",
                    "role": "secondary",
                    "configured": self.has_secondary,
                    "model": self.huggingface_model,
                },
            ],
            "provider_order": list(self.provider_order),
            "request_timeout_s": self.request_timeout_s,
            "max_retries_per_provider": self.max_retries_per_provider,
            "bounds": {
                "max_tool_calls": self.max_tool_calls,
                "max_steps": self.max_steps,
                "max_tools_per_step": self.max_tools_per_step,
                "max_wall_clock_s": self.max_wall_clock_s,
            },
            "default_time_window": self.default_time_window,
            "default_profile": self.default_profile,
            "graph_backend": "http" if self.graph_api_url else "in-process",
            "cache_enabled": self.cache_enabled,
            "persistence_enabled": bool(self.state_dir),
            "audit_enabled": bool(self.audit_path),
        }
