#Requires -Version 5.1
param(
    [Parameter(Mandatory = $true)][string]$ProjectRoot,
    [Parameter(Mandatory = $true)][string]$PythonPath,
    [Parameter(Mandatory = $true)][int]$Port,
    [Parameter(Mandatory = $true)][string]$LogDir
)

$ErrorActionPreference = "Stop"
$pidFile = Join-Path $LogDir "backend.pid"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
$arguments = @(
    "-m", "src.api.http",
    "--host", "127.0.0.1",
    "--port", $Port,
    "--log-dir", ('"{0}"' -f $LogDir),
    "--pid-file", ('"{0}"' -f $pidFile)
)
$process = Start-Process `
    -FilePath $PythonPath `
    -ArgumentList $arguments `
    -WorkingDirectory $ProjectRoot `
    -WindowStyle Hidden `
    -PassThru

$deadline = (Get-Date).AddSeconds(10)
while ((Get-Date) -lt $deadline) {
    if (Test-Path -LiteralPath $pidFile) {
        $backendPid = (Get-Content -LiteralPath $pidFile -Raw).Trim()
        if ($backendPid -match '^\d+$') {
            Write-Output $backendPid
            exit 0
        }
    }
    if ($process.HasExited) {
        throw "Backend launcher exited before publishing its process ID."
    }
    Start-Sleep -Milliseconds 100
}

Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
throw "Backend did not publish its process ID within 10 seconds."
