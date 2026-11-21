import subprocess
import sys
from types import SimpleNamespace

import pytest

from src.core.runtime.profiles import RuntimeProbeError, RuntimeProfileResolver


def environment(tmp_path):
    resolver = RuntimeProfileResolver(tmp_path)
    profile = resolver.resolve("fun_asr")
    profile.python_executable.parent.mkdir(parents=True)
    profile.python_executable.write_bytes(b"python")
    site = profile.environment_dir / "Lib" / "site-packages"
    site.mkdir(parents=True)
    return resolver, profile, site


def success(*args, **kwargs):
    return SimpleNamespace(returncode=0, stdout='__ASMR_RUNTIME_PROBE__{"funasr": true}', stderr="")


def test_timeout_stays_unknown_and_manual_verification_retries(tmp_path, monkeypatch):
    resolver, _, _ = environment(tmp_path)
    clock = [1000.0]
    monkeypatch.setattr("src.core.runtime.profiles.time.time", lambda: clock[0])
    calls = []
    def run(*args, **kwargs):
        calls.append(args)
        raise subprocess.TimeoutExpired("probe", kwargs["timeout"], output=(
            b'__ASMR_RUNTIME_EVENT__{"module":"funasr","phase":"start"}\n'))
    monkeypatch.setattr("src.core.runtime.profiles.subprocess.run", run)
    with pytest.raises(RuntimeProbeError, match="当前模块：funasr.*45 秒总上限"):
        resolver.check_modules("fun_asr", ["funasr"])
    with pytest.raises(RuntimeProbeError, match="历史缓存，本次未重新导入.*5分钟"):
        RuntimeProfileResolver(tmp_path).check_modules("fun_asr", ["funasr"])
    assert len(calls) == 1
    resolver.clear_probe_cache("fun_asr")
    with pytest.raises(RuntimeProbeError):
        RuntimeProfileResolver(tmp_path).check_modules("fun_asr", ["funasr"])
    assert len(calls) == 2
    clock[0] += 301
    monkeypatch.setattr("src.core.runtime.profiles.subprocess.run", success)
    assert resolver.check_modules("fun_asr", ["funasr"]) is True


@pytest.mark.parametrize("change", ["python", "metadata", "cuda_env"])
def test_environment_changes_invalidate_disk_and_memory_cache(tmp_path, monkeypatch, change):
    resolver, profile, site = environment(tmp_path)
    metadata = site / "funasr-1.dist-info" / "METADATA"
    metadata.parent.mkdir()
    metadata.write_text("Version: 1")
    calls = []
    def run(*args, **kwargs):
        calls.append(args)
        return success()
    monkeypatch.setattr("src.core.runtime.profiles.subprocess.run", run)
    resolver.check_modules("fun_asr", ["funasr"])
    if change == "python":
        profile.python_executable.write_bytes(b"new python")
    elif change == "metadata":
        metadata.write_text("Version: 2.0")
    else:
        monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "cache-test")
    assert resolver.check_modules("fun_asr", ["funasr"])
    assert len(calls) == 2


def test_actual_new_process_reads_cache_without_launching_probe(tmp_path):
    script = """
import subprocess, sys
from pathlib import Path
from src.core.runtime.profiles import RuntimeProfileResolver
resolver = RuntimeProfileResolver(Path(sys.argv[1]))
if len(sys.argv) > 2:
    def forbidden(*args, **kwargs):
        raise AssertionError('warm startup attempted another probe')
    subprocess.run = forbidden
assert resolver.check_modules('main', ['json']) is True
"""
    for args in ([], ["warm"]):
        result = subprocess.run([sys.executable, "-c", script, str(tmp_path), *args],
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr


def test_model_list_passively_reuses_runtime_and_gpu_checks_after_restart(tmp_path, monkeypatch):
    from src.core.resources.model_catalog import ModelEntry
    from src.core.resources.model_status import ModelStatusResolver

    resolver, _, site = environment(tmp_path)
    entry = ModelEntry(
        "model", "local", "asr", "Test model", "", runtime_profile="fun_asr",
        required_runtime_packages=["funasr"], requires_gpu=True, required_files=["weights.bin"],
    )
    monkeypatch.setattr(ModelEntry, "resolved_install_dir", lambda _: tmp_path)
    (tmp_path / "weights.bin").write_bytes(b"weights")
    package = site / "funasr"
    package.mkdir()
    (package / "__init__.py").touch()
    calls = []

    def run(*args, **kwargs):
        calls.append(args)
        return success()

    monkeypatch.setattr("src.core.runtime.profiles.subprocess.run", run)
    status_resolver = ModelStatusResolver(runtime_resolver=resolver)
    pending = status_resolver.resolve(entry, cached_only=True)
    assert pending.weights_ready and not pending.executable
    assert [issue.code for issue in pending.issues] == ["RUNTIME_CHECK_PENDING"]
    assert not calls
    assert status_resolver.resolve(entry).executable
    (package / "__pycache__").mkdir()
    monkeypatch.setenv("PATH", "alternate launcher path")
    restarted = ModelStatusResolver(runtime_resolver=RuntimeProfileResolver(tmp_path))
    assert restarted.resolve(entry, cached_only=True).executable
    assert len(calls) == 2
