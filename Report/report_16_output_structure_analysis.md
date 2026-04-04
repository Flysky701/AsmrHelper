# 输出结构问题分析报告

## 1. 期望结构 vs 当前结构

### 1.1 单文件处理期望结构
```
<name>_output/
├── <name>_mix.<音频后缀>          # 成品文件（直接放在根目录）
└── BY_Product/                    # 中间产物目录
    ├── vocal.wav
    ├── asr_result.txt
    ├── translated.txt
    ├── tts_aligned.wav
    └── ...
```

### 1.2 批量处理期望结构
```
(root)/
├── Main_Product/                  # 所有成品集中存放
│   ├── <name1>_mix.<ext>
│   ├── <name2>_mix.<ext>
│   └── ...
└── BY_Product/                    # 中间产物按文件分目录
    ├── <name1>_by/
    │   ├── vocal.wav
    │   ├── asr_result.txt
    │   └── ...
    ├── <name2>_by/
    │   └── ...
    └── ...
```

### 1.3 当前实际结构（问题！）
```
output/
└── <task_name>/                   # 多余的层级
    ├── <task_name>_mix.wav        # 成品藏在子目录里
    ├── vocal.wav                  # 中间文件和成品混在一起
    ├── asr_result.txt
    ├── translated.txt
    └── tts_aligned.wav
```

---

## 2. 问题根因分析

### 2.1 核心问题：Pipeline._resolve_output_dirs() 设计缺陷

**文件**: `src/core/pipeline/__init__.py` (110-139行)

```python
def _resolve_output_dirs(self) -> tuple:
    """
    统一解析输出目录（消除多处重复计算）

    目录结构:
    - base_dir: 用户指定的基准目录（默认: 输入文件同级 output/）
    - task_dir: 任务输出目录（base_dir/task_name/）
      - 成品: task_dir/{task_name}_mix.wav
      - 中间文件: task_dir/{中间文件}
    """
    config = self.config
    input_path = Path(config.input_path)
    task_name = input_path.stem

    # 基准目录: 用户指定 output_dir（默认: 输入文件同级 output/）
    if config.output_dir:
        base_dir = Path(config.output_dir)
    else:
        base_dir = input_path.parent / "output"

    # 任务目录: base_dir/{task_name}/  ← 问题在这里！
    task_dir = base_dir / task_name  # ❌ 强制创建了 task_name 子目录

    ensure_dir(base_dir)
    ensure_dir(task_dir)

    return base_dir, task_dir
```

**问题**: 
- 强制创建 `task_name` 子目录，导致成品文件被深埋
- 中间文件和成品文件混在一起，没有分离

### 2.2 混音输出路径问题

**文件**: `src/core/pipeline/__init__.py` (522-525行)

```python
# ===== Step 5: 混音 (带错误处理) =====
current_step += 1
# 成品命名: <name>_mix.<ext>，放在 task_dir 中  ← 注释说明和期望不符
mix_ext = "wav"
mix_path = task_dir / f"{task_name}_mix.{mix_ext}"  # ❌ 放在 task_dir 里
```

**问题**: 成品文件放在 `task_dir`（中间文件目录）里，而不是单独的主目录。

### 2.3 脚本级重复实现

**文件**: `scripts/asmr_bilingual.py` (59-66行)

```python
# 输出目录（使用安全的目录名）
if args.output:
    output_dir = Path(args.output)
else:
    # 清理文件名中的特殊字符
    safe_name = "".join(c if c.isalnum() or c in " _-()" else "_" for c in input_path.stem)
    output_dir = input_path.parent / f"{safe_name}_output"  # ❌ 自己实现了一套目录逻辑
output_dir.mkdir(parents=True, exist_ok=True)
```

**问题**: 脚本自己实现了目录结构，和 Pipeline 的实现不一致！

### 2.4 GUI 层的目录处理

**文件**: `src/gui.py` (669-680行)

```python
def browse_single_file(self):
    """选择单文件"""
    file_path, _ = QFileDialog.getOpenFileName(...)
    if file_path:
        self.single_file_input.setText(file_path)
        if not self.single_output_input.text():
            p = Path(file_path)
            safe_name = "".join(c if c.isalnum() or c in " _-()" else "_" for c in p.stem)
            self.single_output_input.setText(str(p.parent / f"{safe_name}_output"))  # ❌ 又一套逻辑
```

