; Build with Inno Setup 6 after build_windows.py. Npcap is installed separately.
[Setup]
AppId={{534578A3-1F80-4129-81F0-A4379A53C954}
AppName=GOOSE Secure Publisher
AppVersion=2026.11.24
AppPublisher=LC400 Development
DefaultDirName={autopf}\GoosePublisher
DefaultGroupName=GOOSE Secure Publisher
OutputDir=dist
OutputBaseFilename=GoosePublisher-Setup-2026.11.24
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\GoosePublisher.exe
DisableProgramGroupPage=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "dist\GoosePublisher.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "WINDOWS.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "THIRD-PARTY.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\GOOSE Secure Publisher"; Filename: "{app}\GoosePublisher.exe"
Name: "{autodesktop}\GOOSE Secure Publisher"; Filename: "{app}\GoosePublisher.exe"; Tasks: desktopicon
Name: "{group}\Npcap download"; Filename: "https://npcap.com/#download"

[Run]
Filename: "{app}\GoosePublisher.exe"; Description: "Launch GOOSE Secure Publisher"; Flags: nowait postinstall skipifsilent
