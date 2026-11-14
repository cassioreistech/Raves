; WinBot - instalador Inno Setup 6 (Passo 4)
;
; Compilado por:  .\scripts\build.ps1 -Installer
; Ou direto:     ISCC.exe /DMyAppVersion=0.1.0 installer.iss
;
; Caminhos relativos sao resolvidos a partir da pasta deste .iss (raiz do repo).
; A assinatura de codigo NAO e feita aqui: scripts/build.ps1 usa signtool no
; .exe interno e no instalador final com o mesmo certificado (D3).

#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif
#ifndef SourceDir
  #define SourceDir "dist\winbot"
#endif

#define MyAppName "WinBot"
#define MyAppPublisher "Cassio Reis Tech"
#define MyAppExeName "winbot.exe"
#define MyAppURL "https://github.com/cassioreistech/Raves"

[Setup]
AppId={{A7F3C1E4-9B2D-4E88-8C15-6D0A2E7B4F91}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Instalacao por usuario: PATH em HKCU e settings.yaml em {localappdata} precisam
; pertencer ao MESMO usuario. Com PrivilegesRequired=admin, UAC pode elevar para
; outra conta e o override de licenca cairia no perfil errado.
PrivilegesRequired=lowest
OutputDir=dist\installer
OutputBaseFilename=WinBotSetup-{#MyAppVersion}
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Nuitka gera binario x64 (CPython 3.12 x64). Nao ha payload 32-bit.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
ChangesEnvironment=yes

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "addtopath"; Description: "Adicionar WinBot ao PATH (recomendado)"; GroupDescription: "Integracao com o terminal:"; Flags: checkedonce

[Files]
; Payload do Nuitka: um unico .exe em --onefile, ou a pasta inteira em --standalone.
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs
; Liga o licenciamento apenas na distribuicao. Nunca sobrescreve config existente.
Source: "installer\settings.distribution.yaml"; DestDir: "{localappdata}\WinBot"; DestName: "settings.yaml"; Flags: onlyifdoesntexist

[Registry]
; Duas entradas: uma para quando PATH ainda nao existe, outra para append seguro.
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{app}"; Tasks: addtopath; Check: NoPathValue
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; Tasks: addtopath; Check: NeedsAddPath(ExpandConstant('{app}'))

[Icons]
Name: "{group}\WinBot Console"; Filename: "{sys}\cmd.exe"; Parameters: "/K ""{app}\{#MyAppExeName}"" --help"; WorkingDir: "{app}"; IconFilename: "{app}\{#MyAppExeName}"; Comment: "Abre um console com o WinBot pronto para uso"
Name: "{group}\Desinstalar WinBot"; Filename: "{uninstallexe}"

[Code]
function PathValueExists(): Boolean;
var
  Dummy: string;
begin
  Result := RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', Dummy);
end;

function NoPathValue(): Boolean;
begin
  Result := not PathValueExists();
end;

function NeedsAddPath(Param: string): Boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', OrigPath) then
  begin
    Result := False;
    exit;
  end;
  Result := Pos(';' + Uppercase(Param) + ';', ';' + Uppercase(OrigPath) + ';') = 0;
end;
