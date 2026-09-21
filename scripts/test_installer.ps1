$ErrorActionPreference='Stop'
$ProjectRoot=Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot
$CheckRoot=[IO.Path]::GetFullPath((Join-Path $ProjectRoot 'release_validation'))
$InstallRoot=[IO.Path]::GetFullPath((Join-Path $CheckRoot 'installed-smoke'))
if (-not $InstallRoot.StartsWith($CheckRoot + [IO.Path]::DirectorySeparatorChar)) { throw 'Invalid test installation path' }
$Source=Get-Content -LiteralPath installer/BioinfoLiteratureRadar.iss -Raw
$Source=$Source.Replace('AC491EC2-595E-4E7E-B2C6-A3C3FB763E59','E9091329-A29A-4A25-A522-3B76D848B85E').Replace('#define MyAppName "Paper Orbit"','#define MyAppName "Paper Orbit Release Smoke"').Replace('PaperOrbit-0.4.0-beta.2-Setup','PaperOrbit-Release-Smoke-Setup').Replace('Source: "config.toml";','Source: "..\installer\config.toml";')
$Spec=Join-Path $CheckRoot 'smoke-installer.iss'
[IO.File]::WriteAllText($Spec,$Source,[Text.UTF8Encoding]::new($false))
$Iscc=Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'
& $Iscc /Q $Spec
if ($LASTEXITCODE -ne 0) {throw 'Smoke installer compilation failed'}
$Setup=Join-Path $ProjectRoot 'release\PaperOrbit-Release-Smoke-Setup.exe'
$Arguments=@('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/NOICONS',('/DIR="'+$InstallRoot+'"'))
$Install=Start-Process -FilePath $Setup -ArgumentList $Arguments -WindowStyle Hidden -Wait -PassThru
if ($Install.ExitCode -ne 0) { throw 'Smoke installation failed' }
$Python=Join-Path $ProjectRoot '.release-venv\Scripts\python.exe'
& $Python scripts/smoke_packaged.py (Join-Path $InstallRoot 'BioinfoLiteratureRadar.exe')
if ($LASTEXITCODE -ne 0) {throw 'Installed application smoke check failed'}
$Config=Join-Path $InstallRoot 'config.toml'
$Before=(Get-FileHash -LiteralPath $Config -Algorithm SHA256).Hash
$Database=Join-Path $CheckRoot 'packaged-workspace\data\papers.sqlite'
$DbBefore=(Get-FileHash -LiteralPath $Database -Algorithm SHA256).Hash
$Upgrade=Start-Process -FilePath $Setup -ArgumentList $Arguments -WindowStyle Hidden -Wait -PassThru
if ($Upgrade.ExitCode -ne 0) {throw 'Upgrade failed'}
if ((Get-FileHash -LiteralPath $Config -Algorithm SHA256).Hash -ne $Before) {throw 'Upgrade changed config'}
$Uninstaller=Join-Path $InstallRoot 'unins000.exe'
$Uninstall=Start-Process -FilePath $Uninstaller -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART') -WindowStyle Hidden -Wait -PassThru
if ($Uninstall.ExitCode -ne 0) {throw 'Uninstall failed'}
if ((Get-FileHash -LiteralPath $Database -Algorithm SHA256).Hash -ne $DbBefore) {throw 'Uninstall changed independent user database'}
$Reinstall=Start-Process -FilePath $Setup -ArgumentList $Arguments -WindowStyle Hidden -Wait -PassThru
if ($Reinstall.ExitCode -ne 0) {throw 'Reinstall failed'}
& $Python scripts/smoke_packaged.py (Join-Path $InstallRoot 'BioinfoLiteratureRadar.exe')
if ($LASTEXITCODE -ne 0) {throw 'Reinstalled app failed'}
$Cleanup=Start-Process -FilePath $Uninstaller -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART') -WindowStyle Hidden -Wait -PassThru
if ($Cleanup.ExitCode -ne 0) {throw 'Smoke uninstall cleanup failed'}
@{status='passed';checks=@('install','upgrade_preserves_config','uninstall_preserves_workspace','reinstall');scope='isolated AppId on current Windows machine; not a clean VM'} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $CheckRoot 'installer-smoke.json') -Encoding UTF8
Write-Output 'PASS: installation, upgrade, uninstall and reinstall with an isolated test AppId.'
