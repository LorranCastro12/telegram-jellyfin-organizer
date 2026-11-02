"""Download de arquivo único usando múltiplas conexões MTProto em paralelo.

Por que isso existe: `TelegramClient.download_media` (Telethon) busca as
partes do arquivo sequencialmente numa única conexão TCP/MTProto — pede um
pedaço, espera a resposta, só então pede o próximo. O Telegram limita a
taxa de transferência por conexão (não pela banda do usuário nem pela
conta), então em conexões de latência mais alta isso resulta em poucos
KB/s mesmo com internet rápida, independentemente do tamanho do arquivo.
Os clientes oficiais contornam isso abrindo várias conexões simultâneas
para o mesmo datacenter e baixando pedaços diferentes em paralelo — é a
mesma técnica implementada aqui.

A auth_key é exportada uma única vez (`auth.ExportAuthorizationRequest`) e
reaproveitada nas conexões extras, evitando renegociar autenticação a cada
uma. Isso usa métodos "privados" do Telethon (`_create_exported_sender` já
faz algo parecido, mas cacheia uma única conexão por DC — aqui precisamos
de N conexões independentes de propósito, por isso a reimplementação).
"""

from __future__ import annotations

import asyncio
import logging
import math
from pathlib import Path
from typing import Callable, List, Optional

from telethon import utils
from telethon.network import MTProtoSender
from telethon.tl import functions, types
from telethon.tl.alltlobjects import LAYER

logger = logging.getLogger(__name__)

# Limite do próprio protocolo: partes de upload.getFile devem ser múltiplas
# de 4096 bytes, até no máximo 512 KB.
MAX_CHUNK_SIZE = 512 * 1024

# Nº máximo de conexões simultâneas para um único arquivo. Mais que isso
# tende a esbarrar em FLOOD_WAIT sem ganho adicional de throughput.
MAX_CONNECTIONS = 8

# Abaixo desse tamanho não compensa abrir várias conexões: o overhead do
# handshake (TCP + troca de chaves) supera o ganho de paralelismo.
MIN_PARALLEL_FILE_SIZE = 5 * 1024 * 1024


class FastDownloadError(Exception):
    """Erro no download paralelo; o chamador deve cair para o método padrão."""


def connection_count(file_size: int, max_connections: int = MAX_CONNECTIONS) -> int:
    """Escala o nº de conexões com o tamanho do arquivo (mais conexões para
    arquivos maiores, onde o overhead de abrir a conexão é diluído)."""
    full_size = 100 * 1024 * 1024
    if file_size >= full_size:
        return max_connections
    return max(1, math.ceil((file_size / full_size) * max_connections))


class _PartSender:
    """Uma conexão MTProto dedicada, responsável por um subconjunto de
    partes do arquivo (distribuídas em stride, tipo round-robin)."""

    def __init__(self, sender: MTProtoSender, request: "functions.upload.GetFileRequest", stride: int, remaining: int):
        self.sender = sender
        self.request = request
        self.stride = stride
        self.remaining = remaining

    async def next_chunk(self, client) -> bytes:
        result = await client._call(self.sender, self.request)
        if isinstance(result, (types.upload.FileCdnRedirect, types.upload.CdnFileReuploadNeeded)):
            raise FastDownloadError("Arquivo servido via CDN; use o download padrão.")
        self.request.offset += self.stride
        self.remaining -= 1
        return result.bytes


class ParallelTransferrer:
    """Baixa um único arquivo do Telegram usando várias conexões em paralelo."""

    def __init__(self, client):
        self.client = client
        self._part_senders: List[_PartSender] = []
        self._auth_key = None
        self._dc_id: Optional[int] = None
        self._reused_main_sender = False

    async def _create_sender(self, dc_id: int) -> MTProtoSender:
        dc = await self.client._get_dc(dc_id)
        sender = MTProtoSender(self._auth_key, loggers=self.client._log)
        await sender.connect(self.client._connection(
            dc.ip_address,
            dc.port,
            dc.id,
            loggers=self.client._log,
            proxy=self.client._proxy,
            local_addr=self.client._local_addr,
        ))
        if self._auth_key is None:
            auth = await self.client(functions.auth.ExportAuthorizationRequest(dc_id))
            self.client._init_request.query = functions.auth.ImportAuthorizationRequest(
                id=auth.id, bytes=auth.bytes
            )
            await sender.send(functions.InvokeWithLayerRequest(LAYER, self.client._init_request))
            self._auth_key = sender.auth_key
        return sender

    async def _init_part_senders(self, file_location, dc_id: int, file_size: int, connections: int) -> int:
        self._dc_id = dc_id
        part_size_kb = min(utils.get_appropriated_part_size(file_size), MAX_CHUNK_SIZE // 1024)
        part_size = part_size_kb * 1024
        part_count = math.ceil(file_size / part_size)
        connections = max(1, min(connections, part_count))
        stride = connections * part_size

        same_dc = dc_id == self.client.session.dc_id
        for i in range(connections):
            if i == 0 and same_dc:
                sender = self.client._sender
                self._reused_main_sender = True
            else:
                sender = await self._create_sender(dc_id)
            request = functions.upload.GetFileRequest(file_location, offset=i * part_size, limit=part_size)
            remaining = part_count // connections + (1 if i < part_count % connections else 0)
            self._part_senders.append(_PartSender(sender, request, stride, remaining))
        return part_size

    async def close(self) -> None:
        for i, part_sender in enumerate(self._part_senders):
            if i == 0 and self._reused_main_sender:
                continue  # é a conexão principal do client, não fecha
            try:
                await part_sender.sender.disconnect()
            except Exception:  # noqa: BLE001 - limpeza best-effort
                logger.debug("Falha ao desconectar sender auxiliar", exc_info=True)
        self._part_senders = []

    async def download(
        self,
        file_location,
        file_size: int,
        dc_id: Optional[int],
        out_path: Path,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        max_connections: int = MAX_CONNECTIONS,
    ) -> None:
        effective_dc_id = dc_id or self.client.session.dc_id
        connections = connection_count(file_size, max_connections)

        try:
            await self._init_part_senders(file_location, effective_dc_id, file_size, connections)
        except Exception as exc:  # noqa: BLE001
            await self.close()
            raise FastDownloadError(f"Falha ao abrir conexões paralelas: {exc}") from exc

        downloaded = 0
        try:
            with open(out_path, "wb") as f:
                f.truncate(file_size)
                while any(ps.remaining > 0 for ps in self._part_senders):
                    active = [ps for ps in self._part_senders if ps.remaining > 0]
                    offsets = [ps.request.offset for ps in active]
                    chunks = await asyncio.gather(*(ps.next_chunk(self.client) for ps in active))
                    for offset, data in zip(offsets, chunks):
                        f.seek(offset)
                        f.write(data)
                        downloaded += len(data)
                    if progress_callback:
                        progress_callback(min(downloaded, file_size), file_size)
        finally:
            await self.close()
