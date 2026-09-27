"""Experimental instructions for Qwen3 CustomVoice; no playback processing."""

STYLE_INSTRUCTIONS = {
    "normal": "",
    "soft": "用温柔、轻柔的声音说话，语气放松自然，吐字清晰。",
    "whisper": "用贴近耳边的气声耳语说话，轻声低语，保持清晰的吐字和自然的停顿。",
}


def style_instruction(style: str) -> str:
    if style not in STYLE_INSTRUCTIONS:
        raise ValueError(f"Unsupported Qwen3 speaking_style: {style!r}")
    return STYLE_INSTRUCTIONS[style]


def compose_instruction(*parts: str | None) -> str:
    """Retain voice identity, delivery style and alignment instructions together."""
    return "\n".join(part.strip() for part in parts if part and part.strip())
