# ElevenLabs single-voice adapter contract

Verified against public official documentation on 2026-10-13. No authenticated
API requests, customer audio, or real credentials were used. Offline tests do not
establish account entitlement, voice access, pronunciation, or audio quality.

## Endpoint and format

[Create speech](https://elevenlabs.io/docs/api-reference/text-to-speech/convert)
specifies `POST /v1/text-to-speech/{voice_id}`, `xi-api-key`, a JSON body containing
`text`, `model_id`, optional `language_code`, and optional per-request `voice_settings`.
The response is audio bytes. The adapter requests `output_format=wav_24000` and
uses the existing audio validation/output path. It does not use OpenAI's endpoint.
Voice IDs refer to existing remote voices; saving a local recipe does not create
or clone a voice. Custom proxy prefixes and official regional hosts are supported
through the connection base URL.

## Deliberate supported subset

[Models](https://elevenlabs.io/docs/overview/models) explicitly permits `eleven_v3`
on the Text to Speech API and lists `eleven_flash_v2_5`. Their request character
limits are 5,000 and 40,000. The [official v4 product page](https://elevenlabs.io/v4)
provides a `textToSpeech.convert` example with `modelId: 'eleven_v4'`, and states
its 10,000-character limit. The adapter therefore includes `eleven_v4` on the same
ordinary HTTP endpoint. The previous exclusion based on a Dialogue reference was
incorrect: that reference did not establish exclusive availability.
Ordinary REST support for `eleven_v4_turbo` remains unverified and is not advertised;
its documented WebSocket support does not establish either REST support or absence.
`eleven_multilingual_v2` is also excluded: the convert contract says it does not
support `language_code`, incompatible with promising an explicit output language.

This first adapter accepts auto/zh/en/ja, all supported by all three chosen models.
Auto omits `language_code`; explicit languages are sent verbatim. Unknown language
codes are rejected locally because the service can silently ignore unsupported
codes. There is no reference-language field or reference upload.

[Voice settings](https://elevenlabs.io/docs/api-reference/voices/settings/get-default)
defines stability and its 0–1 range. It is exposed only for Flash v2.5, default 0.5.
The current common API page does not specify v3's model-specific stability
constraints; this adapter rejects that option for v3 rather than guessing.
[Pace guidance](https://elevenlabs.io/docs/overview/capabilities/text-to-speech/best-practices)
specifies speed 0.7–1.2, default 1.0, exposed for v3 and Flash v2.5. Other settings and
emotion/delivery transformations are not exposed; unsupported supplied options
fail validation. Pauses remain local postprocessing. No voice settings are edited
on the server.

For v4, the adapter follows the minimal official example and omits `voice_settings`
entirely. No speed, stability, similarity or style numeric override is exposed for
v4 until its specific parameter contract is verified. This is an adapter limitation,
not a claim that the model lacks those features. Text, including user-written audio
tags, is preserved verbatim; automatic delivery/emotion transformations remain
unsupported. Existing v3/Flash defaults and the original model ordering are retained.

## Validation

`tests/test_cloud_elevenlabs.py` uses HTTP mocks and a generated 0.1-second WAV.
It checks payload/authentication, proxy paths, options/model/language constraints,
text limits, audio metadata, sanitized failures, timeout without retries,
cancellation before dispatch, and frozen-request revalidation. Real API acceptance
requires a user-configured authorized account and explicitly approved test text
and costs. Single-voice non-streaming only; no catalog fetch, clone, design,
dialogue, request stitching, audio effects, or streaming implementation.
