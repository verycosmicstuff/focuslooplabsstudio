; Focusloop Labs - Inno Setup Script
; Generates a professional 1-click Windows Installer (Focusloop-Labs-Setup.exe)
; Prerequisites: Compile dist\SaveSpace first using scripts\build_dist.ps1

#define MyAppName "Focusloop Labs"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Focusloop Labs"
#define MyAppURL "https://focuslooplabs.vercel.app/"
#define MyAppExeName "FocusloopLabs.exe"
#define MyAppIcon "..\FocusloopLabs.ico"

[Setup]
; Unique GUID for Focusloop Labs
AppId={{E6F109A2-8BE2-430D-8F6C-23659A7210FA}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

; User-level installation (No administrator UAC password needed)
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\FocusloopLabs
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes

; Early Access & Responsibility Disclaimer
InfoBeforeFile=..\DISCLAIMER.txt

; Output Configuration
OutputDir=..\dist
OutputBaseFilename=Focusloop-Labs-Setup-v{#MyAppVersion}
SetupIconFile={#MyAppIcon}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern

; Branding & Metadata
UninstallDisplayIcon={app}\{#MyAppExeName}
VersionInfoVersion=1.0.0.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=Focusloop Labs — Creative Media Assistant & Storage Manager
VersionInfoProductName={#MyAppName}
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "startmenuicon"; Description: "Create a Start Menu shortcut"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; Distribute all files from dist\FocusloopLabs (excluding runtime databases and logs)
Source: "..\dist\FocusloopLabs\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.db,*.db-shm,*.db-wal,*.log"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\FocusloopLabs.ico"; Tasks: startmenuicon
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\FocusloopLabs.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Clean up runtime logs and cache on uninstall while preserving client media
Type: files; Name: "{app}\logs\*"
Type: filesandordirs; Name: "{app}\python\__pycache__"
Type: filesandordirs; Name: "{app}\src\__pycache__"
