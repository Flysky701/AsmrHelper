# Windows x64 test installer

Version: **0.2.1-beta.5** (Python metadata: `0.2.1b5`). Product: **ASMR Helper Test**. This is a separate per-user NSIS test product, not a signed public release.

The installed desktop executable starts its own loopback backend on an ephemeral port and passes a fresh session token to the WebView. It refuses packaged startup if resources are missing. A Windows Job Object owns the backend and model-worker process tree; application exit requests graceful shutdown and then terminates remaining children.

Immutable installed resources include a complete clean CPython 3.12.13 distribution, locked base dependencies, application source, public default catalogs, uv, and FFmpeg 8.1.2 shared libraries. No developer virtual environment, user credentials/configuration, voice library, history/database, audio output, or model weights is bundled. On first run, the clean interpreter is copied to a versioned writable user runtime so optional dependencies can be installed on demand. Generated Python console launchers with absolute staging paths are omitted; entrypoints use `python -m`.

Persistent data defaults to `%LOCALAPPDATA%\ASMRHelperTestData`, deliberately outside the installation and Tauri WebView cache directories. It contains config, state database, output, models, runtime environments and logs. Upgrades and the standard uninstaller leave it in place, including when the uninstaller removes the separate WebView application cache. `ASMR_HELPER_DATA_DIR` overrides this root for isolated testing.

## Reproduce

Use a clean complete uv-managed CPython 3.12.13 source distribution, not `.venv` or the embeddable distribution. Obtain it with `uv python install 3.12.13 --install-dir <clean-source-parent> --no-bin --no-registry`. Verify the FFmpeg shared archive against the upstream SHA256. The tested FFmpeg archive hash is `cba748035c21ce1431d0823c7a3a711f38616f89f87a265dceddf9b7f6749d2d`.

From the repository root:

```powershell
python -X utf8 -B scripts/build_windows_backend.py --python-source <clean-python-directory> --ffmpeg-source <ffmpeg-directory> --uv <uv.exe> --output desktop/src-tauri/bundle-resources/backend
python -X utf8 -B scripts/audit_windows_bundle.py desktop/src-tauri/bundle-resources/backend
cd desktop
npm ci
npm run tauri -- build --bundles nsis
```

The build script rejects nonempty output. Preserve or remove only a known generated staging directory before rebuilding. Dependencies come from the committed `uv.lock` with hash verification and no optional model/audio extras. The application-managed copy alone has the uv external-management marker removed; the source interpreter is unchanged.

The staging script collects Python/native, uv, Rust and production npm dependency notices. FFmpeg's supplied build is **GPL v3**, not MIT; its license, build options and source references are retained. The application's metadata declares MIT. Dependency notices and inventory are supporting evidence, not legal certification. Model weights have independent terms and are downloaded only when requested.

## Acceptance scope

Test actual installation in a separate directory, fresh data/cache directories and a PATH containing only Windows system directories. Verify desktop-managed backend startup, authenticated UI requests, rejected anonymous API access, local subtitle conversion, restart persistence, reinstall persistence, unchanged installed-resource hashes and process-tree cleanup. Verify uninstall preserves user data. A smoke test on this development machine is **not** clean Windows/VM acceptance; WebView2 and system components may already be present.

The unsigned test installer is intended for private friend testing. No signing certificate, public release, remote API call, model download, virtualization/security change or system-wide development-tool installation is part of this build.
