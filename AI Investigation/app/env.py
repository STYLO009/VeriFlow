"""Minimal ``.env`` loader (stdlib only, no extra dependency).

Reads ``KEY=VALUE`` lines from a project ``.env`` file into ``os.environ`` so
local secrets never live in code. Rules:

* variables already present in the process environment are never overridden
  (shell / deployment values win over the file);
* blank lines, ``#`` comments and an optional ``export `` prefix are ignored;
* single- or double-quoted values keep inner whitespace; ``\\n``, ``\\t``,
  ``\\"`` and ``\\\\`` are unescaped inside double quotes;
* unquoted values drop a trailing ``# comment``.

Search order (first existing file wins):

1. ``MULEGRAPH_ENV_FILE`` (explicit path; if set but missing it raises, so a
   misconfigured deployment is never silently ignored);
2. ``<project root>/.env`` (the directory that contains ``app/``);
3. ``./.env`` (current working directory).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_loaded_from: Path | None = None


def _parse_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        inner = value[1:-1]
        if value[0] == '"':
            inner = (
                inner.replace("\\n", "\n")
                .replace("\\t", "\t")
                .replace('\\"', '"')
                .replace("\\\\", "\\")
            )
        return inner
    # unquoted: drop a trailing comment introduced by whitespace + "#"
    for i, ch in enumerate(value):
        if ch == "#" and i > 0 and value[i - 1] in (" ", "\t"):
            return value[:i].rstrip()
    return value


def parse_env_file(path: str | Path) -> dict[str, str]:
    """Parse a ``.env`` file into a mapping (does not touch ``os.environ``)."""
    text = Path(path).read_text(encoding="utf-8-sig")
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not _KEY_RE.match(key):
            continue
        values[key] = _parse_value(value.strip())
    return values


def _candidate_paths() -> list[Path]:
    # project root == the directory containing ``app/`` (this file's parent)
    root = Path(__file__).resolve().parent.parent
    return [root / ".env", Path.cwd() / ".env"]


def load_env_file(force: bool = False) -> Path | None:
    """Load the first ``.env`` found into ``os.environ``; idempotent.

    Returns the path that was loaded, or ``None`` when no file exists.
    Existing environment variables are never overwritten.
    """
    global _loaded_from
    if _loaded_from is not None and not force:
        return _loaded_from

    explicit = os.environ.get("MULEGRAPH_ENV_FILE")
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise FileNotFoundError(
                f"MULEGRAPH_ENV_FILE points to a missing file: {path}"
            )
        candidates = [path]
    else:
        candidates = _candidate_paths()

    for path in candidates:
        if not path.is_file():
            continue
        for key, value in parse_env_file(path).items():
            if key not in os.environ:
                os.environ[key] = value
        _loaded_from = path
        return path
    return None


__all__ = ["load_env_file", "parse_env_file"]
