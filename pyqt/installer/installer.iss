; AI Modpack Builder — Inno Setup installer script.
; Compile from this directory with ISCC.exe installer.iss
; (Inno Setup 6, per-user install, no admin required).

#define MyAppName "AI Modpack Builder"
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#define MyAppPublisher "AI Modpack Builder"
#define MyAppExeName "AI Modpack Builder.exe"
#define MyAppId "{{8E5C4F2A-1D6B-4C9A-9E2F-7B3A0C5D6E1F}}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\installers
OutputBaseFilename=AI-Modpack-Builder-Setup-{#MyAppVersion}
SetupIconFile=..\app.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Publisher/support/update URLs are intentionally omitted until real public
; endpoints exist. Never show localhost as customer-facing metadata.

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; The PyInstaller one-folder bundle (dist/AI Modpack Builder/).
Source: "..\..\dist\{#MyAppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; The app's per-user data (workspace, builds, java, downloads) is under
; %LOCALAPPDATA%\AI Modpack Builder — keep it on uninstall unless the user
; removes the app data folder explicitly.
