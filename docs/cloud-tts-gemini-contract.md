# Gemini TTS adapter contract

Checked against official documentation on 2026-10-13:

- [Speech generation](https://ai.google.dev/gemini-api/docs/speech-generation)
- [Interactions REST reference](https://ai.google.dev/api/interactions-api)
- [Interactions state retention](https://ai.google.dev/gemini-api/docs/interactions-overview)

The adapter supports `gemini-3.8-flash-tts` and `gemini-3.8-flash-lite-tts` with one voice per request. It sends `POST /v1beta/interactions`, `x-goog-api-key`, literal transcript content, and optional `speech_metadata.style` annotations. It requests WAV at 24 kHz, sets `stream:false`, and opts out of stored interaction history with `store:false`. The response decoder takes the last audio block in model-output steps. Base64 must be valid; PCM fallback requires declared mono 24 kHz L16 and follows the documented little-endian encoding.

The builtin catalog contains the documented 30 voices. Hosted mode accepts an existing persistent `voice_` identifier. This integration never creates, clones, designs, lists or deletes remote voices and rejects temporary `voicekey_` tokens.

Only style text is exposed as a provider option. Normal/soft/whisper delivery and the existing emotion controls are mapped to style metadata, preserving the transcript. The integration accepts auto/Chinese/English/Japanese language annotations; Gemini detects spoken language from the input text. This field does not translate text or force its language. No unsupported sampling parameters are sent.

The existing recipe `variant.style` remains a voice-version label. Performance instructions come from each compiled segment's `delivery`/`emotion` and the provider style option; the label alone never changes the transcript or requests whispering.

Offline tests cover both model requests, existing voices, proxy prefixes, WAV/PCM decoding, malformed and incomplete responses, parameter rejection, snapshot hashing, cancellation, and timeout without retry. These tests do not establish account access, billing, voice availability, synthesis quality, or live service compatibility. Live acceptance remains pending a user-configured authorized account and an explicitly approved text/cost boundary.
