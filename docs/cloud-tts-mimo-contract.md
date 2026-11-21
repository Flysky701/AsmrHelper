# MiMo TTS adapter contract

Checked 2026-10-13 against the [official usage guide](https://mimo.mi.com/docs/en-US/quick-start/usage-guide/audio/speech-synthesis-v2.5) and [API reference](https://mimo.mi.com/docs/en-US/api/audio/tts).

- POST `https://api.xiaomimimo.com/v1/chat/completions`; `api-key` authentication.
- `mimo-v2.5-tts` sends the built-in ID in `audio.voice`. VoiceDesign uses `mimo-v2.5-tts-voicedesign` with a user instruction and omits `audio.voice`. VoiceClone uses `mimo-v2.5-tts-voiceclone` with a WAV or MP3 data URI in `audio.voice`. All three request non-streaming WAV. Spoken text is an `assistant` message; optional delivery instructions are a `user` message.
- Decode `choices[0].message.audio.data` from base64. Reject incomplete or filtered completions. Audio validation and output normalization use the shared cloud transport.
- The catalog is the documented nine built-in IDs. `mimo_default` varies by deployment region. This integration exposes Chinese, English and automatic language selection; explicit language, delivery, emotion and style become instructions, not separate numeric API controls. Model adherence remains unverified.
- Saving a recipe stores its voice selection locally. Reference audio is sent to MiMo during synthesis.

Verification uses mocked responses and synthetic WAV fixtures. No live API call, credentials or user audio were used. Real API acceptance remains pending authorized account configuration and an explicit test/fee boundary.
