from types import SimpleNamespace

from scripts import configure_compute as cli


def resolver_fixture(tmp_path, monkeypatch):
    calls = []
    python = tmp_path / "python.exe"
    python.touch()

    class Resolver:
        def __init__(self, _root): pass
        def compute_mode(self): return "cpu"
        def resolve_compute_target(self): return "cpu"
        def save_compute_mode(self, mode): calls.append(("save", mode))
        def resolve(self, name): return SimpleNamespace(id=name, python_executable=python)
        def build_bootstrap_commands(self, profile):
            calls.append(("plan", profile.id))
            return [["uv", "pip", "install", "torch"]]
        def subprocess_env(self): return {}
        def verify_compute(self, profile):
            calls.append(("verify", profile.id))
            return {"device": "cpu"}

    monkeypatch.setattr(cli, "RuntimeProfileResolver", Resolver)
    monkeypatch.setattr(cli, "has_torch", lambda _python: True)
    return calls


def test_plan_never_saves_or_executes(tmp_path, monkeypatch):
    calls = resolver_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("unexpected installation")))
    monkeypatch.setenv("ASMR_HELPER_COMPUTE", "cuda")
    assert cli.main(["--compute", "cpu", "--existing"]) == 0
    assert calls == [("plan", profile) for profile in cli.PROFILES]
    assert cli.os.environ["ASMR_HELPER_COMPUTE"] == "cuda"


def test_check_verifies_without_install_or_persist(tmp_path, monkeypatch):
    calls = resolver_fixture(tmp_path, monkeypatch)
    assert cli.main(["--check", "--compute", "cpu"]) == 0
    assert calls == [("verify", "main")]


def test_apply_installs_then_verifies_and_honors_offline(tmp_path, monkeypatch):
    calls = resolver_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(cli.subprocess, "run", lambda command, **kwargs: calls.append(("install", command)))
    assert cli.main(["--apply", "--compute", "cpu", "--offline"]) == 0
    assert calls == [("save", "cpu"), ("plan", "main"), ("install", ["uv", "pip", "install", "torch", "--offline"]), ("verify", "main")]


def test_startup_only_does_not_pull_torch(tmp_path, monkeypatch):
    calls = resolver_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "has_torch", lambda _python: False)
    assert cli.main(["--apply"]) == 0
    assert calls == []


def test_failed_verification_is_failure(tmp_path, monkeypatch):
    calls = resolver_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(cli.RuntimeProfileResolver, "verify_compute", lambda *a: (_ for _ in ()).throw(RuntimeError("CPU build installed instead of CUDA")))
    assert cli.main(["--check"]) == 1
    assert calls == []
