#define MyAppName "Paper Orbit"
#define MyAppVersion "0.4.0.3"
#define MyAppPublisher "Paper Orbit contributors"
#define MyAppExeName "BioinfoLiteratureRadar.exe"

[Setup]
AppId={{AC491EC2-595E-4E7E-B2C6-A3C3FB763E59}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName=Paper Orbit 0.4.0-beta.3
LicenseFile=..\LICENSE
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\Bioinfo Literature Radar
DefaultGroupName={#MyAppName}
OutputDir=..\release
OutputBaseFilename=PaperOrbit-0.4.0-beta.3-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
PrivilegesRequired=lowest

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\dist_release\BioinfoLiteratureRadar\BioinfoLiteratureRadar.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist_release\BioinfoLiteratureRadar\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "config.toml"; DestDir: "{app}"; DestName: "config.toml"; Flags: onlyifdoesntexist uninsneveruninstall

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
