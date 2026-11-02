# Telegram → Jellyfin Organizer

Aplicativo desktop (Python + PySide6) para navegar nos grupos e canais do
Telegram dos quais você participa, selecionar arquivos de vídeo e baixá-los
já **organizados no padrão de pastas do Jellyfin**, com nome de arquivo
correto para filmes e séries.

Resolve exatamente as limitações do app oficial do Telegram: download nativo
lento e sem controle, tudo numa pasta única, sem renomear.

![status](https://img.shields.io/badge/status-scaffold%20funcional-C89B3C)

## Principais recursos

- **Login único**: você autentica uma vez (via API oficial do Telegram); da
  próxima vez o app reconecta sozinho. Credenciais ficam criptografadas no
  seu computador (chave protegida pelo cofre do sistema operacional).
- **Navegação de grupos/canais**: lista todos os diálogos da sua conta, com
  busca.
- **Grupos fixados**: clique no alfinete à esquerda do nome (ou use o botão
  direito) para mandar os canais que você mais usa para uma seção **Fixados**
  no topo da lista. A escolha é salva e volta igual na próxima vez que você
  abrir o app.
- **Seleção de arquivos** por checkbox, com filtro (vídeos/documentos) e
  busca por nome.
- **Atualizar sem reiniciar** (botão **⟳ Atualizar** ou `F5`): busca o que
  foi enviado ao grupo aberto depois do último carregamento e insere no topo
  da lista, preservando o que já estava carregado e a seleção em andamento.
- **Organizador Jellyfin**: cada arquivo selecionado tem seu nome analisado
  automaticamente (título, ano, temporada, episódio) usando a biblioteca
  `guessit` — o mesmo tipo de motor usado por ferramentas como Sonarr/Radarr.
  Você revisa e ajusta antes de confirmar; nada é decidido "no escuro".
- **Fila de downloads com múltiplas conexões simultâneas** (configurável),
  progresso, velocidade, ETA e cancelamento individual.
- **Painel de estatísticas**: velocidade agregada, downloads ativos,
  concluídos na sessão, total baixado, gráfico de velocidade ao longo do
  tempo.
- **Interface escura elegante**, com identidade visual própria (veja
  `ui/styles/dark_theme.qss`).

## Requisitos

- Uma conta do Telegram
- Um `api_id` e `api_hash` gratuitos, obtidos em
  [my.telegram.org/apps](https://my.telegram.org/apps) (leva menos de 2
  minutos, é o mesmo procedimento usado por qualquer app de terceiros que
  acessa a API do Telegram)

Não é preciso ter Python instalado para usar os instaladores — o interpretador
e todas as bibliotecas vão embutidos.

## Instalação

Baixe o instalador da sua plataforma na página de
[Releases](https://github.com/LorranCastro12/telegram-jellyfin-organizer/releases).

### Windows 10/11

Execute o arquivo `...-windows-x64-Setup.exe` e siga o assistente
(Avançar → Avançar → Instalar). A instalação é na sua pasta de usuário e
**não pede senha de administrador**.

> O Windows pode exibir um aviso do SmartScreen, porque o instalador não tem
> assinatura digital paga. Clique em **Mais informações** → **Executar assim
> mesmo**.

### Linux (qualquer distribuição)

```bash
chmod +x TelegramJellyfinOrganizer-*-linux-amd64.run
./TelegramJellyfinOrganizer-*-linux-amd64.run
```

Abre o mesmo tipo de assistente gráfico: licença, pasta de destino, atalhos e
barra de progresso. Instala em `~/.local/share` e não precisa de `sudo`.

### Debian, Ubuntu e Mint

```bash
sudo apt install ./telegram-jellyfin-organizer_*_amd64.deb
```

### Desinstalar

| Plataforma | Como |
|---|---|
| Windows | Configurações → Aplicativos → Aplicativos Instalados |
| Linux (`.run`) | `~/.local/share/telegram-jellyfin-organizer/uninstall.sh` |
| Linux (`.deb`) | `sudo apt remove telegram-jellyfin-organizer` |

Desinstalar **não** apaga seu login nem suas preferências (ficam em
`~/.config/telegram-jellyfin-organizer`, ou em `%LOCALAPPDATA%` no Windows),
para que reinstalar não exija autenticar de novo.

## Rodando a partir do código-fonte

Requer Python 3.10+:

```bash
git clone https://github.com/LorranCastro12/telegram-jellyfin-organizer.git
cd telegram-jellyfin-organizer
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Para gerar os instaladores você mesmo, veja
[`packaging/README.md`](packaging/README.md).

## Primeira execução

1. Informe `api_id`, `api_hash` e seu telefone (com DDI, ex.: `+55 11 9...`).
2. Digite o código de verificação que o Telegram te enviar.
3. Se sua conta tiver verificação em duas etapas, informe a senha.
4. Pronto — nas próximas vezes o app abre direto na tela principal.

Depois, em **Configurações**, aponte as pastas de **Filmes**, **Séries**,
**Desenhos**, **Animes** e **Documentários** para as raízes das bibliotecas
que você já configurou no Jellyfin. Só Filmes e Séries são necessárias —
deixe em branco as bibliotecas que você não usa.

## Fluxo de uso

1. Escolha um grupo/canal na coluna da esquerda. Nos que você usa sempre,
   clique no alfinete para fixá-los no topo e não precisar buscar de novo.
2. Marque os arquivos que quer baixar na lista central. Se alguém enviar algo
   novo enquanto você navega, clique em **⟳ Atualizar** (ou `F5`) — não
   precisa reabrir o grupo nem reiniciar o app.
3. No painel "Revise os metadados", confira/ajuste título, ano, temporada e
   episódio de cada item — o caminho final já aparece em tempo real.
4. Clique em **Adicionar à fila de downloads**.
5. Acompanhe o progresso na aba **Downloads** e o desempenho agregado em
   **Estatísticas**.

## Padrão de pastas gerado (Jellyfin)

```
Filmes/
  Nosferatu (1922)/
    Nosferatu (1922).mkv

Series/
  Sherlock Holmes/
    Season 01/
      Sherlock Holmes S01E03 - A Queda.mkv

Desenhos/            (mesmo layout de Series)
  Tom e Jerry/
    Season 01/
      Tom e Jerry S01E05.mkv

Animes/              (mesmo layout de Series)
Documentarios/       (mesmo layout de Series)
```

Desenhos, animes e documentários são bibliotecas separadas no Jellyfin, mas
seguem exatamente a mesma organização por temporada das séries — a escolha
do tipo no painel "Revise os metadados" define apenas em qual biblioteca o
arquivo cai.

Essa é a convenção recomendada na documentação oficial do Jellyfin para
detecção automática de metadados (pôster, sinopse, ano etc.). Veja mais em:
https://jellyfin.org/docs/general/server/media/movies e
https://jellyfin.org/docs/general/server/media/shows

## Arquitetura

```
main.py                    Ponto de entrada (e `--self-test` do bundle)
version.py                 Versão/identidade do produto (app + instaladores)
core/
  telegram_client.py        Único lugar que fala com a API do Telegram
                             (Telethon), rodando em thread própria com loop
                             asyncio isolado. Expõe apenas sinais Qt.
  credentials.py            Armazenamento criptografado (Fernet + keyring)
  jellyfin_naming.py         Parsing de nome de arquivo (guessit) + geração
                             de caminhos no padrão Jellyfin
  models.py                  Dataclasses compartilhadas (sem dependência de UI)
config/
  settings.py                 Preferências não sensíveis (pastas, concorrência,
                               grupos fixados)
ui/
  main_window.py              Orquestra os sinais entre core e widgets
  login_dialog.py / settings_dialog.py
  widgets/                    Componentes reutilizáveis (lista de grupos,
                               lista de mídia, painel de organização, fila de
                               downloads, estatísticas, delegate de progresso)
  models.py                    QAbstractTableModel para as tabelas Qt
  styles/dark_theme.qss        Tema visual
utils/
  logger.py / formatters.py
  resources.py                 Resolve caminhos de recurso rodando do código
                               ou de dentro do bundle do PyInstaller
packaging/                    Geração dos instaladores — veja
                               packaging/README.md
tests/                        Testes automatizados (pytest) do core, dos
                               modelos/widgets da lista de mídia e da lógica
                               de instalação do assistente do Linux
```

A camada `core/` não importa nada de `PySide6.QtWidgets`, só `QtCore`
(para `QThread`/`Signal`). Isso mantém a lógica de negócio testável sem
precisar abrir janelas — veja `tests/`.

## Testes

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

Os testes que tocam a interface (lista de grupos) rodam com o Qt em modo
`offscreen` — não abrem janela e funcionam em container sem X11.

## Aviso legal

Este software usa a API oficial do Telegram (a mesma usada por qualquer
cliente de terceiros) para baixar arquivos de grupos dos quais **você já é
membro**. Use-o apenas para conteúdo que você tem o direito de acessar e
armazenar (o próprio autor do pedido descreve o grupo como de domínio
público). Respeite os Termos de Serviço do Telegram e a legislação de
direitos autorais aplicável.

## Próximos passos sugeridos

Veja `CLAUDE.md` para o contexto completo de arquitetura e uma lista de
melhorias priorizadas para continuar o desenvolvimento no Claude Code.
