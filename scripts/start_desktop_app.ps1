$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        python -m venv .venv
    } else {
        py -3 -m venv .venv
    }
}

& $VenvPython -c "import requests, webview" 2>$null
if ($LASTEXITCODE -ne 0) {
    & $VenvPython -m pip install -r requirements.txt
}

& $VenvPython desktop_app.py
