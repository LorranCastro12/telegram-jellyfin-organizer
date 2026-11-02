<#
.SYNOPSIS
    Gera o instalador do Windows (assistente "Avançar → Avançar → Instalar").

.DESCRIPTION
    Executa, em ordem: geração dos ícones, empacotamento com PyInstaller,
    verificação do bundle (`--self-test`) e compilação do instalador com o
    Inno Setup.

    O self-test no meio do caminho não é zelo excessivo: o PyInstaller produz
    um .exe que abre normalmente mesmo quando os arquivos de dados do guessit
    ficaram de fora, e o sintoma só aparece quando o usuário final tenta
    organizar um arquivo. Melhor quebrar o build.

.PARAMETER SkipInstaller
    Só gera o bundle do PyInstaller, sem compilar o .exe do instalador.

.EXAMPLE
    .\packaging\windows\build.ps1
#>
[CmdletBinding()]
param(
    [switch]$SkipInstaller
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Resolve-Path (Join-Path $ScriptDir '..\..')
Push-Location $Root

try {
    # Prefere o venv do projeto, se existir.
    $Python = 'python'
    $VenvPython = Join-Path $Root '.venv\Scripts\python.exe'
    if (Test-Path $VenvPython) { $Python = $VenvPython }

    $Version = (& $Python -c 'import version; print(version.__version__)').Trim()
    $AppName = (& $Python -c 'import version; print(version.APP_NAME)').Trim()
    $BundleDir = Join-Path $Root 'dist\TelegramJellyfinOrganizer'
    $AppExe = Join-Path $BundleDir 'TelegramJellyfinOrganizer.exe'

    Write-Host "==> Construindo $AppName $Version (windows-x64)" -ForegroundColor Cyan

    Write-Host '==> Gerando assets'
    & $Python (Join-Path $Root 'packaging\assets\make_icon.py')
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao gerar os assets.' }

    Write-Host '==> Empacotando com PyInstaller'
    if (Test-Path $BundleDir) { Remove-Item -Recurse -Force $BundleDir }
    if (Test-Path (Join-Path $Root 'build')) { Remove-Item -Recurse -Force (Join-Path $Root 'build') }
    & $Python -m PyInstaller (Join-Path $Root 'packaging\app.spec') --noconfirm `
        --distpath (Join-Path $Root 'dist') --workpath (Join-Path $Root 'build')
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller falhou.' }
    if (-not (Test-Path $AppExe)) { throw "Executável não encontrado em $AppExe" }

    Write-Host '==> Verificando o bundle (self-test)'
    & $AppExe --self-test
    if ($LASTEXITCODE -ne 0) {
        throw 'O self-test do bundle falhou — o instalador não será gerado.'
    }

    if ($SkipInstaller) {
        Write-Host '==> Instalador pulado (-SkipInstaller)' -ForegroundColor Yellow
        exit 0
    }

    # Inno Setup não entra no PATH por padrão em nenhum dos instaladores
    # oficiais, então procuramos nos caminhos conhecidos antes de desistir.
    Write-Host '==> Localizando o Inno Setup'
    $ISCC = $null
    $Candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    )
    foreach ($candidate in $Candidates) {
        if ($candidate -and (Test-Path $candidate)) { $ISCC = $candidate; break }
    }
    if (-not $ISCC) {
        $OnPath = Get-Command 'ISCC.exe' -ErrorAction SilentlyContinue
        if ($OnPath) { $ISCC = $OnPath.Source }
    }
    if (-not $ISCC) {
        throw @'
Inno Setup 6 não encontrado. Instale com um dos comandos abaixo e rode de novo:
    winget install --id JRSoftware.InnoSetup -e
    choco install innosetup -y
Ou baixe em https://jrsoftware.org/isdl.php
'@
    }
    Write-Host "    usando $ISCC"

    Write-Host '==> Compilando o instalador'
    & $ISCC "/DMyAppVersion=$Version" (Join-Path $Root 'packaging\windows\installer.iss')
    if ($LASTEXITCODE -ne 0) { throw 'Inno Setup falhou ao compilar o instalador.' }

    $Setup = Join-Path $Root "dist\TelegramJellyfinOrganizer-$Version-windows-x64-Setup.exe"
    if (-not (Test-Path $Setup)) { throw "Instalador não encontrado em $Setup" }
    $SizeMB = [math]::Round((Get-Item $Setup).Length / 1MB, 1)
    Write-Host "    $Setup ($SizeMB MB)" -ForegroundColor Green
    Write-Host '==> Pronto.' -ForegroundColor Cyan
}
finally {
    Pop-Location
}
