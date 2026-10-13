# Cloud TTS extension — isolated acceptance candidate

Base: `e365724097f4f2f2b4956f86b55bf44d34379f4e`.
Branch: `codex/cloud-tts-extension-20261013`.
This extension does not change version files, merge master, create a tag or release,
or replace the existing v1.1 candidate preview.

## Supported scope

| Provider | Models | Voice source | Exposed controls |
| --- | --- | --- | --- |
| Gemini | `gemini-3.8-flash-tts`, `gemini-3.8-flash-lite-tts` | 30 built-in voices or existing persistent `voice_` ID | Style metadata, delivery and emotion instructions |
| ElevenLabs | `eleven_v3`, `eleven_flash_v2_5` | Existing Voice ID, entered manually | Speed; stability only on Flash v2.5 |
| MiMo | `mimo-v2.5-tts` | Nine documented built-in voice IDs | Style, delivery, emotion and language instructions |

All use single-voice, non-streaming requests and normalize audio into the existing
WAV take/artifact pipeline. Local recipe save/load, auditions and existing TTS
graph nodes share the same provider compiler and immutable connection snapshot.
No remote voice creation, reference upload, voice design, multi-speaker dialogue
or streaming was added. No new dependency or model download is required.

Gemini detects language from the spoken text. MiMo currently exposes Chinese and
English only; its explicit language is an instruction, not a guarantee of adherence.
The app's initial Gemini/ElevenLabs scope is auto/Chinese/English/Japanese.
Output language is separate from reference recording language.

ElevenLabs v4 and v4 Turbo use different documented dialogue interfaces and are
not routed through this ordinary TTS adapter. Model-specific unsupported options
are rejected, including stability on the current v3 adapter. Cloud responses and
errors do not prove model quality or reproducibility.

## Configuration and acceptance

1. In external speech services, select the provider. Its official base URL is
   filled for a new connection; custom proxy prefixes remain editable.
2. The user supplies their authorized API key. Configuration checking performs
   no billable generation and does not claim that authentication was verified.
3. In the existing voice library, select a model and built-in voice or existing
   remote Voice ID, choose supported parameters, and save the local recipe.
4. An explicitly authorized audition uses the existing audition action. Select
   the saved recipe on the workbench TTS node to use it in a pipeline.

Keys are stored through the existing local credential-reference mechanism and
never enter recipe/graph snapshots. Execution checks that compiled requests,
recipe identity, model and connection reference agree before resolving credentials.
Timeouts and network failures do not retry paid POSTs automatically. Cancellation
before sending avoids a request; cancellation after sending discards the local
take but cannot undo remote generation or charges. Existing stage recovery can
reuse audited completed output; graph checkpoint resume is not introduced.

## Verification on FLY-Laptop

- 355 backend tests passed: three adapters, shared transport/integration, existing
  speech providers/store/service/HTTP/rules/defaults/overrides/recovery, pipeline
  sources, TTS unification and graph audio regression.
- After the final runner identity check, 151 affected tests passed, including nine
  added cases rejecting mixed request/snapshot connections or models before any
  credential resolution or HTTP request.
- All 75 frontend tests passed; `tsc --noEmit` passed; `git diff --check` passed.
- HTTP uses `httpx.MockTransport`, invented fixture credentials and tiny generated
  WAV/PCM samples. Tests cover JSON/base64/PCM decoding, model-specific option
  rejection, saved recipe reload, fixed graph snapshots, artifact registration,
  timeout/error sanitization, cancellation cleanup and old stage reuse.

Windows test execution needed normal local permissions for `Path.resolve` on
generated fixtures and a short temporary base directory for libsndfile paths.
No permissions/ACLs were changed. No full release/native build was run.

**Real API acceptance is pending.** No real credentials were inspected, no paid
requests were made, and no user audio was uploaded. Account/model/voice entitlement,
live response compatibility and listening quality still require a user-configured
account plus agreed test text and spending boundary. No live UI screenshot or
real synthesized sample is claimed by this delivery.

## Official contract notes

- [Gemini](cloud-tts-gemini-contract.md)
- [ElevenLabs](cloud-tts-elevenlabs-contract.md)
- [MiMo](cloud-tts-mimo-contract.md)

The linked notes include official source URLs and the implemented subset.
