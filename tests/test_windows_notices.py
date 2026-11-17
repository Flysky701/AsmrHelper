"""Portable Cargo caches must retain their dependency license notices."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    "windows_notices", Path(__file__).resolve().parents[1] / "scripts/collect_windows_notices.py"
)
notices = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notices)


class WindowsNoticesTests(unittest.TestCase):
    def test_collects_license_from_configured_cargo_home(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "desktop/src-tauri").mkdir(parents=True)
            (root / "desktop/src-tauri/Cargo.lock").write_text(
                '[[package]]\nname="fixture"\nversion="1.0.0"\n'
                'source="registry+https://github.com/rust-lang/crates.io-index"\n',
                encoding="utf-8",
            )
            (root / "desktop/package-lock.json").write_text('{"packages": {}}', encoding="utf-8")
            cargo = root / "portable-cargo"
            package = cargo / "registry/src/test-index/fixture-1.0.0"
            package.mkdir(parents=True)
            (package / "Cargo.toml").write_text(
                '[package]\nname="fixture"\nversion="1.0.0"\nlicense="MIT"\n', encoding="utf-8"
            )
            (package / "LICENSE").write_text("fixture notice", encoding="utf-8")
            output = root / "notices"
            with patch.dict(os.environ, {"CARGO_HOME": str(cargo)}):
                self.assertEqual(notices.collect(root, output), 1)
            self.assertEqual(
                (output / "rust/fixture-1.0.0/LICENSE").read_text(encoding="utf-8"), "fixture notice"
            )
            inventory = json.loads((output / "desktop-dependencies.json").read_text(encoding="utf-8"))
            self.assertEqual(inventory[0]["license"], "MIT")


if __name__ == "__main__":
    unittest.main()