**文件**: `src/gui_workers.py` (180-186行)

```python
# 基准输出目录（Pipeline 内部会创建 task_dir）
output_dir = (
    self.output_dir
    if self.output_dir
    else str(Path(input_path).parent / "output")  # ❌ 默认 output 目录
)
```

**问题**: GUI、Worker、Pipeline、脚本各自实现了不同的默认目录逻辑！

---

## 3. 耦合点详细分析

### 3.1 目录结构决策分散在 4 个地方

| 层级 | 文件 | 逻辑 | 问题 |
|------|------|------|------|
| GUI | `gui.py:669-680` | `{name}_output` | 和 Pipeline 不一致 |
| Worker | `gui_workers.py:180-186` | `{parent}/output` | 和 GUI 不一致 |
| Pipeline | `pipeline/__init__.py:110-139` | `{output_dir}/{task_name}/` | 强制子目录 |
| Script | `asmr_bilingual.py:59-66` | `{name}_output` | 独立实现 |

### 3.2 关键耦合：Pipeline 强制子目录

**影响**: 无论上层怎么设置 `output_dir`，Pipeline 都会在后面再加一层 `{task_name}/`

```
用户期望: output_dir = "MyOutput" → MyOutput/<name>_mix.wav
实际结果: output_dir = "MyOutput" → MyOutput/<name>/<name>_mix.wav
```

### 3.3 批量处理的特殊问题

**当前批量处理逻辑** (`gui_workers.py:180-186`):
```python
output_dir = (
    self.output_dir
    if self.output_dir
    else str(Path(input_path).parent / "output")
)
```

**问题**: 
1. 没有区分 Main_Product 和 BY_Product
2. 每个文件都调用 Pipeline，Pipeline 又各自创建子目录
3. 成品分散在各个子目录中，用户难以找到

---

## 4. 修复方案

### 4.1 方案 A：修改 Pipeline._resolve_output_dirs()

**目标**: 支持灵活的目录结构

```python
def _resolve_output_dirs(self) -> tuple:
    """
    统一解析输出目录
    
    返回:
        (main_product_dir, by_product_dir)
        - main_product_dir: 成品存放目录
        - by_product_dir: 中间文件存放目录
    """
    config = self.config
    input_path = Path(config.input_path)
    task_name = input_path.stem
    input_ext = input_path.suffix  # 保留原始音频后缀
    
    if config.output_dir:
        base_dir = Path(config.output_dir)
    else:
        base_dir = input_path.parent / f"{task_name}_output"
    
    # 单文件模式: 成品直接放 base_dir，中间文件放 base_dir/BY_Product/
    # 批量模式由调用方控制 base_dir
    main_product_dir = base_dir
    by_product_dir = base_dir / "BY_Product"
    
    ensure_dir(main_product_dir)
    ensure_dir(by_product_dir)
    
    return main_product_dir, by_product_dir, input_ext
```

### 4.2 方案 B：统一目录工具函数

**新建**: `src/utils/output_paths.py`

