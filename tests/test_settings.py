"""Testes de config/settings.py — foco na lista de grupos fixados.

O settings.json é escrito/lido a cada sessão e pode ter vindo de uma versão
do app que ainda não conhecia o campo `pinned_group_ids` (ou de uma edição
manual). Carregar não pode explodir em nenhum desses casos.
"""

from __future__ import annotations

import json

from config.settings import AppSettings, SettingsManager


def test_sem_fixados_por_padrao():
    assert AppSettings().pinned_group_ids == []


def test_default_nao_e_compartilhado_entre_instancias():
    first = AppSettings()
    first.pinned_group_ids.append(42)
    assert AppSettings().pinned_group_ids == []


def test_round_trip_dos_fixados(tmp_path):
    manager = SettingsManager(tmp_path)
    settings = manager.load()
    settings.pinned_group_ids = [10, 20]
    manager.save(settings)

    raw = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert raw["pinned_group_ids"] == [10, 20]
    assert SettingsManager(tmp_path).load().pinned_group_ids == [10, 20]


def test_settings_de_versao_antiga_carrega_sem_fixados(tmp_path):
    (tmp_path / "settings.json").write_text(
        json.dumps({"movies_library_path": "/filmes", "max_concurrent_downloads": 5}),
        encoding="utf-8",
    )
    settings = SettingsManager(tmp_path).load()
    assert settings.pinned_group_ids == []
    assert settings.movies_library_path == "/filmes"


def test_lista_de_fixados_corrompida_e_normalizada(tmp_path):
    (tmp_path / "settings.json").write_text(
        json.dumps({"pinned_group_ids": ["7", 7, None, "abc", 9]}), encoding="utf-8"
    )
    assert SettingsManager(tmp_path).load().pinned_group_ids == [7, 9]


def test_fixados_com_tipo_errado_viram_lista_vazia(tmp_path):
    (tmp_path / "settings.json").write_text(
        json.dumps({"pinned_group_ids": "nao é uma lista"}), encoding="utf-8"
    )
    assert SettingsManager(tmp_path).load().pinned_group_ids == []
