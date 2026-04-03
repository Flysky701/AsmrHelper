# 环境转换报告：PyTorch CPU → CUDA + flash-attn 安装

**日期**: 2026-04-04  
**目标**: 将 PyTorch 从 CPU 版本切换到 CUDA 版本，并安装 flash-attn 加速库

---

## 1. 转换前环境

| 项目 | 值 |
|------|-----|
| Python | 3.10.19 |
| PyTorch | 2.11.0+**cpu** |
| torchaudio | 2.11.0+**cpu** |
| CUDA (torch.cuda) | **False** |
| flash-attn | 未安装 |
| GPU | NVIDIA RTX 4070 Ti SUPER (16GB, Compute 8.9) |
| NVIDIA Driver | 560.94 |

**问题**: PyTorch 为 CPU 版本，无法使用 GPU 加速。flash-attn 无法安装（需要 CUDA 版 PyTorch）。

### 转换前关键包版本

| 包 | 版本 |
|----|------|
| demucs | 4.0.1 |
| faster-whisper | 1.2.1 |
| edge-tts | 7.2.8 |
| qwen-tts | 0.1.1 |
| transformers | 4.57.3 |
| PySide6 | 6.11.0 |
| numpy | 1.26.4 |

完整 pip freeze 备份: `.workbuddy/memory/pip_freeze_before_cuda.txt`

---

## 2. 兼容性分析

### 2.1 flash-attn 版本要求

| 要求 | 当前值 | 状态 |
|------|--------|------|
| Python >= 3.9 | 3.10.19 | ✅ |
| PyTorch >= 2.2 | 2.11.0 | ✅ |
| CUDA >= 12.0 | cu126 (12.6) | ✅ |
| GPU Compute >= 8.0 | 8.9 (Ada Lovelace) | ✅ |
| Windows | Windows 11 x64 | ✅ |

### 2.2 预编译 Wheel 选择

flash-attn 官方 (PyPI) 不提供 Windows 预编译 wheel。使用第三方预编译源：

