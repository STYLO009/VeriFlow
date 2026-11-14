"""Prompt loading: prompts live in dedicated ``app/ai/prompts/*.txt`` files."""

from __future__ import annotations

import re
from pathlib import Path

DEFAULT_PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
_PLACEHOLDER = re.compile(r"\{\{([A-Z0-9_]+)\}\}")


class PromptLibrary:
    """Loads and caches prompt templates; ``{{NAME}}`` placeholders only."""

    def __init__(self, directory: Path | str | None = None) -> None:
        self.directory = Path(directory) if directory else DEFAULT_PROMPT_DIR
        self._cache: dict[str, str] = {}

    def names(self) -> list[str]:
        return sorted(p.stem for p in self.directory.glob("*.txt"))

    def get(self, name: str) -> str:
        if name in self._cache:
            return self._cache[name]
        path = self.directory / f"{name}.txt"
        if not path.exists():
            raise FileNotFoundError(f"prompt template not found: {path}")
        text = path.read_text(encoding="utf-8")
        self._cache[name] = text
        return text

    def render(self, name: str, **variables: object) -> str:
        template = self.get(name)
        def repl(match: re.Match[str]) -> str:
            key = match.group(1)
            return str(variables.get(key, match.group(0)))
        return _PLACEHOLDER.sub(repl, template)

    def stage(self, name: str, **variables: object) -> str:
        """System prompt for a workflow stage: core rules + stage instructions."""
        return self.get("system").rstrip() + "\n\n" + self.render(name, **variables)


__all__ = ["PromptLibrary"]
