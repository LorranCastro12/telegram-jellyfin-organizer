"""Integração com o Telegram via Telethon, rodando em uma QThread dedicada.

Por que uma thread com loop asyncio próprio?
- Telethon é assíncrono (asyncio) e a interface é PySide6 (event loop do Qt).
- Em vez de misturar os dois loops (o que exigiria uma dependência extra como
  `qasync`), rodamos o Telethon inteiro em uma QThread separada que possui seu
  próprio `asyncio` event loop. A GUI nunca chama corrotinas diretamente: ela
  chama métodos "de fachada" (síncronos) que fazem
  `asyncio.run_coroutine_threadsafe(...)`, e o resultado/progresso volta para
  a GUI através de sinais Qt (thread-safe por natureza).

Esse é o único lugar do projeto que conhece a API do Telethon. Se no futuro
o Claude Code quiser trocar de biblioteca (ex.: Pyrogram) ou usar TDLib para
downloads mais rápidos, é só reescrever esta classe mantendo os mesmos sinais.
"""

from __future__ import annotations

import asyncio
import logging
import mimetypes
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import QThread, Signal

from core import fast_download
from core.jellyfin_naming import sanitize_filename
from core.models import (
    DownloadStatus,
    DownloadTask,
    MediaFile,
    MediaKind,
    MediaPage,
    TelegramGroup,
)

logger = logging.getLogger(__name__)

# Extensões por mime type, para mídia que chega sem nome de arquivo. A tabela
# explícita vem antes de `mimetypes.guess_extension` porque o mapa do sistema
# não conhece justamente os tipos mais comuns em vídeo do Telegram — em várias
# distros `video/x-matroska` não está registrado — e, para outros, devolve
# variantes inesperadas (`.jpe` para JPEG, por exemplo).
_MIME_EXTENSIONS = {
    "video/mp4": ".mp4",
    "video/x-matroska": ".mkv",
    "video/quicktime": ".mov",
    "video/x-msvideo": ".avi",
    "video/webm": ".webm",
    "video/mpeg": ".mpg",
    "video/x-ms-wmv": ".wmv",
    "video/3gpp": ".3gp",
}


def _extension_for(mime_type: str) -> str:
    """Extensão provável para um mime type, com `.bin` como último recurso."""
    mime_type = (mime_type or "").strip().lower()
    if mime_type in _MIME_EXTENSIONS:
        return _MIME_EXTENSIONS[mime_type]
    return mimetypes.guess_extension(mime_type) or ".bin"


def synthesize_file_name(message, mime_type: str, kind: MediaKind) -> str:
    """Inventa um nome para mídia que chegou sem `DocumentAttributeFilename`.

    Vídeo enviado pelo celular "como vídeo" é recodificado pelo Telegram e
    perde o nome original: chega só com o atributo de vídeo. Antes, essa mídia
    era descartada em silêncio — o arquivo estava no grupo, nunca aparecia na
    lista, e reabrir o app não resolvia, porque não havia cache nenhum para
    corrigir; o arquivo simplesmente nunca virava um `MediaFile`.

    A legenda é a primeira escolha para o nome porque é justamente onde se
    escreve o título nesse tipo de envio. Seja como for, o nome é editável na
    UI antes de confirmar o download — o que não pode acontecer é o arquivo
    não aparecer.
    """
    extension = _extension_for(mime_type)

    caption = (getattr(message, "message", "") or "").strip()
    first_line = caption.splitlines()[0] if caption else ""
    base = sanitize_filename(first_line).strip(" .-") if first_line.strip() else ""
    if not base or base == "Sem Titulo":
        prefix = "video" if kind == MediaKind.VIDEO else "arquivo"
        base = f"{prefix}_{message.id}"

    base = base[:120].strip(" .-") or f"arquivo_{message.id}"
    if Path(base).suffix.lower() == extension:
        return base
    return base + extension


