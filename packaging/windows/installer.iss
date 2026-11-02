; Instalador do Windows (Inno Setup 6) — assistente "Avançar → Avançar → Instalar".
;
; Por que Inno Setup e não um assistente próprio como no Linux: no Windows o
; instalador com assistente é o formato nativo e esperado, e o Inno já resolve
; de graça o que daria muito trabalho fazer à mão — entrada em Programas e
; Recursos, desinstalador, detecção de instalação anterior, atalhos no Menu
; Iniciar, e fechamento do app antes de atualizar.
;
; Não compile este arquivo direto; use packaging/windows/build.ps1, que gera o
; bundle do PyInstaller antes e injeta a versão via /D.

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

#define MyAppName "Telegram Jellyfin Organizer"
; Nome da pasta de dados do usuário. Tem que casar exatamente com o APP_NAME
; de core/credentials.py — é o que o platformdirs usa para montar
; %LOCALAPPDATA%\<appname> no Windows. Errar aqui faz o desinstalador
; procurar (e potencialmente apagar) a pasta errada.
#define MyDataDirName "TelegramJellyfinOrganizer"
#define MyAppPublisher "LorranCastro12"
#define MyAppURL "https://github.com/LorranCastro12/telegram-jellyfin-organizer"
#define MyAppExeName "TelegramJellyfinOrganizer.exe"
#define BundleDir "..\..\dist\TelegramJellyfinOrganizer"
#define AssetsDir "..\assets"

[Setup]
; Este GUID identifica o produto para atualizações/desinstalação.
; NÃO mude entre versões — se mudar, o Windows passa a tratar a nova versão
; como um programa diferente e o usuário fica com duas entradas instaladas.
AppId={{7A80F824-E8A9-4C62-AC6A-97EEE24850CD}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=Instalador do {#MyAppName}

; Instala na pasta do usuário e sem pedir UAC por padrão. O app guarda
; credenciais e sessão no perfil do usuário, então não há motivo para exigir
; administrador — mas quem quiser instalar para todos os usuários ainda pode,
; pelo diálogo que o "OverridesAllowed" habilita.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
AllowNoIcons=yes
UninstallDisplayName={#MyAppName} {#MyAppVersion}
UninstallDisplayIcon={app}\{#MyAppExeName}

LicenseFile=..\..\LICENSE
OutputDir=..\..\dist
OutputBaseFilename=TelegramJellyfinOrganizer-{#MyAppVersion}-windows-x64-Setup
SetupIconFile={#AssetsDir}\icon.ico
WizardStyle=modern
WizardImageFile={#AssetsDir}\wizard_large.bmp,{#AssetsDir}\wizard_large@2x.bmp
WizardSmallImageFile={#AssetsDir}\wizard_small.bmp,{#AssetsDir}\wizard_small@2x.bmp

Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
ShowLanguageDialog=no

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar um atalho na &Área de Trabalho"; GroupDescription: "Atalhos:"
Name: "startmenuicon"; Description: "Criar um atalho no &Menu Iniciar"; GroupDescription: "Atalhos:"; Flags: checkedonce

[Files]
Source: "{#BundleDir}\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startmenuicon
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"; Tasks: startmenuicon
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Executar o {#MyAppName} agora"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; O PyInstaller gera .pyc em runtime dentro de _internal; sem isto a pasta
; fica para trás depois de desinstalar.
Type: filesandordirs; Name: "{app}\_internal"
Type: dirifempty; Name: "{app}"

[Messages]
brazilianportuguese.WelcomeLabel2=Este assistente vai instalar o [name/ver] no seu computador.%n%nO programa baixa mídia dos grupos do Telegram dos quais você já é membro, já organizada no padrão de pastas do Jellyfin.%n%nRecomendamos fechar todos os outros aplicativos antes de continuar.

[Code]
// Sem isto, atualizar por cima de uma instalação em uso falha com "arquivo
// bloqueado" no meio da cópia — um erro que o usuário não tem como resolver.
function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
begin
  Exec('taskkill.exe', '/F /IM {#MyAppExeName}', '', SW_HIDE,
       ewWaitUntilTerminated, ResultCode);
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ConfigDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    // Desinstalar o programa não é pedir para deslogar do Telegram: a sessão
    // e as credenciais só saem se o usuário confirmar explicitamente.
    ConfigDir := ExpandConstant('{localappdata}\{#MyDataDirName}');
    if DirExists(ConfigDir) then
    begin
      if MsgBox('Deseja remover também suas credenciais, a sessão do Telegram e as preferências?'#13#10#13#10
                + 'Escolha "Não" se você pretende reinstalar o programa depois.',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(ConfigDir, True, True, True);
    end;
  end;
end;
