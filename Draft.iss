#define MyAppName "Draft"
#define MyAppVersion "0.2.0"
#define MyAppPublisher "Draft"
#define MyAppExeName "Draft.exe"

[Setup]
AppId={{DRAFT-7F6C2B4A-91D8-4F3A-B7E2-5A9C8D1E6F20}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}

DefaultDirName={autopf}\Draft
DefaultGroupName={#MyAppName}

OutputDir=output
OutputBaseFilename=Draft-Setup

Compression=lzma
SolidCompression=yes

ArchitecturesInstallIn64BitMode=x64compatible

WizardStyle=modern
Uninstallable=yes

ChangesEnvironment=yes

[Files]
Source: "dist\Draft\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Icons]
Name: "{group}\Draft"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\Draft"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; Check: NeedsAddPath(ExpandConstant('{app}'))

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch Draft"; Flags: nowait postinstall skipifsilent

[Code]

function NeedsAddPath(Param: string): Boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(
    HKEY_CURRENT_USER,
    'Environment',
    'Path',
    OrigPath
  ) then
  begin
    Result := True;
    Exit;
  end;

  Result :=
    Pos(
      ';' + UpperCase(Param) + ';',
      ';' + UpperCase(OrigPath) + ';'
    ) = 0;
end;