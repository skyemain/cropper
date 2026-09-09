; Inno Setup script for ID Photo Auto Cropper.
; Compile AFTER build_windows.bat has produced dist\ID Photo Auto Cropper\:
;   iscc packaging\installer.iss
; Produces dist\installer\IDPhotoAutoCropper-Setup.exe
;
; End users: double-click Setup.exe to install. To update, run a newer
; Setup.exe — it replaces the old version automatically. To remove, use
; Windows Settings → Apps → ID Photo Auto Cropper → Uninstall.

#include "app_version.iss"

#define MyAppName "ID Photo Auto Cropper"
#define MyAppExeName "ID Photo Auto Cropper.exe"
#define MyAppPublisher "ID Photo Auto Cropper"
#define MyAppURL "https://github.com/skyemain/cropper"

[Setup]
AppId={{B4D9A1E6-7C52-4F8B-9E3A-1D2C5B8F0A47}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Per-user install: no administrator rights required.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist\installer
OutputBaseFilename=IDPhotoAutoCropper-Setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
; Same AppId + UsePreviousAppDir = seamless upgrades when user runs a new Setup.
UsePreviousAppDir=yes
CloseApplications=force
AppMutex=Global\IDPhotoAutoCropper
RestartApplications=no
InfoBeforeFile=..\INSTALL.txt

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\{#MyAppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Comment: "Batch-align ID portrait photos (offline)"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; Comment: "Batch-align ID portrait photos (offline)"
Name: "{autoprograms}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{userappdata}\IDPhotoAutoCropper"

[Messages]
WelcomeLabel2=This will install [name/ver] on your computer.%n%nEverything runs locally — your photos never leave your PC.%n%nIf you already have an older version, it will be replaced automatically (your settings are kept in AppData).%n%nClick Next to continue.

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
end;

function InitializeUninstall(): Boolean;
begin
  Result := True;
end;
