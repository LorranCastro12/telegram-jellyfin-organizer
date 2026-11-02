"""Testes da varredura do histórico de um grupo e da extração de mídia.

Cobrem os três jeitos de um arquivo que existe no grupo nunca chegar à lista
— todos relatados em uso real como "não aparecem todos os filmes":

1. **Mídia sem nome.** Vídeo enviado do celular "como vídeo" é recodificado
   pelo Telegram e perde o `DocumentAttributeFilename`. A extração descartava
   essa mensagem em silêncio, e nada nunca a trazia de volta: não há cache,
   o arquivo simplesmente nunca virava um `MediaFile`.
2. **Paginação travada.** O próximo `offset_id` saía do último *arquivo* da
   fatia. Um trecho só de conversa não tem arquivo, o offset não andava, e
   "Carregar mais" repetia a mesma consulta para sempre.
3. **Buraco na checagem incremental.** Varrendo do mais novo para o mais
   antigo, bater no limite deixava sem ler o intervalo entre o limite e a
   marca d'água; avançar a marca depois disso tornava esse intervalo
   inalcançável — o "Atualizar" parava de trazer novidade e continuava assim
   depois de reabrir o app.

Nada aqui fala com o Telegram: `FakeClient` reproduz a semântica do
`iter_messages` do Telethon, que é o contrato de que a correção depende.
"""

from __future__ import annotations

import asyncio
import datetime
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from core.models import MediaKind, MediaPage
from core.telegram_client import TelegramWorker, synthesize_file_name
from ui.main_window import MainWindow
from ui.widgets.media_list import MediaListWidget


# ----------------------------------------------------------------------
# Dublês
# ----------------------------------------------------------------------
def texto(message_id: int) -> SimpleNamespace:
    """Mensagem de conversa: nenhuma mídia."""
    return SimpleNamespace(
        id=message_id, media=None, document=None, video=None, message="oi",
        date=datetime.datetime(2026, 11, 2),
    )


def video(message_id: int, file_name: str | None = None, *, legenda: str = "",
          mime: str = "video/mp4") -> SimpleNamespace:
    attrs = [SimpleNamespace(duration=7200, w=1920, h=1080)]
    if file_name:
        attrs.append(SimpleNamespace(file_name=file_name))
    document = SimpleNamespace(size=1024, mime_type=mime, attributes=attrs)
    return SimpleNamespace(
        id=message_id, media=object(), document=document, video=attrs[0],
        message=legenda, date=datetime.datetime(2026, 11, 2),
    )


def foto(message_id: int) -> SimpleNamespace:
    """Mídia sem documento: continua fora do escopo do app."""
    return SimpleNamespace(
        id=message_id, media=object(), document=None, video=None, message="",
        date=datetime.datetime(2026, 11, 2),
    )


class FakeClient:
    """Imita o `iter_messages` do Telethon no que a correção depende.

    Por padrão a iteração vai do mais novo para o mais antigo e `offset_id` é
    exclusivo. Com `reverse=True` a ordem inverte e `min_id` passa a valer
    como `offset_id` — é o que o Telethon faz em `client/messages.py`
    (`offset_id = max(offset_id, min_id)`, depois `offset_id += 1`) e está na
    docstring de `iter_messages`. Toda a ausência de buraco na checagem
    incremental se apoia nisso.
    """

    def __init__(self, messages):
        self.messages = sorted(messages, key=lambda m: m.id)
        self.calls: list[dict] = []

    async def get_entity(self, group_id):
        return f"entity:{group_id}"

    def iter_messages(self, entity, limit=None, offset_id=0, min_id=0, reverse=False):
        self.calls.append(
            {"limit": limit, "offset_id": offset_id, "min_id": min_id, "reverse": reverse}
        )
        selected = [m for m in self.messages if m.id > min_id]
        if offset_id and not reverse:
            selected = [m for m in selected if m.id < offset_id]
        if not reverse:
            selected = list(reversed(selected))
        if limit is not None:
            selected = selected[:limit]

        async def gerador():
            for message in selected:
                yield message

        return gerador()


