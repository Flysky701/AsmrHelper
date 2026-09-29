"""Offline Qwen preset catalog; execution belongs to Speech workers."""

VOICES = ['Vivian', 'Serena', 'Uncle_Fu', 'Dylan', 'Eric', 'Ryan', 'Aiden', 'Ono_Anna', 'Sohee']
VOICE_DESC = {'Vivian': 'Vivian（女声，甜美）', 'Serena': 'Serena（女声，清亮）', 'Uncle_Fu': 'Uncle_Fu（男声，成熟）', 'Dylan': 'Dylan（男声，年轻）', 'Eric': 'Eric（男声，沉稳）', 'Ryan': 'Ryan（男声，温和）', 'Aiden': 'Aiden（男声，自然）', 'Ono_Anna': 'Ono_Anna（日语女声）', 'Sohee': 'Sohee（女声，柔和）'}

def list_qwen_voices():
    languages = {"Ryan": "en", "Aiden": "en", "Ono_Anna": "ja", "Sohee": "ko"}
    return [{"id": voice, "name": VOICE_DESC[voice], "language": languages.get(voice, "zh")} for voice in VOICES]
