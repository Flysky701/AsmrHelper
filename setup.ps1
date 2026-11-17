#Requires -Version 5.1
<#
.SYNOPSIS
    ASMR Helper 一键环境配置脚本

.DESCRIPTION
    负责环境准备、国内镜像源与离线链路引导、配置初始化、模型下载委托和基础验证。
    长期目标是让模型下载等核心能力回收到项目内部；本脚本只保留引导职责。

.EXAMPLE
    .\setup.ps1
    .\setup.ps1 -Full
    .\setup.ps1 -DomesticMirror
    .\setup.ps1 -Models -DomesticMirror
    .\setup.ps1 -Models -Engines fun_asr -DomesticMirror
    .\setup.ps1 -Models -Engines qwen3,voxcpm2 -Mirror
    .\setup.ps1 -Models -Full
    .\setup.ps1 -Offline
    .\setup.ps1 -SkipInstall
    .\setup.ps1 -DevOnly
    .\setup.ps1 -CleanReinstall
    .\setup.ps1 -Compute auto -Models
    .\setup.ps1 -Compute cpu -Models
    .\setup.ps1 -Compute cuda -Models
#>

param(
    [switch]$Full,
    [switch]$SkipInstall,
    [switch]$DevOnly,
    [switch]$Models,
    [switch]$Mirror,
    [switch]$DomesticMirror,
    [switch]$CleanReinstall,
    [switch]$Offline,
    [switch]$SkipFrontend,
    [ValidateSet("", "auto", "cpu", "cuda")]
    [string]$Compute = "",
    [string[]]$Engines = @(),
    [string]$PythonVersion = "3.12",
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

$AliyunPypiSimple = "https://mirrors.aliyun.com/pypi/simple"
$DomesticPythonMirror = "https://registry.npmmirror.com/-/binary/python-build-standalone/"
$DomesticNpmRegistry = "https://registry.npmmirror.com"
$UseDomesticMirror = [bool]($DomesticMirror -or $Mirror)

# Keep UV's mutable state project-scoped. This avoids inheriting another
# project's Conda interpreter and also makes caches/runtimes easy to inspect
# and remove without touching global Python installations.
if (-not $env:UV_CACHE_DIR) {
    $env:UV_CACHE_DIR = Join-Path $ProjectRoot ".cache\uv"
}
if (-not $env:UV_PYTHON_INSTALL_DIR) {
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $ProjectRoot ".runtimes\python"
}

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

function Configure-DomesticEnvironment {
    if (-not $UseDomesticMirror) {
        return
    }
    if (-not $env:UV_INDEX_URL) {
        $env:UV_INDEX_URL = $AliyunPypiSimple
    }
    if (-not $env:UV_PYTHON_INSTALL_MIRROR) {
        $env:UV_PYTHON_INSTALL_MIRROR = $DomesticPythonMirror
    }
    if (-not $env:NPM_CONFIG_REGISTRY) {
        $env:NPM_CONFIG_REGISTRY = $DomesticNpmRegistry
    }
    if (-not $env:ASMR_HELPER_DOWNLOAD_REGION) {
        $env:ASMR_HELPER_DOWNLOAD_REGION = "cn"
    }
    Write-OK "已启用国内高速镜像源 (ModelScope -> HF-Mirror -> HuggingFace / Aliyun PyPI / npmmirror)"
}

function Add-PathIfMissing([string]$CandidateDir) {
    if (-not $CandidateDir -or -not (Test-Path $CandidateDir)) {
        return
    }
    if (-not ($env:PATH -split ";" | Where-Object { $_ -eq $CandidateDir })) {
        $env:PATH = "$CandidateDir;$env:PATH"
    }
}

function Ensure-Uv {
    if (Test-Command "uv") {
        Write-OK "已检测到 uv"
        return
    }

    if ($Offline) {
        throw "离线模式 (-Offline) 下未检测到 uv，已禁止访问远程安装脚本。请预先安装 uv 并加入 PATH。"
    }

    Write-Host "  正在安装 uv..." -ForegroundColor White
    $installedViaDomestic = $false

    if ($UseDomesticMirror) {
        $bootstrapPy = $null
        if ($PythonPath -and (Test-Path $PythonPath)) {
            $bootstrapPy = $PythonPath
        } elseif (Test-Command "python") {
            $bootstrapPy = "python"
        }

        if ($bootstrapPy) {
            & $bootstrapPy -m pip install --user --index-url $AliyunPypiSimple uv
            if ($LASTEXITCODE -eq 0) {
                $userScripts = (& $bootstrapPy -c "import sysconfig; print(sysconfig.get_path('scripts', 'nt_user') or '')" 2>$null | Select-Object -Last 1)
                if ($userScripts) {
                    Add-PathIfMissing $userScripts.Trim()
                }
                $installedViaDomestic = $true
            }
        } elseif (Test-Command "pip") {
            & pip install --user --index-url $AliyunPypiSimple uv
            if ($LASTEXITCODE -eq 0) {
                $installedViaDomestic = $true
            }
        }
    }

    if (-not $installedViaDomestic -and -not (Test-Command "uv")) {
        if ($UseDomesticMirror) {
            Write-Warn "未检测到可用的本地 Python/pip，回退至官方安装脚本获取 uv"
        }
        Invoke-RestMethod "https://astral.sh/uv/install.ps1" | Invoke-Expression
    }

    $uvBinDir = Join-Path $env:USERPROFILE ".local\bin"
    Add-PathIfMissing $uvBinDir

    if (-not (Test-Command "uv")) {
        throw "uv 安装失败"
    }

    Write-OK "uv 安装完成"
}

function Add-NodeToPath {
    $nodeCandidates = @()
    if ($env:ASMR_HELPER_NODE_HOME) {
        $nodeCandidates += $env:ASMR_HELPER_NODE_HOME
    }
    $nodeCandidates += @(Get-ChildItem -Path (Join-Path $ProjectRoot ".runtimes\node-*-win-x64") -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Select-Object -ExpandProperty FullName)
    foreach ($candidate in $nodeCandidates) {
        if ((Test-Path (Join-Path $candidate "node.exe")) -and (Test-Path (Join-Path $candidate "npm.cmd"))) {
            $env:PATH = "$candidate;$env:PATH"
            return
        }
    }
    if ((Test-Command "node") -and (Test-Command "npm.cmd")) {
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

    # Do not inherit CONDA_PREFIX implicitly. A shell activated for another
    # project previously made .venv depend on that unrelated environment.
    return $PythonVersion
}

function Initialize-Workspace {
    Write-Step "Step 1: 准备项目目录"
    Set-Location $ProjectRoot
    Write-OK "当前目录: $ProjectRoot"
    Configure-DomesticEnvironment
}

function Invoke-DependencyInstall {
    Write-Step "Step 2: 同步 Python 依赖"
    if ($SkipInstall) {
        Write-OK "已跳过依赖安装"
        return
    }

    Ensure-Uv

    if ($CleanReinstall) {
        $venvDir = Join-Path $ProjectRoot ".venv"
        if (Test-Path $venvDir) {
            Remove-Item $venvDir -Recurse -Force
            Write-OK "已删除旧 .venv"
        }
    }

    $pythonSelector = Get-PythonSelector
    $syncArgs = @("sync", "--locked", "--python", $pythonSelector)
    if (-not $PythonPath) {
        $syncArgs += "--managed-python"
    }
    if ($Offline) {
        $syncArgs += @("--offline", "--no-python-downloads")
    } elseif ($UseDomesticMirror) {
        $syncArgs += @("--default-index", $AliyunPypiSimple)
    }

    # 始终保留测试与开发工具 (修复原 -Full 误跳过 --extra dev 的问题)。
    $syncArgs += @("--extra", "dev")
    if (($Models -or $Full) -and -not $DevOnly) {
        $syncArgs += @("--extra", "audio")
    }
    # Qwen/ASR providers use isolated .runtimes environments. Never install
    # mutually conflicting provider extras into the main .venv here.

    & uv @syncArgs

    if ($LASTEXITCODE -ne 0) {
        throw "uv sync 失败"
    }

    Write-OK "依赖同步完成"
}

function Invoke-ComputeInstall {
    Write-Step "Step 3: 选择并验证 CPU / CUDA 运行环境"
    $venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path $venvPython)) {
        throw "项目虚拟环境不存在，请先完成依赖同步。"
    }
    $computeArgs = @((Join-Path $ProjectRoot "scripts\configure_compute.py"), "--existing")
    if ($Compute) { $computeArgs += @("--compute", $Compute) }
    if ($Models -or $Full) { $computeArgs += "--require-main" }
    if ($Offline) { $computeArgs += "--offline" }
    if ($SkipInstall) {
        $computeArgs += "--check"
    } else {
        $computeArgs += "--apply"
    }
    & $venvPython @computeArgs
    if ($LASTEXITCODE -ne 0) {
        throw "CPU/CUDA 环境检查失败。请检查驱动与上方错误，或明确选择 -Compute cpu。"
    }
}