**源**: [mjun0812/flash-attention-prebuild-wheels](https://github.com/mjun0812/flash-attention-prebuild-wheels) (v0.9.6)

| 选择 | Wheel |
|------|-------|
| flash-attn 版本 | 2.8.3 |
| PyTorch 版本 | 2.11 |
| CUDA 版本 | 12.6 (cu126) |
| Python 版本 | 3.10 (cp310) |
| 平台 | win_amd64 |
| 文件名 | `flash_attn-2.8.3+cu126torch2.11-cp310-cp310-win_amd64.whl` (108MB) |

### 2.3 版本选择过程

| 尝试 | 方案 | 结果 |
|------|------|------|
| 1 | torch 2.11+cu124 | ❌ PyTorch 官方仓库最高只有 cu124 = torch 2.6.0 |
| 2 | torch 2.6+cu124 | ❌ 预编译 wheel 只有 torch2.11，无 torch2.6 |
| 3 | **torch 2.11+cu126** | ✅ PyTorch 官方仓库有，预编译 wheel 也有 |

**最终决定**: PyTorch 2.11.0+cu126 + flash-attn 2.8.3

---

## 3. 执行步骤

### 3.1 卸载旧版本

```powershell
uv pip uninstall torch torchaudio
```

### 3.2 安装 PyTorch CUDA 版本

```powershell
uv pip install torch==2.11.0+cu126 torchaudio==2.11.0+cu126 --index-url https://download.pytorch.org/whl/cu126
```

- 下载: torch 2.4GiB + torchaudio 1.4MiB
- 准备: 3分38秒
- 安装: 22秒

### 3.3 修复 pyproject.toml（关键）

**问题**: `uv run` 时 uv 会根据 pyproject.toml 重新同步依赖，将 torch 回退到 PyPI 的 CPU 版本。

**解决**: 在 `pyproject.toml` 中配置 `[tool.uv]` 强制使用 CUDA 源：

```toml
[tool.uv]
override-dependencies = [
    "onnxruntime>=1.16.0,<1.20.0",
    "torch==2.11.0+cu126",
    "torchaudio==2.11.0+cu126",
]

[[tool.uv.index]]
name = "pytorch-cu126"
url = "https://download.pytorch.org/whl/cu126"
explicit = true

[tool.uv.sources]
torch = { index = "pytorch-cu126" }
torchaudio = { index = "pytorch-cu126" }
```

### 3.4 安装 flash-attn

预编译 wheel 文件名不符合 PEP 427 标准（缺少标准 5 段分隔），pip/uv 无法直接安装。

**解决**: 手动解压 wheel 到 site-packages：

```python
import zipfile, os, site

whl_path = 'flash_attn-2.8.3+cu126torch2.11-cp310-cp310-win_amd64.whl'
site_packages = site.getsitepackages()[0]  # .venv

with zipfile.ZipFile(whl_path) as z:
    for info in z.infolist():
        dest = os.path.join(site_packages, info.filename)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if not info.is_dir():
            with z.open(info) as src, open(dest, 'wb') as dst:
                dst.write(src.read())
```

下载: 108MB (9秒，GitHub Releases)  
安装: 即时（解压文件复制）

### 3.5 安装 ninja（编译工具）

```powershell
uv pip install ninja
```

---

## 4. 转换后环境

| 项目 | 转换前 | 转换后 |
|------|--------|--------|
| PyTorch | 2.11.0+cpu | **2.11.0+cu126** |
| torchaudio | 2.11.0+cpu | **2.11.0+cu126** |
| CUDA | False | **True** |
| flash-attn | 未安装 | **2.8.3** |
| flash_attn_func | N/A | **可用** |

### 完整验证结果

```
=================================================================
Environment Verification Report
=================================================================
  [OK] Python            3.10.19
  [OK] PyTorch CUDA      torch=2.11.0+cu126, cuda=True
  [OK] GPU               NVIDIA GeForce RTX 4070 Ti SUPER ((8, 9))
  [OK] flash-attn        flash_attn 2.8.3
  [OK] flash_attn_func   imported
  [OK] demucs            demucs 4.0.1
  [OK] faster-whisper    faster_whisper 1.2.1
  [OK] edge-tts          edge_tts OK
  [OK] qwen-tts          qwen_tts OK
  [OK] transformers      transformers 4.57.3
  [OK] PySide6           PySide6 6.11.0
  [OK] numpy             numpy 1.26.4
  [OK] torchaudio        torchaudio 2.11.0+cu126
  [OK] huggingface_hub   huggingface_hub 0.36.2
=================================================================
Result: 13/13 passed - All checks passed!
=================================================================
```

完整 pip freeze 备份: `.workbuddy/memory/pip_freeze_after_cuda.txt`

---

## 5. 遇到的问题与解决方案

### 问题 1: uv run 回退到 CPU 版本
- **原因**: `uv run` 解析 pyproject.toml 依赖时，从 PyPI 拉取 torch（默认 CPU 版本），覆盖手动安装的 CUDA 版本
- **解决**: 在 `pyproject.toml` 的 `[tool.uv]` 中配置 `override-dependencies` 和自定义 index

### 问题 2: PyTorch 版本与预编译 wheel 不匹配
- **原因**: PyTorch 官方 cu124 仓库最高只到 2.6.0，而预编译 flash-attn wheel 只有 torch2.11 版本
- **解决**: 改用 cu126 仓库（有 torch 2.11.0），与 flash-attn 预编译版本匹配

### 问题 3: flash-attn wheel 文件名不符合 PEP 427
- **原因**: 第三方预编译 wheel 文件名格式不规范，pip/uv 拒绝安装
- **解决**: 下载后手动解压 wheel 到 site-packages 目录

### 问题 4: GitHub 下载不稳定
- **原因**: PowerShell 的 `Invoke-WebRequest` 别名和 SSL 验证问题
- **解决**: 使用 `curl.exe -L --ssl-no-revoke` 直接下载

---

## 6. 注意事项

### 6.1 flash-attn 安装方式

由于是手动解压安装（非 pip 安装），以下情况需要注意：
- `uv pip list` **不会**显示 flash-attn（因为不在 pip 元数据中）
- `uv sync` **不会**自动安装 flash-attn
- 如果 venv 被重建，需要重新手动安装

### 6.2 恢复方法

如需回退到 CPU 版本：
```powershell
uv pip uninstall torch torchaudio
uv pip install torch torchaudio
```
然后还原 `pyproject.toml` 中的 `[tool.uv]` 配置。

### 6.3 pyproject.toml 变更

本次修改了 `pyproject.toml`，添加了：
- `[tool.uv].override-dependencies`: 锁定 torch/torchaudio 为 CUDA 版本
- `[[tool.uv.index]]`: 添加 PyTorch CUDA 源
- `[tool.uv.sources]`: 指定 torch/torchaudio 从 CUDA 源获取
- `[project.optional-dependencies].qwen3`: 添加 `flash-attn>=2.7.0`

---

## 7. 性能预期

flash-attn 将为以下操作带来加速：

| 操作 | 预期加速 |
|------|----------|
| Qwen3-TTS 推理 | 1.5x ~ 2x（长序列 attention） |
| Demucs 人声分离 | 影响较小（主要用卷积） |
| Faster-Whisper ASR | 1.2x ~ 1.5x（encoder attention） |

RTX 4070 Ti SUPER 的 Ada Lovelace 架构 (SM 8.9) 完全支持 flash-attn 2.x 的所有优化。
