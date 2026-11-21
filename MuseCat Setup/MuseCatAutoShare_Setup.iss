; MuseCat Auto Share — Windows Setup Script (Inno Setup 6)
; Compiles dist\MuseCatAutoShare.exe into MuseCatAutoShare_Setup.exe

#define MyAppName "MuseCat Auto Share"
#define MyAppVersion "1.2.0"
#define MyAppPublisher "MuseCat"
#define MyAppExeName "MuseCatAutoShare.exe"

[Setup]
AppId={{8E3C6B42-4B7A-4F62-9A51-5A3D1C9E2B01}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=.
OutputBaseFilename=MuseCatAutoShare_Setup
SetupIconFile=..\assets\musecat_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\Kurulum_Rehberi.html"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\Setup_Guide_EN.html"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\assets\musecat_icon.ico"; DestDir: "{app}\assets"; Flags: ignoreversion
Source: "..\assets\musecat_icon_1024.png"; DestDir: "{app}\assets"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\musecat_icon.ico"
Name: "{group}\Kurulum Rehberi (TR)"; Filename: "{app}\Kurulum_Rehberi.html"
Name: "{group}\Setup Guide (EN)"; Filename: "{app}\Setup_Guide_EN.html"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\musecat_icon.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
