from concurrent.futures import ThreadPoolExecutor
import json
import subprocess
import sys
import time
from threading import Event
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


@pytest.mark.parametrize("available", [True, False])
def test_result_survives_resolver_restart_without_expiring(tmp_path, monkeypatch, available):
    resolver, _, _ = environment(tmp_path)
    calls = []
    def run(*args, **kwargs):
        calls.append(args)
        return success() if available else SimpleNamespace(returncode=1, stdout="", stderr="missing")
    monkeypatch.setattr("src.core.runtime.profiles.subprocess.run", run)
    assert resolver.check_modules("fun_asr", ["funasr"]) is available
    # A new resolver represents restarting the app; elapsed wall time is not an invalidator.
    monkeypatch.setattr("src.core.runtime.profiles.time.time", lambda: 9999999999)
    assert RuntimeProfileResolver(tmp_path).check_modules("fun_asr", ["funasr"]) is available
    assert len(calls) == 1


def test_timeout_stays_unknown_and_manual_verification_retries(tmp_path, monkeypatch):
    resolver, _, _ = environment(tmp_path)
    calls = []
    def run(*args, **kwargs):
        calls.append(args)
        raise subprocess.TimeoutExpired("probe", 30)
    monkeypatch.setattr("src.core.runtime.profiles.subprocess.run", run)
    for current in (resolver, RuntimeProfileResolver(tmp_path)):
        with pytest.raises(RuntimeProbeError):
            current.check_modules("fun_asr", ["funasr"])
    assert len(calls) == 1
    resolver.clear_probe_cache("fun_asr")
    with pytest.raises(RuntimeProbeError):
        RuntimeProfileResolver(tmp_path).check_modules("fun_asr", ["funasr"])
    assert len(calls) == 2


@pytest.mark.parametrize("change", ["python", "package", "metadata", "cuda_env"])
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
    elif change == "package":
        (site / "new_package").mkdir()
    elif change == "metadata":
        metadata.write_text("Version: 2.0")
    else:
        monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "cache-test")
    assert resolver.check_modules("fun_asr", ["funasr"])
    assert len(calls) == 2


def test_corrupt_cache_falls_back_and_concurrent_requests_share_probe(tmp_path, monkeypatch):
    resolver, _, _ = environment(tmp_path)
    path = resolver._probe_cache.path(("fun_asr", "modules:funasr"))
    path.parent.mkdir(parents=True)
    path.write_text("{invalid")
    calls = []
    def run(*args, **kwargs):
        calls.append(args)
        time.sleep(.05)
        return success()
    monkeypatch.setattr("src.core.runtime.profiles.subprocess.run", run)
    with ThreadPoolExecutor(max_workers=6) as pool:
        assert all(pool.map(lambda _: resolver.check_modules("fun_asr", ["funasr"]), range(6)))
    assert len(calls) == 1
    assert json.loads(path.read_text())["available"] is True


def test_cuda_result_is_persistent_but_separate_from_module_result(tmp_path, monkeypatch):
    resolver, _, _ = environment(tmp_path)
    calls = []
    def run(*args, **kwargs):
        calls.append(args)
        return success()
    monkeypatch.setattr("src.core.runtime.profiles.subprocess.run", run)
    assert resolver.check_modules("fun_asr", ["funasr"])
    assert resolver.has_cuda("fun_asr")
    assert RuntimeProfileResolver(tmp_path).has_cuda("fun_asr")
    assert len(calls) == 2


def test_unwritable_cache_does_not_fail_probe(tmp_path, monkeypatch):
    resolver, _, _ = environment(tmp_path)
    from pathlib import Path
    original = Path.write_text
    def write(path, *args, **kwargs):
        if "runtime-probes" in path.parts:
            raise PermissionError("read only")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "write_text", write)
    monkeypatch.setattr("src.core.runtime.profiles.subprocess.run", success)
    assert resolver.check_modules("fun_asr", ["funasr"])
    monkeypatch.setattr("src.core.runtime.profiles.subprocess.run", lambda *a, **k: pytest.fail("memory cache lost"))
    assert resolver.check_modules("fun_asr", ["funasr"])


def test_explicit_model_verification_invalidates_runtime_cache(tmp_path):
    from src.core.resources.model_service import ModelService
    from unittest.mock import Mock
    service = ModelService.__new__(ModelService)
    service.runtime_resolver, _, _ = environment(tmp_path)
    service.runtime_resolver._set_cached_probe(("fun_asr", "modules:funasr"), True)
    service.get_model = Mock(return_value=SimpleNamespace(id="fun-model", kind="local", runtime_profile="fun_asr"))
    service.installer = Mock()
    service.installer.verify_local_model.return_value = True
    assert service.verify("fun-model") == {"fun-model": True}
    assert RuntimeProfileResolver(tmp_path)._get_cached_probe(("fun_asr", "modules:funasr")) is None


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


def test_invalidation_waits_for_inflight_probe_and_discards_its_result(tmp_path, monkeypatch):
    resolver, _, _ = environment(tmp_path)
    started, release, clearing = Event(), Event(), Event()
    def run(*args, **kwargs):
        started.set()
        assert release.wait(5)
        return success()
    def clear():
        clearing.set()
        resolver.clear_probe_cache("fun_asr")
    monkeypatch.setattr("src.core.runtime.profiles.subprocess.run", run)
    with ThreadPoolExecutor(max_workers=2) as pool:
        probe = pool.submit(resolver.check_modules, "fun_asr", ["funasr"])
        assert started.wait(5)
        invalidation = pool.submit(clear)
        assert clearing.wait(5)
        try:
            time.sleep(.02)
            assert not invalidation.done()
        finally:
            release.set()
        assert probe.result() is True
        invalidation.result()
    assert RuntimeProfileResolver(tmp_path)._get_cached_probe(("fun_asr", "modules:funasr")) is None