class TelegramWorker(QThread):
    """Dono exclusivo do TelegramClient e do event loop asyncio que o executa."""

    # --- autenticação -------------------------------------------------
    login_code_needed = Signal()
    login_password_needed = Signal()
    login_success = Signal()
    login_error = Signal(str)
    connection_state_changed = Signal(bool)

    # --- navegação ------------------------------------------------------
    dialogs_ready = Signal(list)  # list[TelegramGroup]
    media_ready = Signal(object)  # MediaPage de uma listagem/paginação
    new_media_ready = Signal(object)  # MediaPage de uma checagem incremental
    new_media_error = Signal(str)  # mensagem de erro da checagem de novos

    # --- downloads --------------------------------------------------------
    download_status_changed = Signal(str, object)  # task_id, DownloadStatus
    download_progress = Signal(str, int, int, float)  # task_id, current, total, speed_bps
    download_completed = Signal(str, str)  # task_id, caminho final
    download_error = Signal(str, str)  # task_id, mensagem

    status_message = Signal(str)

    def __init__(self, session_path: Path, parent=None):
        super().__init__(parent)
        self.session_path = session_path
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.client = None  # TelegramClient, criado dentro da thread

        self._api_id: Optional[int] = None
        self._api_hash: Optional[str] = None
        self._phone: Optional[str] = None

        self._code_future: Optional[asyncio.Future] = None
        self._password_future: Optional[asyncio.Future] = None

        self._max_concurrent = 3
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._active_futures: Dict[str, "asyncio.Future"] = {}

        self._started_event = threading.Event()

    # ------------------------------------------------------------------
    # Ciclo de vida da thread / loop
    # ------------------------------------------------------------------
    def run(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self._semaphore = asyncio.Semaphore(self._max_concurrent)
        self._started_event.set()
        try:
            self.loop.run_forever()
        finally:
            self.loop.close()

    def shutdown(self) -> None:
        """Encerra a thread de forma limpa. Chamar ao fechar a aplicação."""
        if self.loop and self.loop.is_running():
            async def _close():
                if self.client and self.client.is_connected():
                    await self.client.disconnect()

            fut = asyncio.run_coroutine_threadsafe(_close(), self.loop)
            try:
                fut.result(timeout=5)
            except Exception:
                pass
            self.loop.call_soon_threadsafe(self.loop.stop)
        self.wait(3000)

    def set_max_concurrent_downloads(self, value: int) -> None:
        self._max_concurrent = max(1, value)
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(
                lambda: setattr(self, "_semaphore", asyncio.Semaphore(self._max_concurrent))
            )

    def _submit(self, coro) -> "asyncio.Future":
        self._started_event.wait(timeout=5)
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    # ------------------------------------------------------------------
    # Autenticação
    # ------------------------------------------------------------------
    def connect_and_login(self, api_id: int, api_hash: str, phone: str) -> None:
        """Primeiro login: pode disparar login_code_needed / login_password_needed."""
        self._api_id, self._api_hash, self._phone = api_id, api_hash, phone
        self._submit(self._async_connect_and_login())

    def auto_login(self, api_id: int, api_hash: str) -> None:
        """Reconecta usando a sessão já salva, sem pedir telefone/código novamente."""
        self._api_id, self._api_hash = api_id, api_hash
        self._submit(self._async_auto_login())

    def submit_code(self, code: str) -> None:
        if self._code_future and not self._code_future.done():
            self.loop.call_soon_threadsafe(self._code_future.set_result, code)

    def submit_password(self, password: str) -> None:
        if self._password_future and not self._password_future.done():
            self.loop.call_soon_threadsafe(self._password_future.set_result, password)

    async def _create_client(self):
        from telethon import TelegramClient

        return TelegramClient(str(self.session_path), self._api_id, self._api_hash)

    async def _async_connect_and_login(self) -> None:
        from telethon.errors import SessionPasswordNeededError

        try:
            self.client = await self._create_client()
            await self.client.connect()
            if not await self.client.is_user_authorized():
                await self.client.send_code_request(self._phone)
                self.login_code_needed.emit()
                code = await self._wait_future("_code_future")
                try:
                    await self.client.sign_in(self._phone, code)
                except SessionPasswordNeededError:
                    self.login_password_needed.emit()
                    password = await self._wait_future("_password_future")
                    await self.client.sign_in(password=password)
            self.login_success.emit()
            self.connection_state_changed.emit(True)
        except Exception as exc:  # noqa: BLE001 - queremos reportar qualquer falha à UI
            logger.exception("Falha no login")
            self.login_error.emit(str(exc))
            self.connection_state_changed.emit(False)

    async def _async_auto_login(self) -> None:
        try:
            self.client = await self._create_client()
            await self.client.connect()
            if await self.client.is_user_authorized():
                self.login_success.emit()
                self.connection_state_changed.emit(True)
            else:
                self.login_error.emit(
                    "A sessão salva expirou ou foi revogada. Faça login novamente."
                )
                self.connection_state_changed.emit(False)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Falha ao reconectar com sessão salva")
            self.login_error.emit(str(exc))
            self.connection_state_changed.emit(False)

    async def _wait_future(self, attr_name: str):
        future = self.loop.create_future()
        setattr(self, attr_name, future)
        try:
            return await future
        finally:
            setattr(self, attr_name, None)

    # ------------------------------------------------------------------
    # Navegação: grupos e arquivos
    # ------------------------------------------------------------------
    def list_dialogs(self) -> None:
        self._submit(self._async_list_dialogs())

    async def _async_list_dialogs(self) -> None:
        try:
            groups: List[TelegramGroup] = []
            async for dialog in self.client.iter_dialogs():
                if not (dialog.is_group or dialog.is_channel):
                    continue
                groups.append(
                    TelegramGroup(
                        id=dialog.id,
                        title=dialog.name or "(sem título)",
                        is_channel=dialog.is_channel,
                        is_group=dialog.is_group,
                        participants_count=getattr(dialog.entity, "participants_count", None),
                        unread_count=dialog.unread_count,
                    )
                )
            self.dialogs_ready.emit(groups)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Erro ao listar diálogos")
            self.status_message.emit(f"Erro ao listar grupos: {exc}")

    def list_media(self, group_id: int, limit: int = 100, offset_id: int = 0) -> None:
        self._submit(self._async_list_media(group_id, limit, offset_id))

    async def _async_list_media(self, group_id: int, limit: int, offset_id: int) -> None:
        """Lê uma fatia do histórico, do mais novo para o mais antigo.

        `limit` conta *mensagens*, não arquivos — é o orçamento da varredura.
        Por isso a fatia devolve as marcas de navegação em `MediaPage` em vez
        de deixar a UI deduzi-las dos arquivos: um trecho só de conversa não
        traz arquivo nenhum e mesmo assim precisa empurrar a paginação adiante.
        """
        try:
            entity = await self.client.get_entity(group_id)
            page = MediaPage(group_id=group_id)
            scanned = 0
            async for message in self.client.iter_messages(
                entity, limit=limit, offset_id=offset_id
            ):
                scanned += 1
                if scanned == 1:
                    page.newest_message_id = message.id
                page.oldest_message_id = message.id
                media_file = self._extract_media_file(message, group_id)
                if media_file:
                    page.files.append(media_file)
            # Fatia cheia significa que a varredura parou por orçamento, e não
            # por fim de histórico: provavelmente há mais para trás.
            page.hit_limit = scanned >= limit
            logger.info(
                "Grupo %s: %d mensagens varridas a partir de %s, %d arquivo(s).",
                group_id, scanned, offset_id or "topo", len(page.files),
            )
            self.media_ready.emit(page)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Erro ao listar mídia do grupo %s", group_id)
            self.status_message.emit(f"Erro ao listar arquivos: {exc}")

    def check_new_media(self, group_id: int, after_message_id: int, limit: int = 2000) -> None:
        """Busca só o que chegou no grupo depois de `after_message_id`."""
        self._submit(self._async_check_new_media(group_id, after_message_id, limit))

    async def _async_check_new_media(
        self, group_id: int, after_message_id: int, limit: int
    ) -> None:
        """Checagem incremental usada pelo botão "Atualizar".

        Recarregar a primeira página inteira funcionaria, mas descartaria tudo
        que o usuário já trouxe com "Carregar mais" e a seleção em andamento.
        `min_id` pede ao Telegram apenas as mensagens posteriores à marca
        d'água — quase sempre uma resposta minúscula.

        **`reverse=True` é o ponto central desta função.** Varrendo do mais
        novo para o mais antigo, bater no limite deixa um buraco: as mensagens
        entre o limite e a marca d'água nunca são lidas, e avançar a marca
        d'água depois disso torna esse intervalo inalcançável para sempre — o
        sintoma é o "Atualizar" parar de trazer novidade, sem erro nenhum, e
        continuar assim depois de reabrir o app. Do mais antigo para o mais
        novo (`min_id` passa a valer como um `offset_id` exclusivo) a varredura
        é contígua à marca d'água: cortar no limite só adianta menos terreno, e
        a marca d'água avança até exatamente onde a leitura chegou. A próxima
        checagem retoma dali, sem buraco.

        O orçamento é alto de propósito. Ele limita o terreno *novo* desde a
        última checagem, não o grupo inteiro: o custo só aparece na primeira
        atualização depois de muito tempo sem abrir o app. Um limite curto, em
        troca, obrigaria o usuário a clicar em "Atualizar" várias vezes para
        atravessar um trecho de conversa até chegar nos arquivos.
        """
        try:
            entity = await self.client.get_entity(group_id)
            page = MediaPage(group_id=group_id)
            scanned = 0
            async for message in self.client.iter_messages(
                entity, limit=limit, min_id=after_message_id, reverse=True
            ):
                scanned += 1
                if scanned == 1:
                    page.oldest_message_id = message.id
                page.newest_message_id = message.id
                media_file = self._extract_media_file(message, group_id)
                if media_file:
                    page.files.append(media_file)
            page.hit_limit = scanned >= limit
            logger.info(
                "Grupo %s: %d mensagens novas depois de %s, %d arquivo(s).",
                group_id, scanned, after_message_id, len(page.files),
            )
            self.new_media_ready.emit(page)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Erro ao checar mídia nova do grupo %s", group_id)
            self.new_media_error.emit(str(exc))

    @staticmethod
    def _extract_media_file(message, group_id: int) -> Optional[MediaFile]:
        if not message.media:
            return None

        file_name = None
        mime_type = ""
        size = 0
        kind = MediaKind.OTHER
        duration = None

        if message.video:
            kind = MediaKind.VIDEO
            duration = getattr(message.video, "duration", None)

        document = getattr(message, "document", None)
        if document:
            size = document.size
            mime_type = document.mime_type or ""
            for attr in document.attributes:
                name = getattr(attr, "file_name", None)
                if name:
                    file_name = name
            if kind == MediaKind.OTHER and mime_type.startswith("video/"):
                kind = MediaKind.VIDEO
            elif kind == MediaKind.OTHER:
                kind = MediaKind.DOCUMENT

        if kind == MediaKind.OTHER:
            # Mídia que não é documento nem vídeo (foto, sticker, enquete...):
            # não é o que este app organiza.
            logger.debug("Mensagem %s: mídia de tipo não suportado.", message.id)
            return None

        if not file_name:
            # Nunca descarte por falta de nome: ver `synthesize_file_name`.
            file_name = synthesize_file_name(message, mime_type, kind)
            logger.info(
                "Mensagem %s veio sem nome de arquivo; usando %r.",
                message.id, file_name,
            )

        return MediaFile(
            message_id=message.id,
            group_id=group_id,
            file_name=file_name,
            size=size,
            mime_type=mime_type,
            kind=kind,
            date=message.date.isoformat() if message.date else None,
            duration=duration,
        )

    # ------------------------------------------------------------------
    # Downloads
    # ------------------------------------------------------------------
    def queue_download(self, task: DownloadTask) -> None:
        future = self._submit(self._async_download(task))
        self._active_futures[task.id] = future

    def cancel_download(self, task_id: str) -> None:
        future = self._active_futures.get(task_id)
        if future and not future.done():
            self.loop.call_soon_threadsafe(future.cancel)

    async def _download_to_file(self, message, file_size: int, tmp_path: Path, progress_callback) -> None:
        """Baixa a mídia de `message` para `tmp_path`.

        Usa múltiplas conexões MTProto em paralelo (`fast_download`) para
        arquivos grandes — o método padrão do Telethon usa uma única
        conexão e fica limitado a poucos KB/s independente da internet do
        usuário. Se o download paralelo falhar por qualquer motivo (ex.:
        arquivo servido via CDN, DC inválida), cai de volta para o método
        padrão em vez de propagar o erro.
        """
        from telethon import utils as telethon_utils

        dc_id, file_location = telethon_utils.get_input_location(message)
        if file_location is not None and file_size >= fast_download.MIN_PARALLEL_FILE_SIZE:
            transferrer = fast_download.ParallelTransferrer(self.client)
            try:
                await transferrer.download(
                    file_location, file_size, dc_id, tmp_path, progress_callback=progress_callback
                )
                return
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Download paralelo falhou, tentando método padrão", exc_info=True
                )

        await self.client.download_media(
            message, file=str(tmp_path), progress_callback=progress_callback
        )

    async def _async_download(self, task: DownloadTask) -> None:
        assert self._semaphore is not None
        async with self._semaphore:
            try:
                self.download_status_changed.emit(task.id, DownloadStatus.DOWNLOADING)
                entity = await self.client.get_entity(task.media_file.group_id)
                message = await self.client.get_messages(entity, ids=task.media_file.message_id)
                if message is None:
                    raise RuntimeError("Mensagem original não encontrada (pode ter sido apagada).")

                start_time = time.monotonic()
                last_emit_time = [start_time]

                def progress_callback(current: int, total: int) -> None:
                    now = time.monotonic()
                    # Emite no máximo a cada ~0.4s (ou no fim) para não sobrecarregar a UI.
                    if now - last_emit_time[0] < 0.4 and current != total:
                        return
                    last_emit_time[0] = now
                    elapsed = max(now - start_time, 1e-6)
                    speed = current / elapsed
                    self.download_progress.emit(task.id, current, total, speed)

                task.destination_path.parent.mkdir(parents=True, exist_ok=True)
                tmp_path = task.destination_path.with_name(task.destination_path.name + ".part")

                await self._download_to_file(message, task.media_file.size, tmp_path, progress_callback)
                tmp_path.replace(task.destination_path)
                self.download_status_changed.emit(task.id, DownloadStatus.COMPLETED)
                self.download_completed.emit(task.id, str(task.destination_path))
            except asyncio.CancelledError:
                self.download_status_changed.emit(task.id, DownloadStatus.CANCELLED)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Erro ao baixar %s", task.media_file.file_name)
                self.download_status_changed.emit(task.id, DownloadStatus.ERROR)
                self.download_error.emit(task.id, str(exc))
            finally:
                self._active_futures.pop(task.id, None)
