from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


_SPEC = importlib.util.spec_from_file_location(
    "desktop_local", Path(__file__).resolve().parents[1] / "scripts/desktop_local.py"
)
launcher = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(launcher)


class DesktopLocalLauncherTests(unittest.TestCase):
    def test_incomplete_or_changed_staged_build_is_not_selected(self):
        with tempfile.TemporaryDirectory() as directory:
            staged = Path(directory) / "next.exe"
            staged.write_bytes(b"completed build")
            with patch.object(launcher, "STAGED_EXE", staged):
                self.assertFalse(launcher.verified_staged_build())
                staged.with_suffix(".build.json").write_text(
                    json.dumps({"sha256": hashlib.sha256(staged.read_bytes()).hexdigest()}),
                    encoding="utf-8",
                )
                self.assertTrue(launcher.verified_staged_build())
                staged.write_bytes(b"interrupted replacement")
                self.assertFalse(launcher.verified_staged_build())

    def test_staged_build_does_not_launch_or_replace_running_window(self):
        with patch("sys.argv", ["desktop_local.py", "--build-staged"]), \
                patch.object(launcher, "build") as build, \
                patch.object(launcher.subprocess, "Popen") as popen:
            launcher.main()
            build.assert_called_once_with(staged=True)
            popen.assert_not_called()

    def test_locked_output_fails_before_build_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            staged = Path(directory) / "next.exe"
            staged.write_bytes(b"running build")
            with patch.object(launcher, "STAGED_EXE", staged), \
                    patch.object(launcher, "output_locked", return_value=True), \
                    patch.object(launcher.subprocess, "run") as run:
                with self.assertRaisesRegex(RuntimeError, "no process was stopped"):
                    launcher.build(staged=True)
                run.assert_not_called()


class CurrentBuildTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.exe = self.root / "local.exe"
        self.staged = self.root / "next.exe"
        for name, value in (("ROOT", self.root), ("EXE", self.exe), ("STAGED_EXE", self.staged)):
            patcher = patch.object(launcher, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.args = SimpleNamespace(build=False, build_only=False, build_staged=False)

    def receipt(self, path, fingerprint=None):
        path.write_bytes(path.name.encode())
        data = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "source_fingerprint": fingerprint or launcher.source_fingerprint(),
                "fingerprint_version": launcher.FINGERPRINT_VERSION,
                "built_at_utc": "2026-10-08T00:00:00+00:00"}
        path.with_suffix(".build.json").write_text(json.dumps(data), encoding="utf-8")

    def test_current_staged_wins_over_newer_stale_main_without_build(self):
        self.receipt(self.staged)
        self.receipt(self.exe, "old")
        with patch.object(launcher, "build") as build:
            self.assertEqual(launcher.ensure_current_build(), self.staged)
            build.assert_not_called()

    def test_old_sources_trigger_build_and_verify_receipt(self):
        self.receipt(self.exe, "old")
        def build():
            self.receipt(self.staged)
            return self.staged
        with patch.object(launcher, "build", side_effect=build) as build_mock:
            self.assertEqual(launcher.ensure_current_build(), self.staged)
            build_mock.assert_called_once_with()

    def test_failed_build_never_launches_old_executable(self):
        self.receipt(self.exe, "old")
        with patch.object(launcher, "build", side_effect=launcher.subprocess.CalledProcessError(1, "cargo")), \
                patch.object(launcher.subprocess, "Popen") as popen:
            with self.assertRaises(launcher.subprocess.CalledProcessError):
                launcher.launch(self.args)
            popen.assert_not_called()

    def test_build_without_current_receipt_never_launches(self):
        self.receipt(self.exe, "old")
        with patch.object(launcher, "build", return_value=self.exe), \
                patch.object(launcher.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(RuntimeError, "does not match"):
                launcher.launch(self.args)
            popen.assert_not_called()

    def test_locked_main_uses_alternate_and_both_locked_stop(self):
        with patch.object(launcher, "output_locked", side_effect=lambda path: path == self.exe):
            self.assertEqual(launcher.build_target(), self.staged)
        with patch.object(launcher, "output_locked", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "no process was stopped"):
                launcher.build_target()

    def test_existing_window_is_preserved_without_duplicate(self):
        self.receipt(self.exe)
        with patch.object(launcher, "output_locked", side_effect=lambda path: path == self.staged), \
                patch.object(launcher.subprocess, "Popen") as popen:
            launcher.launch(self.args)
            popen.assert_not_called()

    def test_launch_uses_current_path_and_build_identity(self):
        self.receipt(self.staged)
        with patch.object(launcher, "output_locked", side_effect=[False, False, False, True]), \
                patch.object(launcher.time, "sleep"), \
                patch.object(launcher.subprocess, "Popen") as popen:
            popen.return_value.poll.return_value = None
            launcher.launch(self.args)
            self.assertEqual(popen.call_args.args[0], [str(self.staged)])
            self.assertEqual(popen.call_args.kwargs["env"]["ASMR_HELPER_BUILD_SOURCE"],
                             launcher.source_fingerprint())

    def test_source_changes_immediately_before_launch_stop(self):
        self.receipt(self.exe)
        with patch.object(launcher, "source_fingerprint", side_effect=[launcher.source_fingerprint(), "edited"]), \
                patch.object(launcher.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(RuntimeError, "Sources changed before launch"):
                launcher.launch(self.args)
            popen.assert_not_called()

    def test_fingerprint_tracks_inputs_but_not_machine_data_or_timestamps(self):
        source = self.root / "src/app.py"
        source.parent.mkdir()
        source.write_text("first", encoding="utf-8")
        first = launcher.source_fingerprint()
        source.touch()
        (self.root / "state.sqlite3").write_bytes(b"user data")
        config = self.root / "config"
        config.mkdir()
        (config / "model_sources.json").write_text("{}", encoding="utf-8")
        self.assertEqual(first, launcher.source_fingerprint())
        for path in (source, config / "models.yaml", self.root / ".cargo/config.toml"):
            path.parent.mkdir(exist_ok=True)
            before = launcher.source_fingerprint()
            path.write_text("changed", encoding="utf-8")
            self.assertNotEqual(before, launcher.source_fingerprint())
        before = launcher.source_fingerprint()
        source.unlink()
        self.assertNotEqual(before, launcher.source_fingerprint())

    def test_overlapping_launcher_is_rejected_and_lock_is_released(self):
        with launcher.launcher_lock():
            with self.assertRaisesRegex(RuntimeError, "Another desktop launch"):
                with launcher.launcher_lock():
                    self.fail("second launch acquired the lock")
        with launcher.launcher_lock():
            pass

    def test_missing_build_tools_does_not_install_anything(self):
        with patch.object(launcher.shutil, "which", return_value=None), \
                patch.object(launcher.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "Missing build tools"):
                launcher.build()
            run.assert_not_called()


class BuildEnvironmentTests(unittest.TestCase):
    def test_installed_tools_preserve_host_toolchain_and_offline_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            desktop = root / "desktop"
            for relative in ("node_modules/vite/bin/vite.js", "node_modules/typescript/bin/tsc"):
                target = desktop / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch()
            host_env = {"PATH": "host-tools", "CARGO_HOME": "host-cargo",
                        "RUSTUP_HOME": "host-rustup", "RUSTUP_TOOLCHAIN": "stable-msvc"}
            with patch.object(launcher, "ROOT", root), patch.object(launcher, "DESKTOP", desktop), \
                    patch.object(launcher.shutil, "which", side_effect=["host/node.exe", "host/cargo.exe"]), \
                    patch.dict(launcher.os.environ, host_env, clear=True):
                node, cargo, env = launcher.build_environment()
            self.assertEqual(node, Path("host/node.exe"))
            self.assertEqual(cargo, Path("host/cargo.exe"))
            for key in ("CARGO_HOME", "RUSTUP_HOME", "RUSTUP_TOOLCHAIN"):
                self.assertEqual(env[key], host_env[key])
            self.assertEqual(env["RUSTUP_AUTO_INSTALL"], "0")
            self.assertEqual(env["CARGO_NET_OFFLINE"], "true")
            self.assertEqual(env["CARGO_TARGET_DIR"], str(desktop / "src-tauri/target"))

    def test_complete_portable_tools_keep_the_original_gnu_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            desktop = root / "desktop"
            for relative in (".runtimes/node-v24.19.0-win-x64/node.exe", ".runtimes/cargo/bin/cargo.exe",
                             ".runtimes/llvm-mingw-test/bin/gcc.exe", "desktop/node_modules/vite/bin/vite.js",
                             "desktop/node_modules/typescript/bin/tsc"):
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch()
            with patch.object(launcher, "ROOT", root), patch.object(launcher, "DESKTOP", desktop), \
                    patch.object(launcher.shutil, "which") as which:
                node, cargo, env = launcher.build_environment()
            which.assert_not_called()
            self.assertEqual(node, root / ".runtimes/node-v24.19.0-win-x64/node.exe")
            self.assertEqual(cargo, root / ".runtimes/cargo/bin/cargo.exe")
            self.assertEqual(env["RUSTUP_TOOLCHAIN"], "stable-x86_64-pc-windows-gnu")
            self.assertEqual(env["CARGO_HOME"], str(root / ".runtimes/cargo"))


if __name__ == "__main__":
    unittest.main()
