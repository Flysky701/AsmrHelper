#Requires -Version 5.1
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Frontend", "Backend")]
    [string]$Mode,

    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot,

    [string]$ArtifactPath,
    [int]$BackendProcessId = 0,
    [string]$PidFile
)

$ErrorActionPreference = "Stop"

function Get-LatestWriteTimeUtc {
    param(
        [string[]]$Directories,
        [string[]]$Files
    )

    $timestamps = New-Object System.Collections.Generic.List[datetime]
    foreach ($directory in $Directories) {
        if (-not (Test-Path -LiteralPath $directory -PathType Container)) {
            continue
        }
        Get-ChildItem -LiteralPath $directory -File -Recurse -Force | ForEach-Object {
            $timestamps.Add($_.LastWriteTimeUtc)
        }
    }
    foreach ($file in $Files) {
        if (Test-Path -LiteralPath $file -PathType Leaf) {
            $timestamps.Add((Get-Item -LiteralPath $file).LastWriteTimeUtc)
        }
    }

    if ($timestamps.Count -eq 0) {
        return $null
    }
    return ($timestamps | Measure-Object -Maximum).Maximum
}

$resolvedRoot = [System.IO.Path]::GetFullPath($ProjectRoot)

if ($Mode -eq "Frontend") {
    if (-not $ArtifactPath -or -not (Test-Path -LiteralPath $ArtifactPath -PathType Leaf)) {
        Write-Output "missing"
        exit 0
    }

    $desktopRoot = Join-Path $resolvedRoot "desktop"
    $latestSource = Get-LatestWriteTimeUtc `
        -Directories @(
            (Join-Path $desktopRoot "src"),
            (Join-Path $desktopRoot "src-tauri\src"),
            (Join-Path $desktopRoot "src-tauri\capabilities"),
            (Join-Path $desktopRoot "src-tauri\icons")
        ) `
        -Files @(
            (Join-Path $desktopRoot "package.json"),
            (Join-Path $desktopRoot "package-lock.json"),
            (Join-Path $desktopRoot "tsconfig.json"),
            (Join-Path $desktopRoot "vite.config.ts"),
            (Join-Path $desktopRoot "src-tauri\Cargo.toml"),
            (Join-Path $desktopRoot "src-tauri\Cargo.lock"),
            (Join-Path $desktopRoot "src-tauri\build.rs"),
            (Join-Path $desktopRoot "src-tauri\tauri.conf.json")
        )
    $artifactTime = (Get-Item -LiteralPath $ArtifactPath).LastWriteTimeUtc
    if ($null -ne $latestSource -and $latestSource -gt $artifactTime) {
        Write-Output "stale"
    }
    else {
        Write-Output "fresh"
    }
    exit 0
}

if ($BackendProcessId -le 0 -or -not $PidFile) {
    Write-Output "unknown"
    exit 0
}

try {
    $recordedPid = [int](Get-Content -LiteralPath $PidFile -Raw).Trim()
    $process = Get-Process -Id $BackendProcessId -ErrorAction Stop
    $processPath = [System.IO.Path]::GetFullPath($process.Path)
}
catch {
    Write-Output "unknown"
    exit 0
}

$rootPrefix = $resolvedRoot.TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
if (
    $recordedPid -ne $BackendProcessId -or
    -not $processPath.StartsWith(
        $rootPrefix,
        [System.StringComparison]::OrdinalIgnoreCase
    )
) {
    Write-Output "foreign"
    exit 0
}

$latestBackendSource = Get-LatestWriteTimeUtc `
    -Directories @(
        (Join-Path $resolvedRoot "src"),
        (Join-Path $resolvedRoot "config")
    ) `
    -Files @(
        (Join-Path $resolvedRoot "pyproject.toml"),
        (Join-Path $resolvedRoot "uv.lock")
    )

if (
    $null -ne $latestBackendSource -and
    $latestBackendSource -gt $process.StartTime.ToUniversalTime()
) {
    Write-Output "stale"
}
else {
    Write-Output "fresh"
}