```python
"""
统一的输出路径管理
"""
from pathlib import Path
from typing import Tuple
from . import ensure_dir


def resolve_single_output_paths(
    input_path: str,
    output_dir: str = None
) -> Tuple[Path, Path, str]:
    """
    解析单文件处理的输出路径
    
    结构:
        {name}_output/
        ├── {name}_mix.{ext}      # 成品
        └── BY_Product/           # 中间文件
            ├── vocal.wav
            └── ...
    
    Returns:
        (mix_path, by_product_dir, task_name)
    """
    input_p = Path(input_path)
    task_name = input_p.stem
    input_ext = input_p.suffix
    
    if output_dir:
        base_dir = Path(output_dir)
    else:
        safe_name = "".join(c if c.isalnum() or c in " _-()" else "_" for c in task_name)
        base_dir = input_p.parent / f"{safe_name}_output"
    
    mix_path = base_dir / f"{task_name}_mix{input_ext}"
    by_product_dir = base_dir / "BY_Product"
    
    ensure_dir(base_dir)
    ensure_dir(by_product_dir)
    
    return mix_path, by_product_dir, task_name


def resolve_batch_output_paths(
    input_path: str,
    root_output_dir: str
) -> Tuple[Path, Path, str]:
    """
    解析批量处理的输出路径
    
    结构:
        root_output/
        ├── Main_Product/         # 所有成品
        │   └── {name}_mix.{ext}
        └── BY_Product/           # 中间文件
            └── {name}_by/
                └── ...
    
    Returns:
        (mix_path, by_product_dir, task_name)
    """
    input_p = Path(input_path)
    task_name = input_p.stem
    input_ext = input_p.suffix
    
    root_dir = Path(root_output_dir)
    main_product_dir = root_dir / "Main_Product"
    by_product_dir = root_dir / "BY_Product" / f"{task_name}_by"
    
    mix_path = main_product_dir / f"{task_name}_mix{input_ext}"
    
    ensure_dir(main_product_dir)
    ensure_dir(by_product_dir)
    
    return mix_path, by_product_dir, task_name
```

### 4.3 方案 C：修改 Pipeline 支持两种模式

```python
class PipelineConfig:
    # ... 现有字段 ...
    
    # 新增字段
    output_mode: str = "single"  # "single" | "batch"
    batch_root_dir: str = ""     # 批量模式下的根目录


class Pipeline:
    def _resolve_output_dirs(self) -> tuple:
        config = self.config
        input_path = Path(config.input_path)
        task_name = input_path.stem
        input_ext = input_path.suffix
        
        if config.output_mode == "batch" and config.batch_root_dir:
            # 批量模式
            root_dir = Path(config.batch_root_dir)
            main_product_dir = root_dir / "Main_Product"
            by_product_dir = root_dir / "BY_Product" / f"{task_name}_by"
        else:
            # 单文件模式
            if config.output_dir:
                base_dir = Path(config.output_dir)
            else:
                safe_name = sanitize_filename(task_name)
                base_dir = input_path.parent / f"{safe_name}_output"
            main_product_dir = base_dir
            by_product_dir = base_dir / "BY_Product"
        
        mix_path = main_product_dir / f"{task_name}_mix{input_ext}"
        
        ensure_dir(main_product_dir)
        ensure_dir(by_product_dir)
        
        return mix_path, by_product_dir, task_name
```

---

## 5. 修复优先级

| 优先级 | 问题 | 影响 | 修复方案 |
|--------|------|------|----------|
| P0 | Pipeline 强制子目录 | 所有输出结构错乱 | 修改 `_resolve_output_dirs()` |
| P0 | 成品和中间文件混在一起 | 用户找不到成品 | 分离 Main_Product/BY_Product |
| P1 | 四层目录逻辑不一致 | 维护困难 | 统一使用工具函数 |
| P1 | 批量处理结构未实现 | 批量功能不完整 | 实现 batch 模式 |
| P2 | 音频后缀丢失 | 输出格式不一致 | 保留 input_ext |

---

## 6. 测试验证点

### 6.1 单文件模式测试
```bash
# 测试 1: 默认输出
python scripts/asmr_bilingual.py -i test.wav
# 期望: test_output/test_mix.wav + test_output/BY_Product/*

# 测试 2: 指定输出目录
python scripts/asmr_bilingual.py -i test.wav -o MyOutput
# 期望: MyOutput/test_mix.wav + MyOutput/BY_Product/*
```

### 6.2 批量模式测试
```bash
# 测试 3: GUI 批量处理
# 期望: output/Main_Product/*_mix.wav + output/BY_Product/*_by/*
```

### 6.3 边界情况
- 文件名包含特殊字符
- 输入路径为绝对/相对路径
- 输出目录已存在
- 磁盘空间不足

---

## 7. 总结

**核心问题**: Pipeline 强制创建 `{task_name}/` 子目录，导致：
1. 成品文件被深埋
2. 成品和中间文件混在一起
3. 与 GUI、脚本的目录逻辑不一致

**修复关键**: 
1. 修改 `Pipeline._resolve_output_dirs()` 支持分离的成品/中间文件目录
2. 统一所有入口的目录逻辑
3. 明确区分单文件模式和批量模式
