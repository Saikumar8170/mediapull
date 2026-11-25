$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
$domain = "pursuable-unfocused-gauging.ngrok-free.dev"
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "Creating virtual environment..."
    python -m venv .venv
    & $python -m pip install --upgrade pip
    & $python -m pip install -r requirements.txt
}

Write-Host "Starting MediaPull server on http://127.0.0.1:8000 ..."
$server = Start-Process -FilePath $python -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000" -PassThru -NoNewWindow

try {
    Write-Host ""
    Write-Host "Public URL (works on any device): https://$domain" -ForegroundColor Green
    Write-Host "Press Ctrl+C to stop both MediaPull and ngrok."
    & ngrok http --url=$domain 8000
} finally {
    if ($server -and -not $server.HasExited) {
        Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
    }
}
