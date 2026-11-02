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
; Mesmo GUID do AppId, sem as chaves. Serve para achar a instalação anterior
; no registro: a chave de desinstalação do Inno é "<AppId>_is1". A diretiva
; #if no fim do [Setup] falha o build se os dois divergirem — divergência que
; não daria erro nenhum, só faria o instalador não encontrar a versão velha e
; deixá-la para trás no disco.
#define MyAppGuid "7A80F824-E8A9-4C62-AC6A-97EEE24850CD"
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

#if Pos(MyAppGuid, SetupSetting("AppId")) == 0
  #error MyAppGuid nao corresponde ao AppId: o instalador nao encontraria a versao anterior.
#endif

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
const
  PreviousUninstallKey =
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\{{#MyAppGuid}}_is1';

// Sem isto, atualizar por cima de uma instalação em uso falha com "arquivo
// bloqueado" no meio da cópia — um erro que o usuário não tem como resolver.
procedure CloseRunningApp();
var
  ResultCode: Integer;
begin
  Exec('taskkill.exe', '/F /IM {#MyAppExeName}', '', SW_HIDE,
       ewWaitUntilTerminated, ResultCode);
end;

function PreviousUninstaller(): String;
var
  Value: String;
begin
  Result := '';
  // Instalação "só para mim" grava em HKCU; "para todos os usuários", em
  // HKLM — e um instalador de 32 bits num Windows 64 bits enxerga a chave na
  // view de 32 bits. Procurar nos três cobre quem atualiza por cima de uma
  // instalação feita de outro jeito.
  if RegQueryStringValue(HKCU, PreviousUninstallKey, 'UninstallString', Value) then
    Result := Value
  else if RegQueryStringValue(HKLM, PreviousUninstallKey, 'UninstallString', Value) then
    Result := Value
  else if RegQueryStringValue(HKLM32, PreviousUninstallKey, 'UninstallString', Value) then
    Result := Value;
end;

function InitializeSetup(): Boolean;
begin
  CloseRunningApp();
  Result := True;
end;

// Remove a versão anterior antes de copiar a nova. Fica em PrepareToInstall,
// e não em InitializeSetup, de propósito: aqui o usuário já confirmou a
// instalação. Desinstalar antes disso apagaria a versão que ele tem
// funcionando caso ele desistisse no meio do assistente.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Uninstaller, Params: String;
  ResultCode: Integer;
begin
  Result := '';

  Uninstaller := RemoveQuotes(PreviousUninstaller());
  if Uninstaller = '' then
    exit;
  if not FileExists(Uninstaller) then
    exit;  // entrada órfã no registro: não há nada para remover

  CloseRunningApp();

  // `_?=` precisa ser o último parâmetro, e é ele que faz a diferença aqui:
  // sem ele o desinstalador se copia para o %TEMP% e devolve o controle na
  // hora, de modo que ewWaitUntilTerminated não espera nada — a remoção da
  // versão antiga aconteceria *durante* ou *depois* da cópia dos arquivos
  // novos, apagando parte da instalação recém-feita. Com `_?=` ele roda no
  // lugar e a espera é real.
  //
  // /SUPPRESSMSGBOXES faz todo MsgBox devolver o botão padrão. A pergunta
  // sobre apagar credenciais, em CurUninstallStepChanged, é MB_DEFBUTTON2
  // sobre um MB_YESNO — ou seja, padrão "Não". É isso que garante que
  // atualizar não desloga ninguém do Telegram: NÃO mude esse botão padrão
  // sem reler este comentário.
  Params := '/SILENT /NORESTART /SUPPRESSMSGBOXES _?=' + ExtractFileDir(Uninstaller);

  if not Exec(Uninstaller, Params, '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    // Sobrescrever é pior que remover antes, mas é muito melhor que abortar a
    // instalação: o usuário fica com a versão nova funcionando.
    Log('Falha ao executar o desinstalador anterior: ' + Uninstaller);
    exit;
  end;

  // Rodando com `_?=`, o desinstalador não consegue apagar a si mesmo. O
  // resto da pasta já foi; limpar o que sobrou evita deixar um unins000.*
  // de uma versão antiga para trás quando a nova vai para outra pasta.
  DelTree(ExtractFileDir(Uninstaller) + '\unins*', False, True, False);
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
