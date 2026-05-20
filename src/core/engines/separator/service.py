"""Core separator engine runtime."""

from __future__ import annotations

from pathlib import Path


class SeparatorEngineRuntime:
    """Execute source separation against the legacy separator implementation."""

    def separate(
        self,
        *,
        input_path: str,
        output_dir: str,
        model: str = "htdemucs",
        stems: list[str] | None = None,
    ) -> dict[str, str]:
        from src.core.vocal_separator import VocalSeparator

        source = Path(input_path)
        if not source.exists():
            raise ValueError(f"input file does not exist: {input_path}")

        Path(output_dir).mkdir(parents=True, exist_ok=True)
        separator = VocalSeparator(model_name=model)
        return separator.separate(str(source), output_dir, stems=stems)
