---
name: asmr-producer
description: Orchestrates two-phase ASMR localization and binaural dubbing via ASMR Helper MCP tools (`asmr_inspect_work` -> `asmr_prepare_draft` -> concise review gate & speed rewrite -> user confirmation -> `asmr_patch_draft` + `asmr_commit_draft`).
---

# ASMR Producer Skill (`asmr-producer`)

Use this skill whenever the user asks to inspect, translate, subtitle, or dub an ASMR work (by folder path, track path, RJ code, or title) through the **ASMR Helper MCP Server** (`python -m packages.mcp_server.server`).

Core architectural rule: **Never run full-track TTS synthesis blindly in one shot.** Always pause at the Phase 1 `awaiting_review` gate, show a concise audit summary (`<= 10` lines) plus proposed concise rewrites for any `over_speed_cues`, wait for user confirmation (`"跑"` / `"OK"` / `"确认"`), and only then patch and commit Phase 2.

---

## Step 0: Load User Preferences & Discover Voices

1. Read `config/agent_preferences.yaml` if present; otherwise fall back to `config/agent_preferences.example.yaml` for defaults:
   - `library_roots`: folders to search when the user gives a fuzzy title or RJ code instead of a full path.
   - `translation_style`: target tone, `chars_per_second` (default `4.2`), and `max_atempo` (default `1.35`).
   - `voice_preferences`: preferred `recipe_id` / `provider_id` / `mode` (`preset` vs `clone`), `extract_voice_reference`, and `sample_cue_count`.
   - `compute`: optional `remote_worker_url` (e.g., Colab `trycloudflare.com` tunnel) and token env var.
   - `output_policy` & `mix_defaults`: export formats (`srt`, `lrc`), `bilingual_subtitles`, and mixer gain ratios.
2. When selecting or verifying a voice recipe, call `asmr_list_voices_and_presets` to list real saved VoiceLab `recipes`, `connections`, and engine `providers`—never guess voice IDs.

---

## Step 1: Material Discovery (`asmr_inspect_work`)

1. Resolve the target work directory or track file (searching `library_roots` if the user gave a keyword/RJ number).
2. Call **`asmr_inspect_work`** with `{"path_or_dir": "<resolved_path>"}`.
3. Inspect the returned `tracks`, `stem_pairs`, and `readiness`:
   - Prefer lossless tracks (`.wav` / `.flac`) and note auto-paired stems (`no_se`, `vocals`, `se_only`) and companion subtitles/scripts (`.srt`, `.vtt`, `.lrc`, `.txt`, `.pdf`).
   - If multiple main tracks exist and the user did not specify which track(s) to process, briefly list the discovered tracks and confirm or start with Track 1.

---

## Step 2: Phase 1 Extraction & Deterministic Gate (`asmr_prepare_draft`)

1. Call **`asmr_prepare_draft`** with:
   - `path_or_dir` (and `track_path` / `subtitle_path` if selecting a specific file),
   - `source_lang` / `target_lang` / `chars_per_second` / `max_atempo` from preferences,
   - `voice_plan` (mapped from `voice_preferences`),
   - `extract_voice_reference` (`true` if cloning) and `sample_cue_count` (`1` or `2` if sample preview is desired),
   - `remote_worker_url` if configured.
2. Confirm the returned session `state` is `"awaiting_review"` and note `draft_id` and `revision`.
3. Call **`asmr_get_draft_audit`** (`include_segments: true` if needed for context) to inspect `QualityAuditReport`:
   - `untranslated_indices`
   - `japanese_residue_indices`
   - `empty_or_symbol_indices`
   - `over_speed_cues` (cues whose estimated Chinese duration exceeds `(cue_duration + available_slack) * 1.35`, along with `max_recommended_chars`).

---

## Step 3: Present `<= 10`-Line Gate Summary & Propose Concise Rewrites

Before calling `asmr_commit_draft`, present a **compact gate review (`<= 10` lines for the status overview)** containing:
1. Work/Track title, duration, stem pairing mode (`no_se` / `se_only` / `existing_subtitle` / `asr`), `draft_id`, and `revision`.
2. Audit counts: total cues, untranslated count, Japanese residue count, over-speed count (`> 1.35x`), and `gate_passed`.
3. Voice plan summary (selected recipe/voice, reference SNR dB, or sample take path if generated).
4. **Proposed Rewrites**:
   - For every cue in `over_speed_cues`, propose a natural, whispered Chinese rewrite whose spoken character count is **`<= max_recommended_chars`** while preserving intimacy and meaning.
   - For any `untranslated_indices` or `japanese_residue_indices`, include clean Chinese translations with zero leftover Hiragana/Katakana.
5. End with a clear one-line prompt waiting for user approval: e.g., *"回复 `跑` / `OK` 应用上述精简改词并导出成品（也可直接在桌面端打开该草稿试听微调）。"*

**STOP and wait for the user's explicit confirmation** (`"跑"`, `"OK"`, `"确认"`, or specific adjustment requests).

---

## Step 4: Phase 2 Patch & Commit (`asmr_patch_draft` -> `asmr_commit_draft`)

Once the user replies `"跑"` / `"OK"` (or provides custom edits):

1. If there are any proposed rewrites, residue fixes, timing tweaks, or voice changes:
   - Call **`asmr_patch_draft`** passing `draft_id`, `expected_revision` (optimistic concurrency guard), `edits` (`[{"index": i, "translation": "<concise_rewrite>"}]`), and optional `voice_plan_patch`.
   - Verify the returned `audit_report.gate_passed` (confirming `over_speed_cues` and `japanese_residue_indices` are cleared) and update `expected_revision` to the new `revision`.
2. Call **`asmr_commit_draft`** with:
   - `draft_id`,
   - `output_dir` (e.g., `<work_dir>/<output_policy.subfolder>` or user-specified folder),
   - `export_formats` (default `["srt", "lrc"]` — produces clean `[mm:ss.xx]` `.lrc` and `.srt`),
   - `enable_dubbing` (`true` unless subtitle-only was requested),
   - `bilingual` (`true` by default),
   - `mix_options` from `mix_defaults`,
   - `expected_revision`.
3. Report the completed artifact paths (`artifacts.subtitles.srt`, `artifacts.subtitles.lrc`, `artifacts.mixed_audio_path`, and `reused_take_count` / `synthesized_take_count`). If the user later tweaks 1–2 lines, `asmr_patch_draft` + `asmr_commit_draft` will automatically reuse all unchanged synthesized takes!
