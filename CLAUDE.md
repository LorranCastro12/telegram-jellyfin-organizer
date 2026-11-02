# CLAUDE.md — Contexto do projeto

Este arquivo é lido automaticamente pelo Claude Code. Ele explica o que já
foi construído, as decisões de arquitetura e o que falta fazer.

## O que é este projeto

Cliente desktop (PySide6) para baixar mídia de grupos/canais do Telegram e
organizá-la automaticamente no padrão de pastas do Jellyfin. Foi montado
como um scaffold **funcional** (não é apenas um esqueleto vazio): todos os
módulos foram testados — compilação, importação com Qt em modo offscreen,
parsing de nomes de arquivo com casos reais, e criptografia de credenciais
com round-trip completo. O que **não** foi testado é o fluxo end-to-end
contra a API real do Telegram (exigiria uma conta e número de telefone reais).

## Decisões de arquitetura (e por quê)

- **Telethon**, não Pyrogram/TDLib: puro Python, sem dependência de binário
  nativo, API assíncrona madura, e persistência de sessão em arquivo `.session`
  pronta de fábrica — é o que resolve o requisito de "não pedir login toda vez".
- **Uma `QThread` dedicada rodando seu próprio event loop asyncio**
  (`core/telegram_client.py`), em vez de usar `qasync`. Evita uma dependência
  extra e mantém o padrão de comunicação 100% baseado em sinais Qt
  (thread-safe por natureza). Todo método público da classe `TelegramWorker`
  é síncrono (chamável da GUI) e internamente faz
  `asyncio.run_coroutine_threadsafe(...)`.
- **Credenciais**: chave Fernet no keyring do SO; se não houver backend
  disponível (comum em ambientes Linux sem Secret Service/KWallet), cai para
  arquivo local com permissão 0600. Isso já está coberto em
  `core/credentials.py` e testado em `tests/test_credentials.py`.
- **`guessit`** para extrair título/ano/temporada/episódio do nome do arquivo,
  com um parser de regex simples como fallback caso a biblioteca não esteja
  instalada. O resultado é sempre editável na UI antes de confirmar o
  download — nunca vira pasta/arquivo sem revisão do usuário.
- **A varredura do histórico é paginada por id de *mensagem*, não de
  arquivo** (`core/models.MediaPage`). Uma fatia pode não trazer arquivo
  nenhum — um trecho só de conversa — e ainda assim precisa dizer até onde
  leu. E a checagem incremental do botão "Atualizar" usa `reverse=True` de
  propósito: do mais novo para o mais antigo, bater no limite deixa sem ler o
  intervalo entre o limite e a marca d'água, e avançar a marca depois disso
  torna esse intervalo inalcançável para sempre. Do mais antigo para o mais
  novo a varredura é contígua à marca d'água, então cortar no limite só
  adianta menos terreno. Não troque por `reverse=False` sem ler
  `tests/test_media_pagination.py`.
- **Mídia sem nome de arquivo nunca é descartada.** Vídeo enviado do celular
  "como vídeo" é recodificado pelo Telegram e perde o
  `DocumentAttributeFilename`; `synthesize_file_name` inventa um nome a partir
  da legenda (é onde se escreve o título nesses envios) ou do id da mensagem.
  Descartar em silêncio significava um arquivo que existe no grupo e não
  aparece na lista por mais que o usuário atualize ou reabra o app.
- **Camada `core/` não depende de `QtWidgets`**, só de `QtCore` (para
  `QThread`/`Signal`). Mantém a lógica de negócio testável sem precisar de UI.
- **Empacotamento**: PyInstaller (onedir) nas duas plataformas. No Windows o
  assistente é o **Inno Setup**, nativo e já resolvido. No Linux não existe
  equivalente universal, então o assistente foi escrito em PySide6
  (`packaging/linux/installer_wizard.py`) e vai no **mesmo COLLECT** do
  PyInstaller que o app — é isso que deduplica o Qt e mantém o `.run` em ~90 MB
  em vez de ~180 MB. Detalhes e armadilhas em `packaging/README.md`.
- **`main.py --self-test`**: os scripts de build rodam isto no executável
  recém-gerado e abortam se falhar. Motivo concreto: `guessit`/`babelfish`
  carregam conversores por entry point, o PyInstaller não os enxerga
  estaticamente, e o resultado é um app que abre normal mas faz parsing pior
  em silêncio. Se adicionar dependência com carregamento dinâmico, estenda o
  self-test.