@pytest.fixture
def worker(qt_app, tmp_path):
    """TelegramWorker sem thread e sem rede: só o `client` é substituído.

    `__init__` não cria o TelegramClient nem inicia a QThread (isso acontece
    em `run()`), então instanciar aqui é barato e não abre conexão nenhuma.
    """
    w = TelegramWorker(tmp_path / "sessao")
    yield w
    w.deleteLater()
    qt_app.processEvents()


def varrer(worker, coro_factory):
    """Roda uma corrotina do worker e devolve a MediaPage que ela emitiu."""
    recebidas: list[MediaPage] = []
    worker.media_ready.connect(recebidas.append)
    worker.new_media_ready.connect(recebidas.append)
    asyncio.run(coro_factory())
    assert recebidas, "a corrotina terminou sem emitir nenhuma MediaPage"
    return recebidas[-1]


class FakeStatusBar:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def showMessage(self, text: str, timeout: int = 0) -> None:
        self.messages.append(text)


class JanelaStub:
    """Só os atributos que os handlers de mídia da MainWindow tocam.

    Construir uma MainWindow de verdade levanta uma QThread que tenta falar
    com o Telegram. O que se testa aqui é a aritmética dos ponteiros de
    paginação, então os métodos são chamados desacoplados da janela.
    """

    def __init__(self, group_id: int, widget: MediaListWidget) -> None:
        self.current_group = SimpleNamespace(id=group_id, title="Filmes")
        self.media_list_widget = widget
        self._load_more_offset = 0
        self._newest_message_id = 0
        self._status = FakeStatusBar()

    def statusBar(self) -> FakeStatusBar:
        return self._status


@pytest.fixture
def janela(qt_app):
    criados: list[MediaListWidget] = []

    def factory(group_id: int = -100123) -> JanelaStub:
        widget = MediaListWidget()
        criados.append(widget)
        return JanelaStub(group_id, widget)

    yield factory

    for widget in criados:
        widget.setParent(None)
        widget.deleteLater()
    qt_app.processEvents()


def exibidos(stub: JanelaStub) -> list[str]:
    model = stub.media_list_widget.model
    return [model.file_at(row).file_name for row in range(model.rowCount())]


# ----------------------------------------------------------------------
# Extração: nenhuma mídia de vídeo pode ser descartada em silêncio
# ----------------------------------------------------------------------
def test_video_sem_nome_de_arquivo_nao_e_descartado():
    # O caso que o usuário reportou: o filme está no grupo, a lista nunca o
    # mostra, e reabrir o app não muda nada.
    enviado_do_celular = video(102, file_name=None, legenda="Duna (2021)")

    extraido = TelegramWorker._extract_media_file(enviado_do_celular, group_id=-100123)

    assert extraido is not None, "vídeo sem nome não pode ser descartado"
    assert extraido.file_name == "Duna (2021).mp4"
    assert extraido.kind == MediaKind.VIDEO


def test_nome_de_arquivo_real_tem_prioridade_sobre_a_legenda():
    com_nome = video(101, file_name="Duna.2021.1080p.mkv", legenda="qualquer coisa")

    extraido = TelegramWorker._extract_media_file(com_nome, group_id=1)

    assert extraido.file_name == "Duna.2021.1080p.mkv"


def test_sem_nome_e_sem_legenda_usa_o_id_da_mensagem():
    extraido = TelegramWorker._extract_media_file(video(777), group_id=1)

    assert extraido.file_name == "video_777.mp4"


def test_extensao_sintetizada_cobre_mkv():
    # `mimetypes` do sistema não conhece video/x-matroska em várias distros;
    # sem a tabela explícita o arquivo sairia como `.bin`.
    extraido = TelegramWorker._extract_media_file(
        video(5, legenda="Interstellar", mime="video/x-matroska"), group_id=1
    )

    assert extraido.file_name == "Interstellar.mkv"


def test_legenda_nao_pode_virar_travessia_de_caminho():
    nome = synthesize_file_name(
        video(9, legenda="../../.ssh/authorized_keys"), "video/mp4", MediaKind.VIDEO
    )

    assert "/" not in nome and "\\" not in nome
    assert not nome.startswith(".")


def test_legenda_que_ja_termina_na_extensao_nao_duplica():
    nome = synthesize_file_name(
        video(9, legenda="Duna.mp4"), "video/mp4", MediaKind.VIDEO
    )

    assert nome == "Duna.mp4"


