"""Artifact result mapper — normalizes pipeline run results."""

from __future__ import annotations

from typing import Any


class ArtifactResultMapper:
    """Maps raw pipeline results to a normalized artifact structure."""

    @staticmethod
    def normalize_results(raw: dict[str, Any]) -> dict[str, Any]:
        """Ensure pipeline results have a consistent shape.

        Extracts known artifact paths and step errors into a flat structure
        that callers (PipelineService) can consume without inspecting
        legacy internals.
        """
        steps = raw.get("steps", {})
        step_errors: dict[str, str] = {}
        for step_name, step_result in steps.items():
            if isinstance(step_result, dict) and step_result.get("error"):
                step_errors[step_name] = str(step_result["error"])

        mix_path = raw.get("mix_path")
        exported_subtitle = raw.get("exported_subtitle")

        return {
            "input": raw.get("input", ""),
            "output_dir": raw.get("output_dir", ""),
            "mix_path": mix_path,
            "exported_subtitle": exported_subtitle,
            "primary_output": mix_path or exported_subtitle,
            "vocal_path": raw.get("vocal_path"),
            "tts_audio_path": raw.get("tts_audio_path") or raw.get("tts_path"),
            "transcript_path": raw.get("transcript_path") or raw.get("asr_text_path"),
            "steps": steps,
            "step_errors": step_errors,
            "subtitle_lang": raw.get("subtitle_lang"),
            "subtitle_type": raw.get("subtitle_type"),
            "total_steps": raw.get("total_steps", 0),
            "total_duration": raw.get("total_duration", 0.0),
            "error": raw.get("error"),
        }
