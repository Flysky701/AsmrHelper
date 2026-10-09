"""Bounded download policy for FasterWhisper; no global installer settings."""
from __future__ import annotations

import logging
import os
import subprocess
import tomllib
from pathlib import Path

logger = logging.getLogger(__name__)
PYPI = "https://pypi.org/simple"
TUNA = "https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple"
HUGGINGFACE = "https://huggingface.co"
HF_MIRROR = "https://hf-mirror.com"


def transient_network_error(detail: str) -> bool:
    detail = detail.lower()
    # Do not hide dependency conflicts, authentication, TLS, or corrupt files.
    if any(word in detail for word in ("certificate", "sslerror", "401", "403", "hash mismatch")):
        return False
    return any(word in detail for word in (
        "timeout", "timed out", "connection", "connecterror", "network is unreachable",
        "name resolution", "failed to fetch", "429", "500", "502", "503", "504",
    ))


def package_sources() -> list[str]:
    policy = os.environ.get("ASMR_HELPER_PYPI_FALLBACK", "tuna")
    if policy not in {"tuna", "none"}:
        raise ValueError("ASMR_HELPER_PYPI_FALLBACK must be tuna or none")
    return [PYPI, TUNA] if policy == "tuna" else [PYPI, PYPI]


def model_sources(mirror: str | None) -> list[str]:
    first = (mirror or os.environ.get("HF_ENDPOINT") or HUGGINGFACE).rstrip("/")
    if first not in {HUGGINGFACE, HF_MIRROR}:
        raise ValueError("FasterWhisper accepts only https://huggingface.co or https://hf-mirror.com")
    policy = os.environ.get("ASMR_HELPER_HF_FALLBACK", "hf-mirror")
    if policy not in {"hf-mirror", "none"}:
        raise ValueError("ASMR_HELPER_HF_FALLBACK must be hf-mirror or none")
    other = HF_MIRROR if first == HUGGINGFACE else HUGGINGFACE
    return [first, first, other] if policy == "hf-mirror" else [first, first]


def locked_requirements(lockfile: Path, roots: list[str], output: Path) -> Path:
    """Reuse the shipped lock's exact versions and PyPI wheel hashes on every source."""
    from packaging.markers import Marker

    with lockfile.open("rb") as stream:
        lock = tomllib.load(stream)
    packages = {}
    for package in lock["package"]:
        if package.get("version"):
            packages.setdefault(package["name"], []).append(package)
    selected = {}
    pending = list(roots)
    while pending:
        name = pending.pop()
        if name in selected:
            continue
        candidates = packages.get(name, [])
        if len(candidates) != 1:
            raise RuntimeError(f"FasterWhisper lock must identify exactly one version of {name}")
        package = candidates[0]
        if package.get("source") != {"registry": PYPI}:
            raise RuntimeError(f"FasterWhisper package is not locked to official PyPI: {name}")
        selected[name] = package
        for dependency in package.get("dependencies", []):
            marker = dependency.get("marker")
            if not marker or Marker(marker).evaluate({"extra": ""}):
                pending.append(dependency["name"])
    lines = []
    for name, package in sorted(selected.items()):
        hashes = sorted({wheel["hash"] for wheel in package.get("wheels", [])})
        if not hashes or any(not value.startswith("sha256:") for value in hashes):
            raise RuntimeError(f"FasterWhisper lock has no trusted wheel hashes: {name}")
        lines.append(f"{name}=={package['version']} " + " ".join(f"--hash={value}" for value in hashes))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def install_locked_packages(installer: dict, requirements: Path, *, env: dict, cwd: Path) -> None:
    env = env.copy()
    # Scope changes to this child. Keep the user's proxy and all cache paths.
    for key in list(env):
        if key.startswith(("UV_INDEX", "UV_EXTRA_INDEX", "UV_DEFAULT_INDEX", "PIP_INDEX", "PIP_EXTRA_INDEX")):
            env.pop(key)
    for key in ("PIP_TRUSTED_HOST", "UV_INSECURE_HOST", "PIP_FIND_LINKS", "UV_FIND_LINKS"):
        env.pop(key, None)
    env.update(UV_HTTP_TIMEOUT="30", UV_HTTP_RETRIES="1", PIP_CONFIG_FILE=os.devnull)
    for attempt, source in enumerate(package_sources(), 1):
        cmd = installer["packages_cmd"]([])
        uv = len(cmd) > 1 and cmd[1] == "pip"
        cmd.extend(["--require-hashes", "--only-binary", ":all:", "-r", str(requirements)])
        cmd.extend(["--no-config", "--default-index", source] if uv else
                   ["--index-url", source, "--timeout", "30", "--retries", "1"])
        logger.info("FasterWhisper dependencies source=%s attempt=%s/2 locked_hashes=true", source, attempt)
        try:
            result = subprocess.run(cmd, cwd=str(cwd), env=env, capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", timeout=600, check=False)
            if result.returncode == 0:
                logger.info("FasterWhisper dependency install complete: %s", result.stderr.strip())
                return
            detail = (result.stderr or result.stdout or "unknown error")[-2000:]
        except subprocess.TimeoutExpired:
            detail = "dependency download timed out after 600 seconds"
        if attempt == 2 or not transient_network_error(detail):
            raise RuntimeError(f"FasterWhisper dependency install failed source={source} attempt={attempt}: {detail}")
        logger.warning("FasterWhisper dependency network failure; retaining cache and switching source: %s", detail)
