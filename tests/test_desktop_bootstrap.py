"""Regression tests for the portable Windows interpreter bootstrap."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from contextlib import contextmanager

SPEC = importlib.util.spec_from_file_location("desktop_bootstrap", Path(__file__).resolve().parents[1] / "scripts" / "desktop_backend.py")
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)

@contextmanager
def temporary_root():
    temporary = tempfile.TemporaryDirectory()
    # Cleanup must use the same extended-path support as the operation under test.
    temporary.name = str(bootstrap.extended_path(Path(temporary.name)))
    with temporary as name:
        yield name


class DesktopBootstrapTests(unittest.TestCase):
    def fixture(self, root):
        bundle = root / "bundle"
        (bundle / "python").mkdir(parents=True)
        (bundle / "python" / "python.exe").write_bytes(b"test fixture")
        (bundle / "ffmpeg" / "bin").mkdir(parents=True)
        (bundle / "ffmpeg" / "bin" / "avcodec-test.dll").write_bytes(b"test dll")
        return bundle

    def test_ready_runtime_is_reused_without_overwriting_user_packages(self):
        with temporary_root() as temp:
            root = Path(temp)
            bundle = self.fixture(root)
            python = bootstrap.prepare_runtime(bundle, root / "data")
            marker = python.parent / "user-installed-package.txt"
            marker.write_text("keep")
            self.assertEqual(bootstrap.prepare_runtime(bundle, root / "data"), python)
            self.assertEqual(marker.read_text(), "keep")
            self.assertEqual((python.parent / "Library/bin/avcodec-test.dll").read_bytes(), b"test dll")
            self.assertFalse((bundle / "python/Library").exists())

    @unittest.skipUnless(os.name == "nt", "Windows extended-path regression")
    def test_first_copy_supports_paths_beyond_max_path(self):
        with temporary_root() as temp:
            root = Path(temp)
            bundle = self.fixture(root)
            relative = Path("Lib/site-packages/openai/types/beta/realtime/conversation_item_input_audio_transcription_completed_event.py")
            source = bundle / "python" / relative
            source.parent.mkdir(parents=True)
            source.write_text("test")
            python = bootstrap.prepare_runtime(bundle, root / ("long-data-" + "x" * 110))
            target = python.parent / relative
            self.assertGreater(len(str(target)), 260)
            self.assertEqual(target.read_text(), "test")


if __name__ == "__main__":
    unittest.main()
