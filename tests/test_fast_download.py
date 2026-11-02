"""Testes para core/fast_download.py.

Não é possível testar contra a API real do Telegram (exigiria conta e
conexão de verdade), mas a lógica de particionamento/remontagem do arquivo
é pura e testável isoladamente: montamos `_PartSender`s falsos que devolvem
bytes determinísticos com atraso assíncrono variável (para simular chegada
fora de ordem) e verificamos que o arquivo final fica byte-a-byte correto.
"""

from __future__ import annotations

import asyncio
import random

from core import fast_download


def test_connection_count_scales_with_file_size():
    assert fast_download.connection_count(1024, max_connections=8) == 1
    assert fast_download.connection_count(50 * 1024 * 1024, max_connections=8) == 4
    assert fast_download.connection_count(100 * 1024 * 1024, max_connections=8) == 8
    assert fast_download.connection_count(500 * 1024 * 1024, max_connections=8) == 8


class _FakeRequest:
    def __init__(self, offset: int):
        self.offset = offset


class _FakePartSender:
    """Substitui core.fast_download._PartSender sem tocar em rede."""

    def __init__(self, content: bytes, offset: int, stride: int, part_size: int, remaining: int):
        self._content = content
        self.request = _FakeRequest(offset)
        self.stride = stride
        self.part_size = part_size
        self.remaining = remaining

    async def next_chunk(self, client) -> bytes:
        await asyncio.sleep(random.uniform(0, 0.01))  # simula latência de rede variável
        start = self.request.offset
        data = self._content[start:start + self.part_size]
        self.request.offset += self.stride
        self.remaining -= 1
        return data


def test_download_reassembles_file_in_correct_order(tmp_path):
    random.seed(42)
    content = bytes(random.getrandbits(8) for _ in range(50_000))
    part_size = 4096
    connections = 5
    stride = connections * part_size
    part_count = -(-len(content) // part_size)  # ceil div

    transferrer = fast_download.ParallelTransferrer(client=object())

    async def _fake_init(*args, **kwargs):
        for i in range(connections):
            remaining = part_count // connections + (1 if i < part_count % connections else 0)
            transferrer._part_senders.append(
                _FakePartSender(content, i * part_size, stride, part_size, remaining)
            )
        return part_size

    async def _fake_close():
        transferrer._part_senders = []

    transferrer._init_part_senders = _fake_init
    transferrer.close = _fake_close

    out_path = tmp_path / "saida.bin"
    progress_calls = []

    asyncio.run(
        transferrer.download(
            file_location=None,
            file_size=len(content),
            dc_id=1,
            out_path=out_path,
            progress_callback=lambda cur, total: progress_calls.append((cur, total)),
            max_connections=connections,
        )
    )

    assert out_path.read_bytes() == content
    assert progress_calls
    assert progress_calls[-1] == (len(content), len(content))
