#Requires -Version 5.1
<#
.SYNOPSIS
    ASMR Helper 一键环境配置脚本

.DESCRIPTION
    负责环境准备、配置初始化、模型下载委托和基础验证。
    长期目标是让模型下载等核心能力回收到项目内部；本脚本只保留引导职责。

.EXAMPLE
    .\setup.ps1
    .\setup.ps1 -Full
    .\setup.ps1 -Models
    .\setup.ps1 -Models -Full
    .\setup.ps1 -Models -Mirror
    .\setup.ps1 -SkipInstall
    .\setup.ps1 -DevOnly
    .\setup.ps1 -CleanReinstall
#>

param(
    [switch]$Full,
    [switch]$SkipInstall,
    [switch]$DevOnly,
    [switch]$Models,
    [switch]$Mirror,
    [switch]$CleanReinstall
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

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

$PyMirrors = @(
    @{ Name = "tsinghua"; URL = "https://pypi.tuna.tsinghua.edu.cn/simple" },
    @{ Name = "aliyun"; URL = "https://mirrors.aliyun.com/pypi/simple" }
)

function Get-MirrorLatency([string]$Url, [int]$TimeoutMs = 5000) {
    try {
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        $req = [System.Net.HttpWebRequest]::Create($Url)
        $req.Timeout = $TimeoutMs
        $req.Method = "HEAD"
        $resp = $req.GetResponse()
        $resp.Close()
        $sw.Stop()
        return [int]$sw.ElapsedMilliseconds
    } catch {
        return $null
    }
}

function Select-BestMirror {
    Write-Host "  正在测速选择最快源..." -ForegroundColor White

    $candidates = @(
        @{ Name = "pypi.org (官方)"; URL = "https://pypi.org" }
    ) + $PyMirrors

    $results = @()
    foreach ($candidate in $candidates) {
        $latency = Get-MirrorLatency -Url $candidate.URL
        if ($null -ne $latency) {
            $results += @{
                Name = $candidate.Name
                URL = $candidate.URL
                Latency = $latency
            }
        }
    }

    if ($results.Count -eq 0) {
        Write-Warn "所有源均不可达，将回退到官方源。"
        return @{ Name = "pypi.org (官方)"; URL = "https://pypi.org"; Latency = 9999 }
    }

    $best = $results | Sort-Object Latency | Select-Object -First 1
    Write-OK ("已选择: {0} ({1} ms)" -f $best.Name, $best.Latency)
    return $best
}

function Ensure-Uv {
    if (Test-Command "uv") {
        Write-OK "已检测到 uv"
        return
    }

    Write-Step "Step 1: 安装 uv"
    Invoke-RestMethod "https://astral.sh/uv/install.ps1" | Invoke-Expression

    $uvBinDir = Join-Path $env:USERPROFILE ".local\bin"
    if (-not ($env:PATH -split ";" | Where-Object { $_ -eq $uvBinDir })) {
        $env:PATH = "$uvBinDir;$env:PATH"
    }

    if (-not (Test-Command "uv")) {
        throw "uv 安装失败"
    }

    Write-OK "uv 安装完成"
}

function Ensure-ConfigFiles {
    Write-Step "Step 3: 初始化配置"

    $configDir = Join-Path $ProjectRoot "config"
    $exampleConfig = Join-Path $configDir "config.example.json"
    $targetConfig = Join-Path $configDir "config.json"
    $exampleVoices = Join-Path $configDir "voice_profiles.example.json"
    $targetVoices = Join-Path $configDir "voice_profiles.json"

    if (-not (Test-Path $targetConfig) -and (Test-Path $exampleConfig)) {
        Copy-Item $exampleConfig $targetConfig
        Write-OK "已创建 config.json"
    } elseif (Test-Path $targetConfig) {
        Write-OK "保留已有 config.json"
    } else {
        Write-Warn "未找到 config.example.json"
    }

    if (-not (Test-Path $targetVoices) -and (Test-Path $exampleVoices)) {
        Copy-Item $exampleVoices $targetVoices
        Write-OK "已创建 voice_profiles.json"
    } elseif (Test-Path $targetVoices) {
        Write-OK "保留已有 voice_profiles.json"
    } else {
        Write-Warn "未找到 voice_profiles.example.json"
    }

    Write-Host "  配置完成" -ForegroundColor White
}

function Ensure-Directories {
    Write-Step "Step 4: 创建目录结构"

    $dirs = @(
        "models",
        "models\whisper",
        "models\qwen3tts",
        "models\voice_profiles",
        "output",
        ".workbuddy\memory"
    )

    foreach ($dir in $dirs) {
        $fullPath = Join-Path $ProjectRoot $dir
        if (-not (Test-Path $fullPath)) {
            New-Item -ItemType Directory -Path $fullPath -Force | Out-Null
        }
    }

    Write-OK "目录结构已就绪"
}

function Invoke-DependencyInstall {
    if ($SkipInstall) {
        Write-OK "已跳过依赖安装"
        return
    }

    Ensure-Uv

    Write-Step "Step 2: 同步依赖"
    if ($CleanReinstall) {
        $venvDir = Join-Path $ProjectRoot ".venv"
        if (Test-Path $venvDir) {
            Remove-Item $venvDir -Recurse -Force
            Write-OK "已删除旧 .venv"
        }
    }

    if ($DevOnly) {
        & uv sync --extra dev
    } elseif ($Full) {
        & uv sync --extra qwen3 --extra dev
    } else {
        & uv sync
    }

    if ($LASTEXITCODE -ne 0) {
        throw "uv sync 失败"
    }

    Write-OK "依赖同步完成"
}

function Invoke-ModelInstall {
    if (-not $Models) {
        return
    }

    Ensure-Uv

    Write-Step "Step 5: 下载模型"
    $scriptPath = Join-Path $ProjectRoot "scripts\install_models.py"
    $args = @("run", "python", $scriptPath)

    if ($Full) {
        $args += "--all"
    }

    if ($Mirror) {
        $bestMirror = Select-BestMirror
        if ($bestMirror.URL -match "tsinghua|aliyun") {
            $args += @("--mirror", "https://hf-mirror.com")
        }
    }

    & uv @args
    if ($LASTEXITCODE -ne 0) {
        throw "模型下载失败"
    }

    Write-OK "模型下载完成"
}

function Invoke-EnvironmentVerify {
    Write-Step "Step 6: 环境验证"

    if (Test-Command "uv") {
        $verifyScript = Join-Path $ProjectRoot "scripts\verify_models.py"
        if (Test-Path $verifyScript) {
            & uv run python $verifyScript | Out-Host
        }
    } else {
        Write-Warn "未检测到 uv，跳过模型验证"
    }

    Write-OK "环境验证完成"
}

Write-Step "Step 0: 准备项目目录"
Set-Location $ProjectRoot
Write-OK "当前目录: $ProjectRoot"

Invoke-DependencyInstall
Ensure-ConfigFiles
Ensure-Directories
Invoke-ModelInstall
Invoke-EnvironmentVerify

Write-Step "Step 7: 完成"
Write-Host "  后续步骤:" -ForegroundColor White
Write-Host "    1. 配置 API Key (编辑 config/config.json 或设置环境变量)" -ForegroundColor White
Write-Host "    2. 下载模型:     .\setup.ps1 -Models" -ForegroundColor White
Write-Host "    3. 运行 GUI:     .\run.bat" -ForegroundColor White
Write-Host "    4. 命令行处理:   uv run python scripts/asmr_bilingual.py --input audio.wav" -ForegroundColor White
Write-Host ""
