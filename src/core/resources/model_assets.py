"""Read-only discovery of local weights, shared model trees and cache snapshots."""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path

from src.config import PROJECT_ROOT

_lock = threading.RLock()
DEMUCS_FILES = {
    'htdemucs': ['955717e8-8726e21a.th'],
    'htdemucs_ft': ['f7e0c4bc-ba3fe64a.th', 'd12395a8-e57c48e6.th', '92cfc3b6-ef3bcb9c.th', '04573f0d-f3cf25b2.th'],
    'htdemucs_6s': ['5c90dfd2-34c22ccb.th'],
}


def demucs_hf_manifest(name: str, path: Path) -> dict | None:
    """Read a complete local HF bag without contacting the Hub or resolving other bags."""
    if name not in DEMUCS_FILES:
        return None
    import yaml
    try:
        bag = yaml.safe_load((path / f'{name}.yaml').read_text(encoding='utf-8'))
        if not isinstance(bag, dict) or not isinstance(bag.get('models'), list) or not bag['models']:
            return None
        for signature in bag['models']:
            if not isinstance(signature, str) or not re.fullmatch(r'[A-Za-z0-9_]+', signature):
                return None
            weight = path / f'{signature}.safetensors'
            if not weight.is_file() or not weight.stat().st_size:
                return None
        return bag
    except (OSError, ValueError, yaml.YAMLError):
        return None


def sources() -> list[str]:
    path = PROJECT_ROOT / 'config' / 'model_sources.json'
    return json.loads(path.read_text(encoding='utf-8')).get('roots', []) if path.is_file() else []


def add_source(value: str) -> None:
    if not value.strip():
        raise ValueError('模型目录不能为空')
    path = Path(value).expanduser().resolve(strict=True)
    if not path.is_dir():
        raise ValueError('请选择已有模型目录或缓存目录')
    with _lock:
        roots = list(dict.fromkeys([*sources(), str(path)]))
        target = PROJECT_ROOT / 'config' / 'model_sources.json'
        target.parent.mkdir(parents=True, exist_ok=True)
        pending = target.with_suffix('.tmp')
        pending.write_text(json.dumps({'roots': roots}, ensure_ascii=False, indent=2), encoding='utf-8')
        pending.replace(target)


def remove_source(value: str) -> None:
    """Forget a library location, even if offline; never touch its files."""
    selected = Path(value).expanduser().resolve()
    with _lock:
        roots = [root for root in sources() if Path(root).expanduser().resolve() != selected]
        target = PROJECT_ROOT / 'config' / 'model_sources.json'
        target.parent.mkdir(parents=True, exist_ok=True)
        pending = target.with_suffix('.tmp')
        pending.write_text(json.dumps({'roots': roots}, ensure_ascii=False, indent=2), encoding='utf-8')
        pending.replace(target)


def complete(entry, path: Path) -> bool:
    if entry.provider == 'demucs' and demucs_hf_manifest(entry.upstream_name or 'htdemucs', path):
        return True
    required = DEMUCS_FILES.get(entry.upstream_name or 'htdemucs', []) if entry.provider == 'demucs' else entry.required_files
    if entry.install_strategy == 'package' and entry.provider != 'demucs':
        return True
    if not path.is_dir() or not required:
        return False
    if any(not (path / name).is_file() or (path / name).stat().st_size == 0 for name in required):
        return False
    if any(not (path / name).is_dir() for name in entry.required_dirs):
        return False
    if entry.provider == 'qwen3' and 'speech_tokenizer' in entry.required_dirs:
        if any(not (path / 'speech_tokenizer' / name).is_file() or not (path / 'speech_tokenizer' / name).stat().st_size
               for name in ('config.json', 'model.safetensors')):
            return False
    # Sharded weights are complete only when every referenced shard exists.
    for index in path.glob('*.index.json'):
        try:
            names = set(json.loads(index.read_text(encoding='utf-8')).get('weight_map', {}).values())
            if any(not (path / name).is_file() or (path / name).stat().st_size == 0 for name in names):
                return False
        except (ValueError, OSError):
            return False
    return True


