#Requires -Version 5.1
<#
.SYNOPSIS
    ASMR Helper 一键环境配置脚本

.DESCRIPTION
    自动完成以下步骤:
    1. 检测/安装 uv 包管理器
    2. 创建 Python 虚拟环境
    3. 安装核心依赖
    4. (可选) 安装 Qwen3-TTS 依赖
    5. 初始化配置文件
    6. 验证环境

.EXAMPLE
    .\setup.ps1                  # 基础安装 (ASR + Edge-TTS + Demucs)
    .\setup.ps1 -Full            # 完整安装 (含 Qwen3-TTS)
    .\setup.ps1 -SkipInstall     # 跳过依赖安装，仅初始化配置并验证
    .\setup.ps1 -DevOnly         # 仅安装开发工具

.NOTES
    需要的运行时:
    - Python 3.10+ (建议 3.12)
    - NVIDIA GPU + CUDA (可选，仅 Qwen3-TTS 需要)
#>

param(
    [switch]$Full,           # 包含 Qwen3-TTS (需要 CUDA GPU)
    [switch]$SkipInstall,    # 跳过依赖安装
    [switch]$DevOnly         # 仅安装开发工具
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

# ============================================================
# 工具函数
# ============================================================

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==================================================" -ForegroundColor Cyan
    Write-Host "  $Message" -ForegroundColor Cyan
    Write-Host "==================================================" -ForegroundColor Cyan
}

function Write-OK([string]$Message) {
    Write-Host "  [OK] $Message" -ForegroundColor Green
}

function Write-Warn([string]$Message) {
    Write-Host "  [WARN] $Message" -ForegroundColor Yellow
}

function Write-Fail([string]$Message) {
    Write-Host "  [FAIL] $Message" -ForegroundColor Red
}

function Test-Command([string]$Command) {
    return $null -ne (Get-Command $Command -ErrorAction SilentlyContinue)
}

# ============================================================
# Step 0: 切换到项目目录
# ============================================================
Write-Step "Step 0: 准备项目目录"
Set-Location $ProjectRoot
Write-OK "当前目录: $ProjectRoot"

# ============================================================
# Step 1: 检测/安装 uv
# ============================================================
Write-Step "Step 1: 检测 uv 包管理器"

if (Test-Command "uv") {
    $uvVersion = & uv --version
    Write-OK "uv 已安装: $uvVersion"
} else {
    Write-Warn "uv 未安装，正在通过 pip 安装..."
    python -m pip install uv
    if ($LASTEXITCODE -eq 0) {
        Write-OK "uv 安装成功"
    } else {
        Write-Fail "uv 安装失败，请手动安装: https://docs.astral.sh/uv/getting-started/installation/"
        exit 1
    }
}

# ============================================================
# Step 2: 同步依赖
# ============================================================
if (-not $SkipInstall -and -not $DevOnly) {
    Write-Step "Step 2: 安装项目依赖"

    if ($Full) {
        Write-Host "  安装完整依赖 (含 Qwen3-TTS)..." -ForegroundColor White
        & uv sync --extra qwen3
    } else {
        Write-Host "  安装核心依赖..." -ForegroundColor White
        & uv sync
    }

    if ($LASTEXITCODE -eq 0) {
        Write-OK "依赖安装完成"
    } else {
        Write-Fail "依赖安装失败"
        exit 1
    }
}

if ($DevOnly) {
    Write-Step "Step 2: 安装开发工具"
    & uv sync --extra dev
    if ($LASTEXITCODE -eq 0) {
        Write-OK "开发工具安装完成"
    } else {
        Write-Fail "开发工具安装失败"
        exit 1
    }
}

# ============================================================
# Step 3: 初始化配置文件
# ============================================================
Write-Step "Step 3: 初始化配置文件"

$configDir = Join-Path $ProjectRoot "config"
$configFile = Join-Path $configDir "config.json"
$exampleFile = Join-Path $configDir "config.example.json"

if (-not (Test-Path $configFile)) {
    if (Test-Path $exampleFile) {
        Copy-Item $exampleFile $configFile -Force
        Write-OK "已从 config.example.json 创建 config.json"
    } else {
        Write-Warn "config.example.json 不存在，跳过"
    }
} else {
    Write-OK "config.json 已存在，跳过"
}

