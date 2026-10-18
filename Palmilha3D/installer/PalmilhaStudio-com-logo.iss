#define AppName "Palmilha Studio"
#define AppVersion "1.0.2"
#define AppPublisher "Palmilha Studio"
#define AppExeName "PalmilhaStudio.exe"
#define PayloadDir "payload\PalmilhaStudio"

[Setup]
AppId={{A4C92C2D-6392-4C3C-A209-087246191F7C}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\Palmilha Studio
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
PrivilegesRequired=admin
OutputDir=output
OutputBaseFilename=PalmilhaStudio-Setup-x64-{#AppVersion}-ComLogo
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\palmilhaLogo.ico
SetupIconFile=..\palmilhaLogo.ico
SetupLogging=yes
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; GroupDescription: "Atalhos adicionais:"; Flags: unchecked

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LEIA-ME-INSTALADOR.md"; DestDir: "{app}"; DestName: "LEIA-ME.md"; Flags: ignoreversion
Source: "..\palmilhaLogo.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "redist\vc_redist.x64.exe"; Flags: dontcopy

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\palmilhaLogo.ico"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\palmilhaLogo.ico"; Tasks: desktopicon

[Run]
Filename: "{tmp}\vc_redist.x64.exe"; Parameters: "/install /quiet /norestart"; StatusMsg: "Instalando o runtime do Visual C++..."; Flags: waituntilterminated; Check: not IsVCRedistInstalled
Filename: "{app}\{#AppExeName}"; Description: "Abrir o {#AppName}"; Flags: postinstall nowait skipifsilent

[Code]
function IsVCRedistInstalled: Boolean;
var
  Installed: Cardinal;
begin
  Result := RegQueryDWordValue(HKLM64, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'Installed', Installed) and (Installed = 1);
end;

function InitializeSetup: Boolean;
begin
  if not IsVCRedistInstalled then
    ExtractTemporaryFile('vc_redist.x64.exe');
  Result := True;
end;
