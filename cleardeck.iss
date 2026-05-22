; Inno Setup script for Cleardeck
;
; Produces CleardeckSetup.exe — a per-user installer that does NOT require
; admin privileges (installs to %LOCALAPPDATA%\Programs\Cleardeck).
;
; Usage (locally, from a Windows machine with Inno Setup 6 installed):
;     iscc cleardeck.iss
; Or via GitHub Actions on a windows-latest runner (see release.yml).

#define MyAppName "Cleardeck"
#define MyAppPublisher "AI Builders"
#define MyAppURL "https://github.com/ArthurCFR/Cleardeck"
#define MyAppExeName "Cleardeck.exe"

; The version is injected by CI (--define MyAppVersion=x.y.z). Fallback for
; local builds keeps the script self-sufficient.
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0-dev"
#endif

[Setup]
AppId={{8A3D6D34-2C5C-4F4D-93AC-CLEARDECK0001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

; Per-user install — no UAC prompt, faster onboarding.
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes

; Compression
Compression=lzma2/ultra
SolidCompression=yes

; Output
OutputDir=dist
OutputBaseFilename=CleardeckSetup
UninstallDisplayIcon={app}\{#MyAppExeName}
WizardStyle=modern

; Languages
ShowLanguageDialog=no

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "Créer un raccourci sur le Bureau"; GroupDescription: "Raccourcis :"; Flags: unchecked

[Files]
; PyInstaller output — copy everything under dist\Cleardeck\ into {app}.
Source: "dist\Cleardeck\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Désinstaller {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Lancer {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Leave user data (projects, model cache, logs) intact on uninstall — purge only
; if the user reinstalls from scratch. Adjust here if a clean wipe is desired.
Type: filesandordirs; Name: "{app}"
