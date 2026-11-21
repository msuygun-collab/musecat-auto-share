; MuseCat Auto Share — Windows Setup Script (Inno Setup 6 + Nuitka)
; Compiles Nuitka-built MuseCat.exe into MuseCat Setup\MuseCat_Setup.exe

#define MyAppName "MuseCat Auto Share"
#define MyAppVersion "1.2.0"
#define MyAppPublisher "MuseCat"
#define MyAppURL "https://github.com/msuygun-collab/musecat-auto-share"
#define MyAppExeName "MuseCat.exe"
#define DoubleAmp(Value) StringChange(Value, "&", "&&")

[Setup]
AppId={{9DCEFC20-A544-4F07-A1D4-1D94ADE33A9E}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=MuseCat Setup
OutputBaseFilename=MuseCat_Setup
SetupIconFile=assets\musecat_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern dark polar

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"
Name: "arabic"; MessagesFile: "compiler:Languages\Arabic.isl"
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "portuguese"; MessagesFile: "compiler:Languages\Portuguese.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "Kurulum_Rehberi.html"; DestDir: "{app}"; Flags: ignoreversion
Source: "Setup_Guide_EN.html"; DestDir: "{app}"; Flags: ignoreversion
Source: "assets\musecat_icon.ico"; DestDir: "{app}\assets"; Flags: ignoreversion
Source: "assets\musecat_icon_1024.png"; DestDir: "{app}\assets"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\musecat_icon.ico"
Name: "{autoprograms}\{#MyAppName} - Kurulum Rehberi (TR)"; Filename: "{app}\Kurulum_Rehberi.html"
Name: "{autoprograms}\{#MyAppName} - Setup Guide (EN)"; Filename: "{app}\Setup_Guide_EN.html"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\musecat_icon.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#DoubleAmp(MyAppName)}}"; Flags: nowait postinstall skipifsilent