function Ensure-ConfigFiles {
    Write-Step "Step 4: 初始化配置"

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
    Write-Step "Step 5: 创建目录结构"

    $dirs = @(
        "models",
        "models\whisper",
        "models\qwen3tts",
        "models\voice_profiles",
        "output"
    )

    foreach ($dir in $dirs) {
        $fullPath = Join-Path $ProjectRoot $dir
        if (-not (Test-Path $fullPath)) {
            New-Item -ItemType Directory -Path $fullPath -Force | Out-Null
        }
    }

    Write-OK "目录结构已就绪"
}

function Invoke-FrontendInstall {
    Write-Step "Step 6: 同步桌面端依赖"
    if ($SkipFrontend) {
        Write-OK "已跳过桌面端依赖安装"
        return
    }

    Add-NodeToPath
    if (-not (Test-Command "node") -or -not (Test-Command "npm")) {
        throw "未找到 Node.js/npm。请先安装 Node.js 22 LTS 或更高版本。"
    }

    $npmArgs = @("ci")
    if ($Offline) {
        $npmArgs += @("--offline", "--prefer-offline")
    } elseif ($UseDomesticMirror) {
        $npmArgs += @("--registry", $DomesticNpmRegistry)
    }

    Push-Location (Join-Path $ProjectRoot "desktop")
    try {
        & npm.cmd @npmArgs
        if ($LASTEXITCODE -ne 0) {
            throw "npm ci 失败"
        }
    } finally {
        Pop-Location
    }
    Write-OK "桌面端依赖同步完成"
}

