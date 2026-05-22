# 模型资产元数据与安装契约草案 V1

## 目标

基于 [2026-05-22-model-asset-management-requirements-v1.md](D:/WorkSpace/AsmrHelper/docs/plan/2026-05-22-model-asset-management-requirements-v1.md) 已冻结的范围，定义一版可落地的后端 schema 草案，用于后续改造：

- [config/models.yaml](D:/WorkSpace/AsmrHelper/config/models.yaml)
- [src/core/resources/model_catalog.py](D:/WorkSpace/AsmrHelper/src/core/resources/model_catalog.py)
- [src/core/resources/model_installer.py](D:/WorkSpace/AsmrHelper/src/core/resources/model_installer.py)
- [src/api/http/schemas/models.py](D:/WorkSpace/AsmrHelper/src/api/http/schemas/models.py)
- [src/api/http/routes/models.py](D:/WorkSpace/AsmrHelper/src/api/http/routes/models.py)

## 范围前提

本草案默认以下决策已经成立：

- 本地统一支持仅覆盖 `PyTorch` 主线。
- 非 `PyTorch` 主线格式不进入当前本地模型资产管理框架。
- 第一轮优先服务 ASR/TTS 两类本地模型。
- 第一轮不做每模型独立环境，只做家族级共享环境表达。

## 设计原则

### 1. 模型条目必须能独立表达可安装性

单个模型条目不再只是“文件路径声明”，而是“安装单元声明”。

### 2. 家族信息必须显式存在

后续很多能力都依赖 `family_id`：

- 共享依赖
- 推荐组合
- 同家族全部下载
- 家族级环境策略

### 3. 附属资产必须是一等公民

不能再把 tokenizer、forced aligner、vocoder、reference runtime 等都塞进 provider 私有逻辑里。

### 4. 平台约束必须进入元数据

否则“下载后直接可用”无法稳定判定。

## 元数据结构草案

V1 建议将当前 `models.yaml` 中的每个模型条目扩展为以下结构。

### 顶层字段

```yaml
id: qwen3-asr-0.6b
kind: local
category: asr
provider: qwen3_asr
display_name: Qwen3-ASR 0.6B
description: Qwen3-ASR 0.6B multilingual offline ASR model
family_id: qwen3_asr
variant_group: qwen3_asr_main
variant_tier: standard
is_primary_variant: true
```

说明：

- `family_id`
  - 家族标识，后续用于共享依赖和家族级安装。
- `variant_group`
  - 用于区分同一家族内不同分支。
  - 例如 `main`、`forced_aligner`、`legacy`。
- `variant_tier`
  - 用于表达规模或推荐级别。
  - 例如 `lite`、`standard`、`full`、`legacy`。
- `is_primary_variant`
  - 标识该条目是否是该家族当前主推荐模型。

### 文件资产字段

```yaml
install_root: models
install_path: qwen3asr/Qwen3-ASR-0.6B
required_files:
  - config.json
  - model.safetensors
required_dirs: []
supports_install: true
supports_remove: true
install_strategy: huggingface_snapshot
upstream_name: Qwen/Qwen3-ASR-0.6B
download_sources:
  - type: huggingface
    repo_id: Qwen/Qwen3-ASR-0.6B
```

说明：

- `download_sources`
  - V1 虽然主下载源可以继续只用 Hugging Face，但字段先留出来。
  - 未来可扩展 `modelscope`。

### 依赖字段

```yaml
dependency_group: qwen3_asr
required_python_extras:
  - qwen_asr
required_runtime_packages: []
recommended_runtime_packages:
  - flash-attn
optional_runtime_packages: []
conflicts: []
```

说明：

- `dependency_group`
  - 用于表达家族共享依赖的归属。
- `required_python_extras`
  - 与当前 [pyproject.toml](D:/WorkSpace/AsmrHelper/pyproject.toml) 的 optional extras 对齐。
- `required_runtime_packages`
  - 直接写非 extra 的包名时，后续可以支持自动安装策略。
- `recommended_runtime_packages`
  - 不阻断可用性，但作为推荐优化项展示。
- `conflicts`
  - 暂时只需保留结构，不一定第一轮就实现复杂冲突解析。

### 附属资产字段

```yaml
required_assets: []
recommended_assets:
  - qwen3-forced-aligner-0.6b
optional_assets: []
```

说明：

- 字段值直接引用其他模型条目 `id`。
- 这样附属资产也能复用现有模型状态管理和安装逻辑。

### 运行约束字段

```yaml
runtime_profile: transformers_basic
supported_os:
  - windows
  - linux
supported_python:
  min: "3.10"
  max: "3.13"
requires_gpu: false
min_cuda: null
preferred_runtime: python_package_local
required_system_tools: []
required_binary_assets: []
required_vcs_features: []
```

说明：

- `runtime_profile`
  - 对运行方式做标准化标记。
- `supported_python`
  - 用于后续 readiness 检查。
- `requires_gpu`
  - 如果为 `true`，当前环境缺 GPU 时直接不可进入 `ready`。
- `required_system_tools`
  - 例如 `ffmpeg`、`git`、`git-lfs`、`espeak-ng`。
- `required_vcs_features`
  - V1 主要用于 `git-lfs` 这类需求表达。

### 安装模式字段

