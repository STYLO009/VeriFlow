"""Environment-based configuration for the MuleGraph graph engine.

All settings can be overridden with ``MULEGRAPH_*`` environment variables so
the engine behaves the same on a developer laptop and in a deployment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Mapping

# Canonical sliding-window presets (seconds).
WINDOW_PRESETS: dict[str, float] = {
    "5s": 5.0,
    "30s": 30.0,
    "5m": 300.0,
    "1h": 3600.0,
    "24h": 86400.0,
}


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be a number, got {raw!r}") from exc


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be an integer, got {raw!r}") from exc


def _env_str(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class GraphConfig:
    """Runtime configuration for graph construction and analysis."""

    # --- structural limits -------------------------------------------------
    max_nodes: int = field(default_factory=lambda: _env_int("MULEGRAPH_MAX_NODES", 200_000))
    max_edges: int = field(default_factory=lambda: _env_int("MULEGRAPH_MAX_EDGES", 2_000_000))
    max_degree: int = field(default_factory=lambda: _env_int("MULEGRAPH_MAX_DEGREE", 5_000))

    # --- traversal limits --------------------------------------------------
    max_hops: int = field(default_factory=lambda: _env_int("MULEGRAPH_MAX_HOPS", 6))
    max_paths: int = field(default_factory=lambda: _env_int("MULEGRAPH_MAX_PATHS", 25))
    max_cycle_length: int = field(default_factory=lambda: _env_int("MULEGRAPH_MAX_CYCLE_LENGTH", 6))
    max_cycles: int = field(default_factory=lambda: _env_int("MULEGRAPH_MAX_CYCLES", 100))
    max_traversal_nodes: int = field(default_factory=lambda: _env_int("MULEGRAPH_MAX_TRAVERSAL_NODES", 20_000))

    # --- execution budget --------------------------------------------------
    analysis_timeout_ms: float = field(
        default_factory=lambda: _env_float("MULEGRAPH_ANALYSIS_TIMEOUT_MS", 2_000.0)
    )
    deep_timeout_ms: float = field(default_factory=lambda: _env_float("MULEGRAPH_DEEP_TIMEOUT_MS", 10_000.0))

    # --- fan detection thresholds -----------------------------------------
    fan_min_unique_accounts: int = field(
        default_factory=lambda: _env_int("MULEGRAPH_FAN_MIN_UNIQUE", 5)
    )
    fan_min_transactions: int = field(default_factory=lambda: _env_int("MULEGRAPH_FAN_MIN_TX", 5))

    # --- risk propagation --------------------------------------------------
    propagation_depth: int = field(default_factory=lambda: _env_int("MULEGRAPH_PROPAGATION_DEPTH", 2))
    propagation_decay: float = field(default_factory=lambda: _env_float("MULEGRAPH_PROPAGATION_DECAY", 0.5))

    # --- background analysis ----------------------------------------------
    community_refresh_seconds: float = field(
        default_factory=lambda: _env_float("MULEGRAPH_COMMUNITY_REFRESH_S", 30.0)
    )
    centrality_refresh_seconds: float = field(
        default_factory=lambda: _env_float("MULEGRAPH_CENTRALITY_REFRESH_S", 30.0)
    )
    enable_background_analysis: bool = field(
        default_factory=lambda: _env_str("MULEGRAPH_BACKGROUND_ANALYSIS", "1") not in ("0", "false", "False")
    )

    # --- streaming ---------------------------------------------------------
    event_ttl_seconds: float = field(default_factory=lambda: _env_float("MULEGRAPH_EVENT_TTL_S", 0.0))

    # --- redis stream consumer ---------------------------------------------
    redis_url: str = field(default_factory=lambda: _env_str("MULEGRAPH_REDIS_URL", "redis://localhost:6379/0"))
    redis_stream: str = field(default_factory=lambda: _env_str("MULEGRAPH_REDIS_STREAM", "transaction-outcomes"))
    redis_group: str = field(default_factory=lambda: _env_str("MULEGRAPH_REDIS_GROUP", "mulegraph-workers"))
    redis_consumer: str = field(default_factory=lambda: _env_str("MULEGRAPH_REDIS_CONSUMER", "mulegraph-worker"))
    redis_max_attempts: int = field(default_factory=lambda: _env_int("MULEGRAPH_REDIS_MAX_ATTEMPTS", 5))
    redis_backoff_ms: float = field(default_factory=lambda: _env_float("MULEGRAPH_REDIS_BACKOFF_MS", 1000.0))

    # --- api ---------------------------------------------------------------
    default_time_window: str = field(default_factory=lambda: _env_str("MULEGRAPH_DEFAULT_WINDOW", "5m"))
    default_profile: str = field(default_factory=lambda: _env_str("MULEGRAPH_DEFAULT_PROFILE", "STANDARD"))
    max_page_size: int = field(default_factory=lambda: _env_int("MULEGRAPH_MAX_PAGE_SIZE", 100))

    @classmethod
    def from_env(cls, overrides: Mapping[str, object] | None = None) -> "GraphConfig":
        """Build a config from ``MULEGRAPH_*`` environment variables."""
        base = cls()
        if not overrides:
            return base
        data = {f: getattr(base, f) for f in base.__dataclass_fields__}
        data.update({k: v for k, v in overrides.items() if k in data})
        return cls(**data)  # type: ignore[arg-type]


def resolve_window(name: str) -> float:
    """Resolve a window preset name (``5m``, ``1h``...) to seconds."""
    key = name.strip().lower()
    if key not in WINDOW_PRESETS:
        raise ValueError(
            f"Unknown time window {name!r}. Valid options: {', '.join(WINDOW_PRESETS)}"
        )
    return WINDOW_PRESETS[key]
