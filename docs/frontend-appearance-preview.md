# Frontend appearance preview

This branch starts at `6bbaa867` and is separate from the Gemini design branch. It does not change release versions, native audio processing, or backend settings.

## Scope

- Settings → Appearance & language: Simplified Chinese / English, local background selection and replacement, readable overlay, and restore default.
- UI copy for navigation, the workbench shell, preset/path settings, quick start and the player is centralized in `desktop/src/i18n.ts` and `desktop/src/locales/en.ts`.
- This is a first visual preview, not complete application localization. Detailed node controls, queue-row details, native workspace dialogs, task center, voice tools and engine screens still need a subsequent translation pass. Backend details and user-provided names are preserved.
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

`node --test tests/*.test.mjs`, `tsc -b`, and `vite build` pass. Browser checks cover language switching, image selection/replacement, invalid image rejection, deletion of the original file, reload persistence, corrupted preference/image recovery, and 1440/650-pixel layouts. The native packaged WebView and its restart/file-picker behavior still require desktop acceptance. Overall visual direction awaits user review before any merge or release.
