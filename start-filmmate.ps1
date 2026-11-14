# Starts the Python app and opens its browser interface.

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $root '.venv\Scripts\python.exe'
$url = 'http://127.0.0.1:8000'

function Test-FilmmateHealth {
    try {
        $health = Invoke-RestMethod -Uri "$url/api/health" -TimeoutSec 2
        return ($health.ok -eq $true)
    }
    catch {
        return $false
    }
}

if (-not (Test-Path $py)) {
    Write-Host "[ERROR] Python venv not found: $py" -ForegroundColor Red
    Write-Host "        Run: python -m venv .venv"
    Write-Host "             .venv\Scripts\python.exe -m pip install -r requirements.txt"
    exit 1
}

if (Test-FilmmateHealth) {
    Write-Host "Filmmate is already running at $url" -ForegroundColor Green
    Start-Process $url
    exit 0
}

if (-not (Test-Path (Join-Path $root 'filmmate-web\dist\index.html') -PathType Leaf) -or
    -not (Test-Path (Join-Path $root 'filmmate-web\dist\assets') -PathType Container)) {
    Write-Host '[ERROR] Build the React frontend first. In filmmate-web, run npm ci and npm run build.' -ForegroundColor Red
    exit 1
}

Write-Host "Starting Filmmate at $url ..." -ForegroundColor Cyan
Write-Host "First startup may need to download the video search model."
$server = Start-Process -FilePath $py `
    -ArgumentList 'app.py' `
    -WorkingDirectory $root `
    -NoNewWindow -PassThru

try {
    $ready = $false
    $deadline = [DateTime]::UtcNow.AddMinutes(10)
    while (-not $server.HasExited -and [DateTime]::UtcNow -lt $deadline) {
        if (Test-FilmmateHealth) {
            $ready = $true
            break
        }
        Start-Sleep -Milliseconds 500
    }

    if (-not $ready) {
        Write-Host "[ERROR] Filmmate did not start. Check the Python output above." -ForegroundColor Red
        exit 1
    }

    Write-Host "Filmmate is running at $url. Press Ctrl+C to stop it." -ForegroundColor Green
    Start-Process $url
    Wait-Process -Id $server.Id
    exit $server.ExitCode
}
finally {
    if (-not $server.HasExited) {
        & taskkill.exe /PID $server.Id /T /F | Out-Null
    }
}
