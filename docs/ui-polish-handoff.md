# Desktop UI polish handoff — 2026-10-16

Branch: `codex/cloud-tts-extension-20261013`, continuing from `bdd27e2`.

This sync preserves the accepted AGY UI changes: denser page layouts, revised task-center presentation, workflow/reference panels, contextual help, and shorter interface copy. The removed request-only speech precheck remains removed by user decision. The task deletion preview adds “同时删除文件，无法恢复” and its English translation, using the existing small-note style only in file-deletion mode when the preview lists at least one file for deletion.

## Continue and launch

Use the existing test branch/worktree; do not overwrite or synchronize changes into a separate old checkout. Run `RUNGUI.bat` from this checkout. It delegates to `scripts/desktop_local.py`, which checks source/build identity and selects a current local native build. Inspect without launching with `.venv\Scripts\python.exe -B scripts\desktop_local.py --check`. Keep the existing dependency/model separation; local binaries and build receipts are generated artifacts and are not in Git.

At handoff, `asmr-helper-local-next.exe` matched the frontend/runtime source fingerprint `e2489ec7e5bf30abdc2db59218930ac8b4f7874ed8c23426a541cd22914ca7cc`; the older `asmr-helper-local.exe` did not. Start the checked launcher rather than a stale executable. No installer was rebuilt or published for this sync.

## Verification

- Rechecked before sync: all 85 existing frontend Node tests, TypeScript (`--noEmit --incremental false`), and syntax parsing of all 17 modified CSS files passed.
- Eight temporary offline rendering checks passed for the deletion note: Chinese/English, history-only, zero deletable files, loading, absent/stale-mode previews, and the result screen. These check scripts and fixtures remain outside the repository.
- The local native build passed before sync. An isolated native instance with synthetic task records confirmed Chinese/English note text, history-only omission, and a visible footer at an emulated 900×600 viewport. Only previews were opened; deletion was never executed. The isolated instance was closed.
- Earlier backend regression evidence for the existing subtitle implementation: 1,179 passed, 1 skipped, with an unknown `cache_dir` pytest configuration warning. This UI-only sync did not rerun that backend suite or real ASR/TTS/paid services.

## Follow-up items retained, not fixed in this sync

1. Workbench scan-settings popup: the `.queue-scan-settings` containing block places its expanded controls above the visible viewport. Reproduce by opening Scan settings at the workbench footer; correct positioning and verify wide/narrow viewports in a separate change.
2. Twelve new interface strings lack English translations: five in `TaskDeletionDialog.tsx`, three in `GraphNodeParameters.tsx`, two in `SubtitleWorkshop.tsx`, one in `ReferenceLibrary.tsx`, and one in `VoiceLab.tsx`. The new irreversible-file-deletion note itself is translated. Complete the remaining dictionary entries separately.
3. `git diff --check` reports eight pre-existing trailing blank lines added by the accepted UI patch in CSS files. They were retained to preserve that patch; CSS parsing and compilation pass.

Native file-picker interaction, a complete keyboard-only walkthrough, actual OS-window resizing, clean-machine installation, model downloads, paid/cloud synthesis, and real recording alignment were not newly verified. Viewport emulation is not an OS-resize acceptance test. No merge to the main branch, release, forced update, or destructive cleanup is included.
