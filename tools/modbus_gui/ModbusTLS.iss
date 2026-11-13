; Build with Inno Setup 6 on Windows, after build_windows.bat succeeds.
[Setup]
AppId={{E2665B6D-AB45-466E-A9D4-3A8C02638DC8}
AppName=Modbus TLS Debugger
AppVersion=2026.11.06
AppPublisher=LC400 Development
DefaultDirName={localappdata}\Programs\ModbusTLS
DefaultGroupName=Modbus TLS Debugger
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=ModbusTLS-Setup-2026.11.06
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\ModbusTLS.exe
DisableProgramGroupPage=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "dist\ModbusTLS.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "WINDOWS.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Modbus TLS Debugger"; Filename: "{app}\ModbusTLS.exe"
Name: "{autodesktop}\Modbus TLS Debugger"; Filename: "{app}\ModbusTLS.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ModbusTLS.exe"; Description: "Launch Modbus TLS Debugger"; Flags: nowait postinstall skipifsilent
