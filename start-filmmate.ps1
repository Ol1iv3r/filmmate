# Filmmate one-click launcher.
# Starts the Python backend and the Vite dev server, then stops both
# when this window is closed or Ctrl+C is pressed.

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$web = Join-Path $root 'filmmate-web'
$py = Join-Path $root '.venv\Scripts\python.exe'

if (-not (Test-Path $py)) {
    Write-Host "[ERROR] Python venv not found: $py" -ForegroundColor Red
    Write-Host "        Run: python -m venv .venv"
    Write-Host "             .venv\Scripts\python.exe -m pip install -r requirements.txt"
    exit 1
}

if (-not (Test-Path (Join-Path $web 'node_modules'))) {
    Write-Host "[ERROR] node_modules not found in $web" -ForegroundColor Red
    Write-Host "        Run: npm.cmd install (inside filmmate-web)"
    exit 1
}

Write-Host "Filmmate" -ForegroundColor White
Write-Host "---------------------------------------------" -ForegroundColor DarkGray
Write-Host "Starting backend  http://127.0.0.1:8000 ..." -ForegroundColor Cyan
$backend = Start-Process -FilePath $py `
    -ArgumentList 'app.py' `
    -WorkingDirectory $root `
    -NoNewWindow -PassThru

Write-Host "Starting frontend http://localhost:5173 ..." -ForegroundColor Cyan
$frontend = Start-Process -FilePath 'cmd.exe' `
    -ArgumentList '/c', 'npm.cmd run dev -- --open' `
    -WorkingDirectory $web `
    -NoNewWindow -PassThru

Write-Host ""
Write-Host "Open http://localhost:5173" -ForegroundColor Green
Write-Host "Close this window or press Ctrl+C to stop both." -ForegroundColor Green
Write-Host ""

$exitCode = 0
try {
    while (-not $backend.HasExited -and -not $frontend.HasExited) {
        Start-Sleep -Milliseconds 400
    }
}
finally {
    Write-Host ""
    Write-Host "Stopping ..." -ForegroundColor Yellow
    foreach ($p in @($frontend, $backend)) {
        if ($p -and -not $p.HasExited) {
            & taskkill.exe /PID $p.Id /T /F 2>$null | Out-Null
        }
    }
    Write-Host "Stopped." -ForegroundColor Yellow
}

exit $exitCode