def test_so_a_primeira_linha_da_legenda_vira_nome():
    nome = synthesize_file_name(
        video(9, legenda="Duna (2021)\n\nDublado — 1080p\n#filmes"),
        "video/mp4",
        MediaKind.VIDEO,
    )

    assert nome == "Duna (2021).mp4"


def test_foto_continua_fora_do_escopo():
    # Inventar nome para mídia sem documento seria encher a lista de coisa que
    # o app não organiza.
    assert TelegramWorker._extract_media_file(foto(50), group_id=1) is None


def test_mensagem_sem_midia_e_ignorada():
    assert TelegramWorker._extract_media_file(texto(50), group_id=1) is None


# ----------------------------------------------------------------------
# Listagem: o ponteiro da paginação é de mensagem, não de arquivo
# ----------------------------------------------------------------------
def test_fatia_so_de_conversa_ainda_move_o_ponteiro(worker):
    # 100 mensagens de texto seguidas: a fatia não traz arquivo nenhum, mas
    # precisa dizer até onde leu, senão o "Carregar mais" não sai do lugar.
    worker.client = FakeClient([texto(i) for i in range(401, 501)])

    page = varrer(worker, lambda: worker._async_list_media(-100123, limit=100, offset_id=0))

    assert page.files == []
    assert page.oldest_message_id == 401
    assert page.newest_message_id == 500
    assert page.hit_limit is True


def test_fatia_incompleta_nao_promete_mais_historico(worker):
    worker.client = FakeClient([video(10, "a.mkv"), texto(11), video(12, "b.mkv")])

    page = varrer(worker, lambda: worker._async_list_media(-100123, limit=100, offset_id=0))

    assert [f.file_name for f in page.files] == ["b.mkv", "a.mkv"]
    assert page.hit_limit is False
    assert page.oldest_message_id == 10


def test_a_fatia_carrega_o_grupo_de_origem(worker):
    worker.client = FakeClient([texto(1)])

    page = varrer(worker, lambda: worker._async_list_media(-100777, limit=100, offset_id=0))

    assert page.group_id == -100777


def test_paginacao_atravessa_um_trecho_de_conversa(worker, janela):
    """O beco sem saída, de ponta a ponta.

    Arquivo antigo (id 1), 120 mensagens de conversa em cima dele e um arquivo
    recente (id 200). Com páginas de 100 mensagens, a conversa ocupa mais de
    uma página inteira: antes, a segunda página vinha vazia, o offset ficava
    parado no id 200 e o arquivo de id 1 era inalcançável por mais que se
    clicasse.
    """
    mensagens = [video(1, "antigo.mkv")] + [texto(i) for i in range(50, 170)] + [video(200, "novo.mkv")]
    worker.client = FakeClient(mensagens)
    stub = janela(-100123)

    for _ in range(5):
        offset = stub._load_more_offset
        page = varrer(
            worker,
            lambda: worker._async_list_media(-100123, limit=100, offset_id=offset),
        )
        MainWindow._on_media_ready(stub, page)
        if not page.hit_limit:
            break

    assert sorted(exibidos(stub)) == ["antigo.mkv", "novo.mkv"]
    assert not stub.media_list_widget.load_more_btn.isEnabled()


def test_fatia_de_outro_grupo_nao_mexe_nos_ponteiros(janela):
    stub = janela(-100123)
    MainWindow._on_media_ready(stub, MediaPage(group_id=-100123, files=[], oldest_message_id=900,
                                               newest_message_id=1000))

    atrasada = MediaPage(group_id=-100999, files=[], oldest_message_id=5, newest_message_id=7)
    MainWindow._on_media_ready(stub, atrasada)

    assert stub._load_more_offset == 900
    assert stub._newest_message_id == 1000


# ----------------------------------------------------------------------
# Checagem incremental: contígua à marca d'água, sem buraco
# ----------------------------------------------------------------------
def test_checagem_incremental_varre_do_mais_antigo_para_o_mais_novo(worker):
    worker.client = FakeClient([video(1001, "a.mkv"), video(1002, "b.mkv")])

    varrer(worker, lambda: worker._async_check_new_media(-100123, 1000, limit=2000))

    chamada = worker.client.calls[-1]
    assert chamada["reverse"] is True, "sem reverse=True o corte no limite deixa buraco"
    assert chamada["min_id"] == 1000