```yaml
install_modes:
  - single
  - recommended
  - family_all
default_install_mode: single
auto_install_dependencies: true
install_recommended_by_default: false
allow_remote_code: false
```

说明：

- `install_modes`
  - 标记该模型支持哪些安装模式。
- `auto_install_dependencies`
  - 控制是否允许后端自动补依赖。
- `install_recommended_by_default`
  - 控制“点击安装”默认是否连同推荐资产一起安装。
- `allow_remote_code`
  - 用于 `Fun-ASR` 等需要远程代码的家族。

### 安装后校验字段

```yaml
post_install_checks:
  - type: import_check
    target: qwen_asr
  - type: file_check
  - type: load_check
sample_inference_policy:
  enabled: false
healthcheck_timeout_seconds: 120
```

说明：

- `import_check`
  - 检查 Python 包是否能导入。
- `file_check`
  - 沿用当前 required files/dirs 检查。
- `load_check`
  - 实际尝试最小加载。
- `sample_inference_policy`
  - 第一轮建议默认关闭真正推理，只做最小加载。

## 家族级别补充结构

V1 可以先不单独拆 `families.yaml`，但逻辑上要支持家族配置。

建议先在代码层用内置默认结构表达：

```yaml
family_defaults:
  qwen3_asr:
    dependency_group: qwen3_asr
    install_modes: [single, recommended, family_all]
    auto_install_dependencies: true
  fun_asr:
    dependency_group: fun_asr
    allow_remote_code: true
  kokoro:
    dependency_group: kokoro
    required_system_tools: [espeak-ng]
```

后续如果条目越来越多，再决定是否拆独立家族注册表。

## 状态模型草案

V1 建议将状态细化为：

```text
missing
downloading
installing_dependencies
installing_assets
verifying
ready
invalid
unsupported
error
unloaded
configured
unconfigured
```

约束：

- `ready`
  - 仅用于本地模型且通过安装校验。
- `configured/unconfigured`
  - 仅用于云模型。
- `unsupported`
  - 当前环境不满足运行约束。

## 安装请求契约草案

当前 [ModelInstallRequest](D:/WorkSpace/AsmrHelper/src/api/http/schemas/models.py) 只有：

- `mirror`
- `force`

V1 建议扩展为：

```python
class ModelInstallRequest(BaseModel):
    mirror: str | None = None
    force: bool = False
    install_mode: str = "single"
    install_dependencies: bool = True
    install_recommended_assets: bool = False
    allow_fallback_variant: bool = False
```

字段解释：

- `install_mode`
  - `single / recommended / family_all`
- `install_dependencies`
  - 是否自动安装必需依赖。
- `install_recommended_assets`
  - 是否安装推荐附属资产。
- `allow_fallback_variant`
  - 如果目标模型不适配当前环境，是否允许自动推荐/切换同家族轻量变体。

## 安装流程草案

V1 后端安装流程建议标准化为：

1. 解析目标模型条目
2. 解析安装模式
3. 展开附属资产集合
4. 检查平台约束
5. 安装或校验依赖
6. 下载主模型与附属资产
7. 执行安装后校验
8. 写入最终状态

### 模式展开规则

#### `single`

- 当前模型
- 必需依赖
- 必需附属资产

#### `recommended`

- 当前模型
- 必需依赖
- 必需附属资产
- 推荐附属资产

#### `family_all`

- 同 `family_id` 下全部主变体
- 共享依赖只装一次
- 每个变体各自的必需附属资产

## 代表模型映射示例

### Qwen3-ASR 主模型

```yaml
id: qwen3-asr-0.6b
family_id: qwen3_asr
variant_group: qwen3_asr_main
variant_tier: standard
recommended_assets:
  - qwen3-forced-aligner-0.6b
required_python_extras:
  - qwen_asr
recommended_runtime_packages:
  - flash-attn
runtime_profile: transformers_basic
install_modes: [single, recommended, family_all]
```

### Fun-ASR 主模型

```yaml
id: fun-asr-nano-2512
family_id: fun_asr
variant_group: fun_asr_main
variant_tier: standard
required_python_extras:
  - funasr
allow_remote_code: true
runtime_profile: python_package_local
install_modes: [single, recommended, family_all]
```

### Kokoro

```yaml
id: kokoro-82m
family_id: kokoro
variant_group: kokoro_main
variant_tier: lite
required_python_extras: []
required_runtime_packages:
  - kokoro>=0.9.2
  - soundfile
required_system_tools:
  - espeak-ng
runtime_profile: python_package_local
install_modes: [single]
```

## 代码改造优先级建议

### 第一步

- 扩展 `ModelEntry` 数据结构
- 扩展 `models.yaml` 解析
- 保持旧字段兼容

### 第二步

- 扩展 `ModelInstallRequest`
- 扩展 `ModelInstaller.install_local_model(...)`
- 增加依赖安装与资产展开逻辑

### 第三步

- 扩展状态解析
- 增加平台约束检查
- 增加最小加载校验

### 第四步

- 再让桌面端暴露安装模式与状态细分

## 非目标

本草案暂不解决：

- 每模型独立虚拟环境
- 非 `PyTorch` 主线运行格式
- 社区量化权重统一接入
- 复杂的安装断点续传和下载队列编排

## 一句话结论

V1 schema 的关键不是把字段堆多，而是把“模型本体、家族依赖、附属资产、平台约束、安装模式、安装后校验”这六类信息正式建模出来。
