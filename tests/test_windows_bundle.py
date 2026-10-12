"""Clean installer resources omit dependency test audio, not runtime code."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("bundle_builder", Path(__file__).resolve().parents[1] / "scripts/build_windows_backend.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def test_removes_only_upstream_test_audio_inside_staging(tmp_path):
    site = tmp_path / "staging/site-packages"
    paths = [site / "scipy/io/tests/data/test.wav", site / "scipy/io/tests/data/LICENSE",
             site / "scipy/io/wavfile.py", site / "runtime/signal.wav", tmp_path / "user.wav"]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
    assert builder.remove_dependency_test_audio(site) == 1
    assert not paths[0].exists()
    assert all(path.read_bytes() == b"fixture" for path in paths[1:])


def test_bundle_audit_rejects_even_manifested_audio(tmp_path):
    import hashlib
    import json
    import subprocess
    import sys
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"RIFF fixture")
    (tmp_path / "manifest.json").write_text(json.dumps({"version": "1.0.0", "files": [
        {"path": "sample.wav", "sha256": hashlib.sha256(audio.read_bytes()).hexdigest()}]}), encoding="utf8")
    audit = Path(__file__).resolve().parents[1] / "scripts/audit_windows_bundle.py"
    result = subprocess.run([sys.executable, "-X", "utf8", "-B", str(audit), str(tmp_path)], capture_output=True, text=True)
    assert result.returncode == 1
    assert json.loads(result.stdout)["errors"] == [{"path": "sample.wav", "reason": "audio asset"}]