- **Identidade visual**: deliberadamente evitamos o clichê "preto + verde
  neon"/terracota que IAs tendem a gerar por padrão. A paleta foi ancorada no
  próprio domínio do produto (sala de edição/arquivo de cinema): preto
  levemente quente (`#0B0B0C`), latão envelhecido como acento (`#C89B3C`) e um
  teal desaturado para progresso (`#4FA3A0`). O elemento de assinatura visual
  é `ui/widgets/film_progress_delegate.py`: uma barra de progresso com
  perfurações estilo película de 35mm em vez de uma barra genérica.

## Mapa de arquivos

Veja a árvore completa e a explicação de cada camada no `README.md`, seção
"Arquitetura". Resumo rápido:

- `core/telegram_client.py` — única classe que fala com a API do Telegram.
- `core/jellyfin_naming.py` — parsing + geração de caminhos.
- `core/credentials.py` — persistência criptografada.
- `config/settings.py` — preferências não sensíveis (JSON simples).
- `ui/main_window.py` — orquestra os sinais entre core e widgets; é o único
  lugar que "conhece" todos os componentes.
- `ui/widgets/*` — componentes reutilizáveis e desacoplados entre si.

## O que falta / próximos passos sugeridos (por prioridade)

1. **Fila de downloads persistente entre reinícios do app.** Hoje a fila
   vive só em memória (`ui/models.DownloadQueueModel`). Se o app fechar no
   meio de uma sessão, a fila some. Sugestão: um SQLite simples em
   `config/` guardando `DownloadTask`s pendentes, recarregado no startup.
2. **Download acelerado por chunks paralelos de um mesmo arquivo.** Hoje a
   concorrência é entre arquivos diferentes (semáforo em
   `TelegramWorker._async_download`). Para arquivos únicos muito grandes,
   vale investigar dividir em partes e baixar em paralelo (Telethon permite
   múltiplas conexões MTProto simultâneas).
3. **Retry automático com backoff** em `_async_download` para erros
   transitórios de rede (hoje qualquer exceção vai direto para
   `DownloadStatus.ERROR`).
4. **Miniaturas de vídeo** na lista de mídia (`ui/widgets/media_list.py`,
   coluna com `Qt.DecorationRole` já preparada mas sem implementação —
   Telethon expõe thumbnails de vídeo via `message.video.thumbs`).
5. **Empacotamento para macOS.** Windows e Linux já estão prontos (veja
   `packaging/`); falta um `.dmg`/`.app`, que exige um runner macOS no CI e,
   para não esbarrar no Gatekeeper, notarização pela Apple (conta de
   desenvolvedor paga).
6. **Editor de regras de nomenclatura**: hoje o padrão Jellyfin em
   `core/jellyfin_naming.py` é fixo (funções `build_movie_path` /
   `build_episode_path`). Poderia virar um template configurável pela UI.
7. **Detecção de duplicados**: verificar se um arquivo com o mesmo destino já
   existe antes de baixar de novo.
8. **Internacionalização (i18n)**: toda a UI está em português fixo nos
   widgets; extrair strings para um sistema de tradução se for necessário
   suporte a outros idiomas.
9. **Mais testes**: os testes atuais cobrem `core/jellyfin_naming.py`,
   `core/credentials.py`, os modelos/widgets de lista e a lógica de instalação
   do assistente do Linux (`tests/test_linux_installer.py`).
   `core/telegram_client.py` não tem testes automatizados por depender de uma
   conexão real com o Telegram — vale considerar mocks do `TelegramClient` do
   Telethon para testar a lógica de fila/progresso isoladamente.

## Convenções de código

- Python 3.10+, `from __future__ import annotations` em todo módulo novo.
- Type hints em funções públicas.
- Docstrings de módulo explicando o "porquê", não só o "o quê" — siga o
  estilo já usado nos arquivos existentes.
- Textos de interface (labels, botões, mensagens) em português, já que é o
  idioma do usuário-alvo. Nomes de variáveis/funções em inglês (padrão do
  ecossistema Python).
- Nenhum import de `PySide6.QtWidgets` dentro de `core/`.

## Como rodar localmente

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest tests/ -v          # testes automatizados
python main.py            # rodar o app (precisa de display gráfico)
```

Para checar só a compilação/importação sem display gráfico (útil em CI ou
containers sem X11):

```bash
QT_QPA_PLATFORM=offscreen python -c "from ui.main_window import MainWindow; print('ok')"
```
