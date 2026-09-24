#define AppVersion "1.0.0"

[Setup]
AppId={{A530E5E6-9F5B-4D21-BBE9-D19B0DFB8456}
AppName=Aurora Music
AppVersion={#AppVersion}
AppPublisher=Aurora Music
DefaultDirName={autopf}\Aurora Music
DefaultGroupName=Aurora Music
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=AuroraMusic-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\assets\aurora.ico
UninstallDisplayIcon={app}\AuroraMusic.exe
DisableProgramGroupPage=yes

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Files]
Source: "..\dist\AuroraMusic\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Aurora Music"; Filename: "{app}\AuroraMusic.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Aurora Music"; Filename: "{app}\AuroraMusic.exe"; WorkingDir: "{app}"

[Run]
Filename: "{app}\AuroraMusic.exe"; Description: "Запустить Aurora Music"; Flags: nowait postinstall skipifsilent
