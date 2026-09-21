param([switch]$SkipInstall)
$ErrorActionPreference = "Stop"
$ProjectRoot = (Split-Path -Parent $PSScriptRoot)
Set-Location $ProjectRoot
$ReleasePython = Join-Path $ProjectRoot ".release-venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $ReleasePython)) {
    & (Join-Path $ProjectRoot ".venv\Scripts\python.exe") -m venv .release-venv
    if ($LASTEXITCODE -ne 0) { throw "Release environment creation failed" }
}
if (-not $SkipInstall) {
    & $ReleasePython -m pip install -r requirements-build.lock
    if ($LASTEXITCODE -ne 0) { throw "Pinned dependency installation failed" }
}
& $ReleasePython -m pip check
if ($LASTEXITCODE -ne 0) { throw "Dependency validation failed" }
$DistPath = [IO.Path]::GetFullPath((Join-Path $ProjectRoot 'dist_release'))
if (-not $DistPath.StartsWith($ProjectRoot + [IO.Path]::DirectorySeparatorChar)) { throw 'Invalid build directory' }
& $ReleasePython -m PyInstaller --noconfirm --clean --distpath $DistPath --workpath build_release BioinfoLiteratureRadar.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
$Iscc = Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"
if (-not (Test-Path -LiteralPath $Iscc)) { throw "Inno Setup 6 missing; portable build is available in dist_release" }
& $Iscc (Join-Path $ProjectRoot 'installer\BioinfoLiteratureRadar.iss')
if ($LASTEXITCODE -ne 0) { throw 'Installer build failed' }
& $ReleasePython scripts/verify_artifact.py
if ($LASTEXITCODE -ne 0) { throw 'Artifact verification failed' }
