; Inno Setup script for "RotaryUI-<version>-Windows-Setup.exe" — built by tools/build.py:
;   ISCC /DAppVersion=1.4.0 /DBuildDir="...\dist\Gesture Rotary" installer\windows\GestureRotary.iss
; Installs for the current user only (no admin prompt) into %LOCALAPPDATA%\Programs\Gesture Rotary.
; The app is called RotaryUI; its folder, program file and AppId keep their names from before, which existing
; installs (and their updates) go by.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef BuildDir
  #error Pass /DBuildDir=<the PyInstaller "Gesture Rotary" folder>
#endif

#define AppName "RotaryUI"
#define AppDir "Gesture Rotary"
#define AppExe "Gesture Rotary.exe"

[Setup]
AppId={{6F1E3C52-8A47-4C1B-9D2E-5B7A0F4C9E31}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=RotaryUI
AppCopyright=Copyright (c) 2026 MochiBoy9. MIT License.
AppPublisherURL=https://github.com/MochiBoy9/Gesture_Rotary
AppSupportURL=https://github.com/MochiBoy9/Gesture_Rotary/issues
AppUpdatesURL=https://github.com/MochiBoy9/Gesture_Rotary/releases
VersionInfoVersion={#AppVersion}
; The app's own Uninstall button and refresh code look for exactly this folder name.
DefaultDirName={autopf}\{#AppDir}
DisableDirPage=auto
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
WizardStyle=modern
SetupIconFile=..\..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes
RestartApplications=no
OutputBaseFilename=RotaryUI-{#AppVersion}-Windows-Setup

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "startup"; Description: "Start RotaryUI when I sign in to Windows"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
Source: "{#BuildDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; A new version replaces the old bundle completely (no stale libraries left behind).
Type: filesandordirs; Name: "{app}\_internal"
; The shortcuts' name from before RotaryUI (the new ones are added below).
Type: files; Name: "{autoprograms}\Gesture Rotary.lnk"
Type: files; Name: "{autodesktop}\Gesture Rotary.lnk"

[Icons]
; Same Start menu path the app itself checks, so it doesn't add a second entry.
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "GestureRotary"; ValueData: """{app}\{#AppExe}"" --minimized"; Tasks: startup; Flags: uninsdeletevalue
; Whatever the app set up itself, uninstalling removes it too.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "GestureRotary"; Flags: uninsdeletevalue dontcreatekey

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/IM ""{#AppExe}"" /F"; Flags: runhidden; RunOnceId: "StopApp"

[UninstallDelete]
; Settings in %APPDATA%\GestureRotary are kept unless removed from the app (General → Uninstall).
Type: filesandordirs; Name: "{app}"
