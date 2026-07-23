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
    [switch]$CleanReinstall,
    [switch]$Offline,
    [switch]$SkipFrontend,
    [string]$PythonVersion = "3.12",
    [string]$PythonPath = ""
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

function Add-NodeToPath {
    if (Test-Command "node") {
        return
    }

    $nodeKey = "HKLM:\SOFTWARE\Node.js"
    if (Test-Path $nodeKey) {
        $nodePath = (Get-ItemProperty $nodeKey -ErrorAction SilentlyContinue).InstallPath
        if ($nodePath -and (Test-Path (Join-Path $nodePath "node.exe"))) {
            $env:PATH = "$nodePath;$env:PATH"
        }
    }
}

function Get-PythonSelector {
    if ($PythonPath) {
        if (-not (Test-Path $PythonPath)) {
            throw "指定的 Python 不存在: $PythonPath"
        }
        return $PythonPath
    }

    if ($env:CONDA_PREFIX) {
        $condaPython = Join-Path $env:CONDA_PREFIX "python.exe"
        if (Test-Path $condaPython) {
            return $condaPython
        }
    }

    if ($Offline) {
        throw "离线安装需要可用的本机 Python 3.11/3.12。请使用 -PythonPath 指定 python.exe，或先激活对应 Conda 环境。"
    }

    return $PythonVersion
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

    $pythonSelector = Get-PythonSelector
    $syncArgs = @("sync", "--locked", "--python", $pythonSelector)
    if ($Offline) {
        $syncArgs += "--offline"
    }

    # DevOnly 表示额外安装测试/格式化工具；API 启动仍需要完整运行依赖。
    if ($DevOnly -or -not $Full) {
        $syncArgs += @("--extra", "dev")
    }
    if ($Models -or $Full) {
        $syncArgs += @("--extra", "audio")
    }
    if ($Full) {
        $syncArgs += @("--extra", "qwen3")
    }

    & uv @syncArgs

    if ($LASTEXITCODE -ne 0) {
        throw "uv sync 失败"
    }

    Write-OK "依赖同步完成"
}

function Invoke-FrontendInstall {
    if ($SkipFrontend) {
        Write-OK "已跳过桌面端依赖安装"
        return
    }

    Add-NodeToPath
    if (-not (Test-Command "node") -or -not (Test-Command "npm")) {
        throw "未找到 Node.js/npm。请先安装 Node.js 22 LTS 或更高版本。"
    }

    Write-Step "Step 3: 同步桌面端依赖"
    Push-Location (Join-Path $ProjectRoot "desktop")
    try {
        & npm.cmd ci
        if ($LASTEXITCODE -ne 0) {
            throw "npm ci 失败"
        }
    } finally {
        Pop-Location
    }
    Write-OK "桌面端依赖同步完成"
}

function Invoke-ModelInstall {
    if (-not $Models) {
        return
    }

    Ensure-Uv

    Write-Step "Step 5: 下载模型"
    $scriptPath = Join-Path $ProjectRoot "scripts\install_models.py"
    $venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path $venvPython)) {
        throw "项目虚拟环境不存在，请先完成依赖同步。"
    }
    $args = @($scriptPath)

    if ($Full) {
        $args += "--all"
    }

    if ($Mirror) {
        $bestMirror = Select-BestMirror
        if ($bestMirror.URL -match "tsinghua|aliyun") {
            $args += @("--mirror", "https://hf-mirror.com")
        }
    }

    & $venvPython @args
    if ($LASTEXITCODE -ne 0) {
        throw "模型下载失败"
    }

    Write-OK "模型下载完成"
}

function Invoke-EnvironmentVerify {
    Write-Step "Step 6: 环境验证"

    $verifyScript = Join-Path $ProjectRoot "scripts\verify_env.py"
    $venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path $venvPython)) {
        throw "项目虚拟环境不存在，请先完成依赖同步。"
    }
    & $venvPython $verifyScript | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "环境验证失败"
    }

    Write-OK "环境验证完成"
}

Write-Step "Step 0: 准备项目目录"
Set-Location $ProjectRoot
Write-OK "当前目录: $ProjectRoot"

Invoke-DependencyInstall
Ensure-ConfigFiles
Ensure-Directories
Invoke-FrontendInstall
Invoke-ModelInstall
Invoke-EnvironmentVerify

Write-Step "Step 7: 完成"
Write-Host "  后续步骤:" -ForegroundColor White
Write-Host "    1. 配置 API Key (编辑 config/config.json 或设置环境变量)" -ForegroundColor White
Write-Host "    2. 下载模型:     .\setup.ps1 -Models" -ForegroundColor White
Write-Host "    3. 运行桌面端:   .\GUIRun.bat" -ForegroundColor White
Write-Host "    4. 环境检查:     .\run.bat test" -ForegroundColor White
Write-Host ""
