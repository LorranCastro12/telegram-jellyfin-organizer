# Empacotamento

Como os instaladores são gerados, e por que cada plataforma usa uma
abordagem diferente.

## O que sai daqui

| Arquivo | Plataforma | O que é |
|---|---|---|
| `TelegramJellyfinOrganizer-<versão>-windows-x64-Setup.exe` | Windows 10/11 | Assistente nativo (Inno Setup) |
| `TelegramJellyfinOrganizer-<versão>-linux-<arch>.run` | Qualquer distro | Assistente gráfico auto-extraível |
| `telegram-jellyfin-organizer_<versão>_<arch>.deb` | Debian/Ubuntu/Mint | Pacote para `apt` |

Nenhum deles exige Python instalado na máquina do usuário — o interpretador,
o Qt e todas as bibliotecas vão embutidos.

## Por que dois caminhos diferentes

No **Windows** o formato com assistente é nativo e esperado, e o Inno Setup
já entrega de graça o que daria muito trabalho reimplementar: entrada em
"Aplicativos Instalados", desinstalador, atualização por cima da versão
anterior e atalhos no Menu Iniciar.

No **Linux** não existe um equivalente universal. `.deb` só cobre a família
Debian, AppImage não instala nada (só executa) e Flatpak exige repositório.
Para que o usuário final tenha a mesma experiência de "Próximo → Próximo",
o assistente foi escrito em `installer_wizard.py` com o PySide6 que o projeto
já usa, e empacotado junto com o app.

O detalhe que faz isso valer a pena: app e assistente são gerados no **mesmo**
`COLLECT` do PyInstaller (veja `app.spec`), então as bibliotecas do Qt são
deduplicadas — um Qt em vez de dois. Sem isso o `.run` teria o dobro do
tamanho.

## Estrutura

```
packaging/
  app.spec                  Spec do PyInstaller (os dois executáveis)
  assets/
    make_icon.py            Gera ícone e imagens do wizard a partir do código
    icon.ico / icon_*.png   Ícones (gerados)
    wizard_*.bmp            Laterais do assistente do Windows (gerados)
  linux/
    build.sh                Orquestra: assets → PyInstaller → .run → .deb
    installer_wizard.py     O assistente gráfico (QWizard)
    run_stub.sh             Cabeçalho shell do .run auto-extraível
  windows/
    build.ps1               Orquestra: assets → PyInstaller → self-test → Inno
    installer.iss           Script do Inno Setup
```

## Como construir

### Linux

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-build.txt
./packaging/linux/build.sh
```

Saída em `dist/`. Use `--skip-deb` para pular o pacote Debian.

### Windows

Precisa do [Inno Setup 6](https://jrsoftware.org/isdl.php):

```powershell
winget install --id JRSoftware.InnoSetup -e

python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-build.txt
.\packaging\windows\build.ps1
```

### Pelo GitHub Actions

`.github/workflows/build-installers.yml` constrói os dois. Dispare manualmente
pela aba **Actions** para baixar os artefatos, ou empurre uma tag `v*` para
gerar um Release com os instaladores anexados:

```bash
git tag v1.0.0 && git push origin v1.0.0
```

É por aqui que o instalador do Windows é produzido quando você só tem uma
máquina Linux — o Inno Setup não roda fora do Windows.

## O self-test (não remova)

Os dois scripts de build rodam `--self-test` no executável recém-gerado antes
de empacotá-lo, e abortam se ele falhar.

Isso existe por um modo de falha concreto do PyInstaller: `guessit` e
`babelfish` carregam regras e conversores de idioma por *entry point*, que a
análise estática não enxerga. O resultado é um app que **abre normalmente**,
mas cujo `parse_filename` cai no fallback de regex sem avisar ninguém — o
usuário só percebe que os metadados ficaram piores. Foi exatamente o que
aconteceu no primeiro build deste projeto (`ModuleNotFoundError:
babelfish.converters.alpha2`), e a correção está nos `collect_submodules` de
`app.spec`.

## Notas de manutenção

- **Versão** mora em `version.py`, na raiz. Mude lá e os três artefatos
  acompanham.
- **O `AppId` do Inno Setup (`installer.iss`) nunca muda.** É o que faz o
  Windows reconhecer uma nova versão como atualização em vez de um segundo
  programa.
- **O `.run` é construído na glibc mais antiga disponível** (Ubuntu 22.04 no
  CI). Binário compilado em glibc nova não roda em distro velha; o contrário
  funciona.
- **Os dados do usuário nunca ficam na pasta de instalação** — sessão do
  Telegram, credenciais e preferências vão para `platformdirs`. Por isso
  desinstalar não desloga, e atualizar não perde nada.
- As dependências de Qt no `.deb` entram como `Recommends`, não `Depends`:
  os nomes desses pacotes mudaram entre releases do Ubuntu (`libglib2.0-0`
  virou `libglib2.0-0t64` no 24.04) e como `Depends` o pacote ficaria
  não-instalável em metade das distros.

## Assinatura digital

Nenhum dos instaladores é assinado. No Windows isso faz o SmartScreen exibir
um aviso na primeira execução ("Mais informações" → "Executar assim mesmo").
Remover o aviso exige um certificado de code signing pago (EV, algumas
centenas de dólares por ano) — não vale a pena para uso pessoal, mas é bom
saber o motivo do aviso antes de concluir que o build deu errado.
