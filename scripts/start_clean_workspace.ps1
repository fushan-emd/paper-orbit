param([int]$Port=8010)
$ErrorActionPreference='Stop'
$ProjectRoot=Split-Path -Parent $PSScriptRoot
$Python=Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) { throw 'Create .venv and install requirements-runtime.lock first. See README.md.' }
# A per-checkout workspace; never use the installed app or author's workspace.
$env:LITERATURE_RADAR_ROOT=Join-Path $ProjectRoot 'private-preview'
foreach ($KeyName in @('DEEPSEEK_API_KEY','NCBI_API_KEY','OPENALEX_API_KEY')) {
    [Environment]::SetEnvironmentVariable($KeyName,$null,'Process')
}
Set-Location $ProjectRoot
& $Python desktop_app.py --no-window --open-browser --port $Port
exit $LASTEXITCODE
