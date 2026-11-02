"""Testes do módulo core.credentials.

Usa um diretório temporário para não tocar na configuração real do usuário
que roda os testes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.credentials import CredentialStore


@pytest.fixture
def store(tmp_path: Path) -> CredentialStore:
    return CredentialStore(config_dir=tmp_path)


def test_no_credentials_initially(store: CredentialStore):
    assert store.has_saved_credentials() is False
    assert store.load_credentials() is None


def test_save_and_load_roundtrip(store: CredentialStore):
    store.save_credentials(api_id=555, api_hash="hash123", phone="+551199999999")
    loaded = store.load_credentials()
    assert loaded == {"api_id": 555, "api_hash": "hash123", "phone": "+551199999999"}


def test_credentials_file_is_encrypted_on_disk(store: CredentialStore):
    store.save_credentials(api_id=555, api_hash="super-secret-hash", phone="+551199999999")
    raw_bytes = store.credentials_path.read_bytes()
    assert b"super-secret-hash" not in raw_bytes


def test_clear_removes_credentials(store: CredentialStore):
    store.save_credentials(api_id=1, api_hash="x", phone="y")
    store.clear(remove_session=False)
    assert store.has_saved_credentials() is False


def test_clear_can_also_remove_session_file(store: CredentialStore):
    session_file = store.session_path.with_suffix(".session")
    session_file.write_text("fake-session-data")
    store.save_credentials(api_id=1, api_hash="x", phone="y")

    store.clear(remove_session=True)

    assert not session_file.exists()
    assert store.has_active_session() is False
