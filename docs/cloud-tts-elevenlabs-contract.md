# ElevenLabs single-voice adapter contract

Verified against public official documentation on 2026-10-13. No authenticated
API requests, customer audio, or real credentials were used. Offline tests do not
establish account entitlement, voice access, pronunciation, or audio quality.

## Endpoint and format

[Create speech](https://elevenlabs.io/docs/api-reference/text-to-speech/convert)
specifies `POST /v1/text-to-speech/{voice_id}`, `xi-api-key`, a JSON body containing
`text`, `model_id`, optional `language_code`, and per-request `voice_settings`.
The response is audio bytes. The adapter requests `output_format=wav_24000` and
uses the existing audio validation/output path. It does not use OpenAI's endpoint.
Voice IDs refer to existing remote voices; saving a local recipe does not create
or clone a voice. Custom proxy prefixes and official regional hosts are supported
through the connection base URL.

## Deliberate supported subset

[Models](https://elevenlabs.io/docs/overview/models) explicitly permits `eleven_v3`
on the Text to Speech API and lists `eleven_flash_v2_5`. Their request character
limits are 5,000 and 40,000. `eleven_v4` is documented on Text to Dialogue and
`eleven_v4_turbo` on the dialogue WebSocket. They are not advertised here.
`eleven_multilingual_v2` is also excluded: the convert contract says it does not
support `language_code`, incompatible with promising an explicit output language.

This first adapter accepts auto/zh/en/ja, all supported by both chosen models.
Auto omits `language_code`; explicit languages are sent verbatim. Unknown language
codes are rejected locally because the service can silently ignore unsupported
codes. There is no reference-language field or reference upload.

[Voice settings](https://elevenlabs.io/docs/api-reference/voices/settings/get-default)
defines stability and its 0–1 range. It is exposed only for Flash v2.5, default 0.5.
The current common API page does not specify v3's model-specific stability
constraints; this adapter rejects that option for v3 rather than guessing.
[Pace guidance](https://elevenlabs.io/docs/overview/capabilities/text-to-speech/best-practices)
specifies speed 0.7–1.2, default 1.0, exposed for both models. Other settings and
emotion/delivery transformations are not exposed; unsupported supplied options
fail validation. Pauses remain local postprocessing. No voice settings are edited
on the server.

## Validation

`tests/test_cloud_elevenlabs.py` uses HTTP mocks and a generated 0.1-second WAV.
It checks payload/authentication, proxy paths, options/model/language constraints,
text limits, audio metadata, sanitized failures, timeout without retries,
cancellation before dispatch, and frozen-request revalidation. Real API acceptance
requires a user-configured authorized account and explicitly approved test text
and costs. Single-voice non-streaming only; no catalog fetch, clone, design,
dialogue, request stitching, audio effects, or streaming implementation.
