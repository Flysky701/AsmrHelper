# MiMo TTS adapter contract

Checked 2026-10-13 against the [official usage guide](https://mimo.mi.com/docs/en-US/quick-start/usage-guide/audio/speech-synthesis-v2.5) and [API reference](https://mimo.mi.com/docs/en-US/api/audio/tts).

- POST `https://api.xiaomimimo.com/v1/chat/completions`; `api-key` authentication.
- Only `mimo-v2.5-tts`, built-in voice selection and non-streaming WAV are implemented. Spoken text is an `assistant` message; optional delivery instructions are a `user` message.
- Decode `choices[0].message.audio.data` from base64. Reject incomplete or filtered completions. Audio validation and output normalization use the shared cloud transport.
- The catalog is the documented nine built-in IDs. `mimo_default` varies by deployment region. This integration exposes Chinese, English and automatic language selection; explicit language, delivery, emotion and style become instructions, not separate numeric API controls. Model adherence remains unverified.
- Numeric speed/sampling, voice design, cloning, reference upload and streaming are not exposed. Saving a recipe creates a local record only.

Verification uses mocked responses and synthetic WAV fixtures. No live API call, credentials or user audio were used. Real API acceptance remains pending authorized account configuration and an explicit test/fee boundary.
