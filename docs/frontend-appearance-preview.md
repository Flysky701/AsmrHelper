# Frontend appearance preview

This branch starts at `6bbaa867` and is separate from the Gemini design branch. It does not change release versions, native audio processing, or backend settings.

## Scope

- Settings → Appearance & language: Simplified Chinese / English, local background selection and replacement, readable overlay, and restore default.
- UI copy is centralized in `desktop/src/i18n.ts` and `desktop/src/locales/`. Coverage includes navigation, the workbench and node controls, workflow editing, presets and paths, workspace controls, task and batch views, subtitles, voice creation/reference/clone tools, engine resources, external services, quick start and the player.
- Dynamic application messages use catalogued templates. State keeps its original message so changing languages can render it again; captured names, paths and backend details are preserved. Unknown backend diagnostics and third-party descriptions remain verbatim. User material, voice/preset names, synthesis text and business enum values are not translated.
- Existing compact navigation and parameter-panel layout are retained. Other screens keep their existing opaque page surfaces.

## Storage

Preferences use `asmr-helper.appearance.v1`; the image uses `asmr-helper.background.v1` in the current browser/WebView origin's local storage. PNG/JPEG/WebP inputs are decoded locally, flattened and resized to a maximum 1920-pixel edge, then saved as a bounded JPEG copy. No upload, external image URL, native filesystem permission or paid translation service is used. Moving/deleting the original image does not affect the copy. Browser preview settings and packaged WebView settings are separate.

The overlay ranges from 72% to 94%. Invalid saved image data falls back to the default background with a recovery message. Storage failures retain the previous saved choice. Restore default removes the image only. Clearing the browser/WebView profile removes these preferences.

## Isolated preview

Use separate frontend/backend ports and an empty `ASMR_HELPER_DATA_DIR` / `ASMR_HELPER_STATE_DB`. Do not point a preview at the primary workspace's data. The Vite-only `ASMR_PREVIEW_BACKEND` option forwards `/api/v1` to the selected local preview backend; production routing and backend CORS are unchanged.

Example PowerShell environment for the frontend (from `desktop`):

```powershell
$env:VITE_API_BASE = 'http://127.0.0.1:5187/api/v1'
$env:ASMR_PREVIEW_BACKEND = 'http://127.0.0.1:18187'
npm run dev -- --host 127.0.0.1 --port 5187 --strictPort
```

## Validation

All 51 tests in `node --test tests/*.test.mjs`, `tsc -b`, and `vite build` pass. Existing component test loaders have an identity translation adapter; the appearance test loads the real language catalog and checks interpolation preservation. Build warnings about the existing dialog import and a large main chunk remain; no new dependency was added.

Browser checks cover language switching, image selection/replacement, invalid image rejection, deletion of the original file, reload persistence, corrupted preference/image recovery, and 1440/650-pixel layouts. The minimum overlay gives exposed dark labels approximately 4.87:1 contrast over a black test image.

An actual Tauri debug window was built and launched using this frontend at port 5187, with independent workspace/profile and target directories. All eight main pages were inspected in English without document-level horizontal overflow. Native WebView file input, original-file deletion, full process close/relaunch persistence, language roundtrip, 900-pixel parameter layout, restore default and damaged-image fallback passed. Screenshots show actual native WebView content, not a native title-bar capture. The OS file chooser itself was not automated; overall visual direction and that manual click remain for user review.

The Windows GNU debug build exceeded the unused dynamic-library export limit. The preview therefore uses a task-local copy of the unchanged Rust shell, with only the copy's library crate type narrowed to `rlib`; its executable builds successfully. This is a development preview, not an installer. The repository's Cargo files, native code and version files are unchanged.

## v1.1 integration handoff

Do not merge or release this branch until visual review and integration validation. The audio branch at `d5e36fa` (`codex/audio-difference-nmix-20261013`) overlaps these display files:

- `desktop/src/components/GraphRunBindings.tsx`
- `desktop/src/components/task-center/TaskCenterDetails.tsx`
- `desktop/src/components/workflow/GraphNodeParameters.tsx`
- `desktop/src/components/workflow/WorkflowEditor.tsx`
- `desktop/src/components/workflow/WorkflowInspector.tsx`
- `desktop/src/components/workflow/WorkflowNode.tsx`
- `desktop/src/pages/WorkflowPresets.tsx`

Preserve its N-track/difference controls and validation, then apply `t`/`format` to the new application labels and add both language resources. Recheck source values sent to the backend, graph editing, rendering, and audio-specific tests after conflict resolution. This frontend branch does not modify audio/domain/backend logic.

Gemini remains separate at `1e2a305`. Its UI work overlaps `desktop/src/index.css`, `desktop/src/pages/Settings.css`, and `desktop/src/components/QuickStartHelp.tsx`; other styling changes may interact even without textual conflicts. Its branch also contains unrelated version/release changes, so do not blindly merge the entire branch for its design. Selection of that design remains the user's decision.
