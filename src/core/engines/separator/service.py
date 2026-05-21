"""Core separator engine runtime."""

from __future__ import annotations

from pathlib import Path

from .registry import get_separator_registry


class SeparatorEngineRuntime:
    """Execute source separation against the legacy separator implementation."""

    def __init__(self, registry=None) -> None:
        self._registry = registry or get_separator_registry()

    def separate(
        self,
        *,
        input_path: str,
        output_dir: str,
        model: str = "htdemucs",
        stems: list[str] | None = None,
    ) -> dict[str, str]:
        source = Path(input_path)
        if not source.exists():
            raise ValueError(f"input file does not exist: {input_path}")

        Path(output_dir).mkdir(parents=True, exist_ok=True)
        separator = self._registry.get("demucs", model_name=model)
        return separator.separate(str(source), output_dir, stems=stems)