def candidates(entry, roots: list[str] | None = None):
    roots = sources() if roots is None else roots
    repo = entry.upstream_name
    if not repo:
        from .model_installer import WHISPER_REPOS, QWEN3_REPOS
        repo = WHISPER_REPOS.get(entry.id) or QWEN3_REPOS.get(entry.id)
    for value in roots:
        root = Path(value).expanduser().resolve()
        yield root / (entry.install_path or '')
        if root.name in {Path(entry.install_path or '').name, (repo or '').split('/')[-1], 'checkpoints'}:
            yield root
        if entry.provider == 'demucs':
            yield root  # A user may select the HF snapshot directory itself.
            yield root / 'hub' / 'checkpoints'
            yield root / 'torch' / 'hub' / 'checkpoints'
            yield root / '.cache' / 'torch' / 'hub' / 'checkpoints'
            model_name = entry.upstream_name or 'htdemucs'
            hf_repo = 'HTDemucs' if model_name == 'htdemucs' else 'HTDemucs-' + model_name.removeprefix('htdemucs_')
            for cache in (root, root / 'hub', root / '.cache' / 'huggingface' / 'hub'):
                snapshots = cache / f'models--adefossez--{hf_repo}' / 'snapshots'
                if snapshots.is_dir():
                    yield from sorted(snapshots.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        if repo:
            slug = 'models--' + repo.replace('/', '--')
            yield root / repo.split('/')[-1]
            yield root / slug
            for cache in (root, root / 'hub', root / Path(entry.install_path or '').parent):
                snapshot = cache / slug / 'snapshots'
                if snapshot.is_dir():
                    yield from sorted(snapshot.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)


def resolve_assets(entry) -> Path:
    local = entry.managed_install_dir()
    if complete(entry, local):
        return local
    roots = scan_roots() if entry.provider == "demucs" else None
    found = next((p for p in candidates(entry, roots) if complete(entry, p)), None)
    if found is not None:
        return found
    # A legacy external model_cache_dir remains a read source. Missing downloads
    # go into this workspace, never into the external tree.
    if not local.resolve().is_relative_to(PROJECT_ROOT.resolve()):
        writable = PROJECT_ROOT / 'models' / (entry.install_path or entry.id)
        return writable
    return local


def shared(entry, path: Path | None = None) -> bool:
    path = (path or entry.resolved_install_dir()).resolve()
    if any(path.is_relative_to(Path(root).resolve()) for root in sources()):
        return True
    # External directories selected through the older settings page are protected too.
    return not path.is_relative_to(PROJECT_ROOT.resolve())


def scan_roots() -> list[str]:
    from src.workspace_paths import model_directory
    selected = model_directory(project_root=PROJECT_ROOT)
    roots = [PROJECT_ROOT / 'models', PROJECT_ROOT / '.cache' / 'torch',
             PROJECT_ROOT / '.cache' / 'huggingface' / 'hub',
             selected, selected.parent / '.cache' / 'torch', selected.parent / '.cache' / 'huggingface' / 'hub',
             Path.home() / '.cache' / 'torch', Path.home() / '.cache' / 'huggingface' / 'hub']
    for key in ('TORCH_HOME', 'HF_HOME', 'HF_HUB_CACHE', 'HUGGINGFACE_HUB_CACHE'):
        if os.environ.get(key):
            roots.append(Path(os.environ[key]))
    mapping = os.environ.get('ASMR_HELPER_RUNTIME_SOURCES')
    if mapping and Path(mapping).is_file():
        model_root = json.loads(Path(mapping).read_text(encoding='utf-8')).get('models')
        if model_root:
            roots.extend([Path(model_root), Path(model_root).parent / '.cache/torch'])
    return list(dict.fromkeys([*sources(), *(str(p.resolve()) for p in roots if p.is_dir())]))


def load_demucs(name: str, path: Path):
    bag = demucs_hf_manifest(name, path)
    if bag:
        try:
            from demucs.hf import load_safetensors_model
        except ImportError as exc:
            raise RuntimeError('已有 Demucs 权重为 HF safetensors 格式，当前环境缺少 demucs.hf 支持；不会转换或下载权重') from exc
        from demucs.apply import BagOfModels
        models = [load_safetensors_model(path / f'{sig}.safetensors') for sig in bag['models']]
        model = BagOfModels(models, bag.get('weights'), bag.get('segment'))
        model.eval()
        return model
    from demucs.pretrained import REMOTE_ROOT
    from demucs.repo import LocalRepo, BagOnlyRepo, AnyModelRepo
    # Read bag definitions from the package and checkpoints from the selected cache.
    # No get_model remote fallback, cache writes or implicit download.
    repo = LocalRepo(path)
    model = AnyModelRepo(repo, BagOnlyRepo(REMOTE_ROOT, repo)).get_model(name)
    model.eval()
    return model