# voice_profiles.json
$vpFile = Join-Path $configDir "voice_profiles.json"
$vpExample = Join-Path $configDir "voice_profiles.example.json"
if (-not (Test-Path $vpFile)) {
    if (Test-Path $vpExample) {
        Copy-Item $vpExample $vpFile -Force
        Write-OK "已从 voice_profiles.example.json 创建 voice_profiles.json"
    } else {
        Write-Warn "voice_profiles.example.json 不存在，跳过"
    }
} else {
    Write-OK "voice_profiles.json 已存在，跳过"
}

# 检查 API Key 配置
if (Test-Path $configFile) {
    $config = Get-Content $configFile -Raw | ConvertFrom-Json
    $hasKey = $false
    if ($config.api.deepseek_api_key -and $config.api.deepseek_api_key -ne "") { $hasKey = $true }
    if ($config.api.openai_api_key -and $config.api.openai_api_key -ne "") { $hasKey = $true }

    if (-not $hasKey) {
        Write-Warn "API Key 未配置"
        Write-Host ""
        Write-Host "  请通过以下任一方式配置:" -ForegroundColor White
        Write-Host "    1. 编辑 config/config.json 填入 API Key" -ForegroundColor White
        Write-Host "    2. 设置环境变量: `$env:DEEPSEEK_API_KEY = `"your-key`"" -ForegroundColor White
        Write-Host "    3. 在 GUI 的设置菜单中配置" -ForegroundColor White
    } else {
        Write-OK "API Key 已配置"
    }
}

# ============================================================
# Step 4: 创建目录结构
# ============================================================
Write-Step "Step 4: 创建必要目录"

$dirs = @(
    "models/voice_profiles",
    "models/qwen3tts",
    "output",
    ".workbuddy/memory",
    ".workbuddy/translation_cache"
)

foreach ($dir in $dirs) {
    $fullPath = Join-Path $ProjectRoot $dir
    if (-not (Test-Path $fullPath)) {
        New-Item -ItemType Directory -Path $fullPath -Force | Out-Null
        Write-OK "创建: $dir/"
    } else {
        Write-OK "已存在: $dir/"
    }
}

# ============================================================
# Step 5: 环境验证
# ============================================================
Write-Step "Step 5: 环境验证"

$checks = @(
    @{ Name = "Python"; Script = { & uv run python --version 2>&1 } },
    @{ Name = "faster-whisper"; Script = { & uv run python -c "import faster_whisper; print(faster_whisper.__version__)" 2>&1 } },
    @{ Name = "edge-tts"; Script = { & uv run python -c "import edge_tts; print('OK')" 2>&1 } },
    @{ Name = "demucs"; Script = { & uv run python -c "import demucs; print(demucs.__version__)" 2>&1 } },
    @{ Name = "PySide6 (GUI)"; Script = { & uv run python -c "import PySide6; print(PySide6.__version__)" 2>&1 } },
    @{ Name = "PyTorch + CUDA"; Script = {
        & uv run python -c "import torch; print(f'torch={torch.__version__}, cuda={torch.cuda.is_available()}, gpu={torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"N/A\"}')" 2>&1
    }}
)

if ($Full) {
    $checks += @(
        @{ Name = "qwen-tts"; Script = { & uv run python -c "import qwen_tts; print(qwen_tts.__version__)" 2>&1 } },
        @{ Name = "flash-attn"; Script = { & uv run python -c "import flash_attn; print(flash_attn.__version__)" 2>&1 } }
    )
}

$passed = 0
$failed = 0

foreach ($check in $checks) {
    try {
        $result = & $check.Script
        if ($LASTEXITCODE -eq 0) {
            $resultStr = ($result | Where-Object { $_ -is [string] }) -join ""
            Write-OK "$($check.Name): $resultStr"
            $passed++
        } else {
            Write-Fail "$($check.Name): 执行失败"
            $failed++
        }
    } catch {
        Write-Fail "$($check.Name): $($_.Exception.Message)"
        $failed++
    }
}

# ============================================================
# 结果汇总
# ============================================================
Write-Step "配置完成"
Write-Host ""
if ($failed -eq 0) {
    Write-Host "  所有检查通过!" -ForegroundColor Green
} else {
    Write-Host "  $passed 项通过, $failed 项失败" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "  后续步骤:" -ForegroundColor White
Write-Host "    1. 配置 API Key (编辑 config/config.json 或设置环境变量)" -ForegroundColor White
Write-Host "    2. 运行 GUI:     .\run.bat" -ForegroundColor White
Write-Host "    3. 命令行处理:  uv run python scripts/asmr_bilingual.py --input audio.wav" -ForegroundColor White
Write-Host ""