def test_marca_dagua_para_onde_a_leitura_chegou_e_nao_no_topo(worker):
    # 500 mensagens novas, limite de 200: a varredura cobre 1001..1200 e a
    # marca d'água tem de parar em 1200. Ir até 1500 seria pular 300
    # mensagens que ninguém leu.
    worker.client = FakeClient([texto(i) for i in range(1001, 1501)])

    page = varrer(worker, lambda: worker._async_check_new_media(-100123, 1000, limit=200))

    assert page.hit_limit is True
    assert page.oldest_message_id == 1001
    assert page.newest_message_id == 1200


def test_atualizar_repetido_nao_deixa_arquivo_para_tras(worker, janela):
    """A regressão central do "parou de aparecer as atualizações".

    Um arquivo logo acima da marca d'água (1005) e outro bem no topo (1495),
    com 500 mensagens novas e orçamento de 200. Varrendo do mais novo para o
    mais antigo, a primeira checagem acharia só o 1495 e levaria a marca para
    lá — o 1005 ficaria num intervalo nunca lido e inalcançável. Contígua, a
    varredura chega aos dois.
    """
    mensagens = [texto(i) for i in range(1001, 1501)]
    mensagens += [video(1005, "primeiro.mkv"), video(1495, "ultimo.mkv")]
    worker.client = FakeClient(mensagens)

    stub = janela(-100123)
    stub._newest_message_id = 1000

    for _ in range(10):
        marca = stub._newest_message_id
        page = varrer(
            worker,
            lambda: worker._async_check_new_media(-100123, marca, limit=200),
        )
        MainWindow._on_new_media_ready(stub, page)
        assert stub._newest_message_id > marca, "a marca d'água tem de avançar sempre"
        if not page.hit_limit:
            break

    assert sorted(exibidos(stub)) == ["primeiro.mkv", "ultimo.mkv"]


def test_marca_dagua_avanca_mesmo_sem_arquivo_novo(janela):
    # Trecho de pura conversa: se a marca não andasse, a checagem seguinte
    # releria as mesmas mensagens a cada clique em Atualizar.
    stub = janela(-100123)
    stub._newest_message_id = 1000

    MainWindow._on_new_media_ready(
        stub, MediaPage(group_id=-100123, files=[], oldest_message_id=1001, newest_message_id=1200)
    )

    assert stub._newest_message_id == 1200


def test_atualizar_poe_o_mais_recente_no_topo(janela):
    # A varredura devolve em ordem crescente de id; a lista mostra ao
    # contrário, com o mais novo primeiro.
    stub = janela(-100123)
    page = MediaPage(
        group_id=-100123,
        files=[
            TelegramWorker._extract_media_file(video(1001, "antigo.mkv"), -100123),
            TelegramWorker._extract_media_file(video(1002, "recente.mkv"), -100123),
        ],
        oldest_message_id=1001,
        newest_message_id=1002,
    )

    MainWindow._on_new_media_ready(stub, page)

    assert exibidos(stub) == ["recente.mkv", "antigo.mkv"]


def test_checagem_de_outro_grupo_nao_entra_na_lista(janela):
    stub = janela(-100123)
    stub._newest_message_id = 1000

    MainWindow._on_new_media_ready(
        stub,
        MediaPage(group_id=-100999, files=[], oldest_message_id=1, newest_message_id=9),
    )

    assert stub._newest_message_id == 1000


# ----------------------------------------------------------------------
# Widget: o fim do histórico fica visível
# ----------------------------------------------------------------------
def test_botao_carregar_mais_desliga_no_fim_do_historico(qt_app):
    widget = MediaListWidget()
    try:
        widget.set_load_more_enabled(False)
        assert not widget.load_more_btn.isEnabled()
        assert widget.load_more_btn.text() == "Todos os arquivos carregados"

        widget.set_load_more_enabled(True)
        assert widget.load_more_btn.isEnabled()
        assert widget.load_more_btn.text() == "Carregar mais arquivos..."
    finally:
        widget.setParent(None)
        widget.deleteLater()
        qt_app.processEvents()
