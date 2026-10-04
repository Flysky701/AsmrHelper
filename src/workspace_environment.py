"""Application-scoped cache and temporary directories; never alter global settings."""
from pathlib import Path


def application_environment(root: Path, *, temporary: Path | None = None) -> dict[str, str]:
    cache = root / '.cache'
    hf = cache / 'huggingface'
    temp = temporary or root / 'debug' / 'runtime'
    paths = {
        'XDG_CACHE_HOME': cache,
        'UV_CACHE_DIR': root / '.uv-cache',
        'UV_PYTHON_INSTALL_DIR': root / '.runtimes' / 'python',
        'UV_TOOL_DIR': cache / 'uv-tools',
        'UV_TOOL_BIN_DIR': cache / 'uv-tools' / 'bin',
        'PIP_CACHE_DIR': cache / 'pip',
        'HF_HOME': hf, 'HF_HUB_CACHE': hf / 'hub', 'HUGGINGFACE_HUB_CACHE': hf / 'hub',
        'HF_ASSETS_CACHE': hf / 'assets', 'HF_XET_CACHE': hf / 'xet',
        'HF_MODULES_CACHE': hf / 'modules', 'TRANSFORMERS_CACHE': hf / 'hub',
        'TORCH_HOME': cache / 'torch', 'TORCH_EXTENSIONS_DIR': cache / 'torch-extensions',
        'TORCHINDUCTOR_CACHE_DIR': cache / 'torch-inductor',
        'MODELSCOPE_CACHE': cache / 'modelscope', 'NUMBA_CACHE_DIR': cache / 'numba',
        'TRITON_CACHE_DIR': cache / 'triton', 'CUDA_CACHE_PATH': cache / 'cuda',
        'CARGO_HOME': cache / 'cargo', 'CARGO_TARGET_DIR': cache / 'cargo-target',
        'PYTHONUSERBASE': cache / 'python-user',
        'TEMP': temp, 'TMP': temp, 'TMPDIR': temp,
    }
    return {key: str(value) for key, value in paths.items()}