function Invoke-ModelInstall {
    Write-Step "Step 7: 下载模型"
    if (-not $Models) {
        Write-OK "未指定 -Models，跳过模型下载"
        return
    }

    Ensure-Uv

    $scriptPath = Join-Path $ProjectRoot "scripts\install_models.py"
    $venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path $venvPython)) {
        throw "项目虚拟环境不存在，请先完成依赖同步。"
    }
    $modelArgs = @($scriptPath)
    if ($Compute) { $modelArgs += @("--compute", $Compute) }

    if ($Engines.Count -gt 0) {
        foreach ($engine in $Engines) {
            $modelArgs += @("--provider", $engine)
        }
    } elseif ($Full) {
        $modelArgs += "--all"
    }

    if ($Offline) {
        $modelArgs += "--check"
    } elseif ($UseDomesticMirror) {
        $modelArgs += @("--mirror", "auto-cn")
    }

    & $venvPython @modelArgs
    if ($LASTEXITCODE -ne 0) {
        throw "模型下载失败"
    }

    Write-OK "模型下载完成"
}

function Invoke-EnvironmentVerify {
    Write-Step "Step 8: 环境验证"

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

Initialize-Workspace
Invoke-DependencyInstall
Invoke-ComputeInstall
Ensure-ConfigFiles
Ensure-Directories
Invoke-FrontendInstall
Invoke-ModelInstall
Invoke-EnvironmentVerify

Write-Step "Step 9: 完成"
Write-Host "  后续步骤:" -ForegroundColor White
Write-Host "    1. 配置 API Key (编辑 config/config.json 或设置环境变量)" -ForegroundColor White
Write-Host "    2. 下载模型:     .\setup.ps1 -Models -DomesticMirror" -ForegroundColor White
Write-Host "    3. 运行桌面端:   .\GUIRun.bat" -ForegroundColor White
Write-Host "    4. 环境检查:     .\run.bat test" -ForegroundColor White
Write-Host ""
