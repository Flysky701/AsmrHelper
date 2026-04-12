import re


def parse_voice_text(voice_text: str) -> tuple:
    voice_text = (voice_text or "").strip()
    if not voice_text:
        return "", None
    match = re.search(r"\(([^()]+)\)\s*$", voice_text)
    profile_id = match.group(1).strip() if match else None
    voice_name = voice_text.split(" (", 1)[0].strip()
    return voice_name, profile_id


def get_voice_info(engine: str, voice_tabs=None,
                   preset_combo=None, custom_combo=None,
                   clone_line=None, edge_combo=None) -> tuple:
    if engine == "edge":
        if edge_combo is not None:
            voice_text = edge_combo.currentText()
            voice_name, _ = parse_voice_text(voice_text)
            return voice_name, None
        return "zh-CN-XiaoxiaoNeural", None

    if voice_tabs is None:
        return "Vivian", "A1"

    tab_index = voice_tabs.currentIndex()
    if tab_index == 0:
        voice_text = preset_combo.currentText()
        return parse_voice_text(voice_text)
    else:
        voice_text = custom_combo.currentText()
        return parse_voice_text(voice_text)
