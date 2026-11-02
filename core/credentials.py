"""Armazenamento persistente e criptografado das credenciais do Telegram.

Estratégia:
- A chave de criptografia (Fernet) fica no cofre de credenciais do sistema
  operacional via `keyring` (Windows Credential Locker, macOS Keychain,
  Secret Service/KWallet no Linux). Se nenhum backend de keyring estiver
  disponível (ex.: alguns ambientes Linux headless), caímos para um arquivo
  local com permissão restrita (0600) e avisamos o usuário.
- api_id, api_hash e telefone ficam criptografados em `credentials.enc`.
- O arquivo de sessão do Telethon (.session) é o que realmente evita o
  "login toda vez": uma vez autorizado, o Telethon reconecta silenciosamente
  usando apenas esse arquivo, sem pedir código de verificação novamente.
"""

from __future__ import annotations

import json
import logging
import stat
from pathlib import Path
from typing import Optional, TypedDict

from cryptography.fernet import Fernet, InvalidToken
from platformdirs import user_config_dir

logger = logging.getLogger(__name__)

APP_NAME = "TelegramJellyfinOrganizer"
KEYRING_SERVICE = "telegram-jellyfin-organizer"
KEYRING_KEY_NAME = "fernet-encryption-key"


class StoredCredentials(TypedDict):
    api_id: int
    api_hash: str
    phone: str


class CredentialStore:
    """Lê/grava as credenciais do Telegram de forma criptografada em disco."""

    def __init__(self, config_dir: Optional[Path] = None):
        self.config_dir = config_dir or Path(user_config_dir(APP_NAME, appauthor=False))
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.credentials_path = self.config_dir / "credentials.enc"
        self.session_path = self.config_dir / "telegram_session"
        self.fallback_key_path = self.config_dir / ".key"
        self._fernet: Optional[Fernet] = None

    # ------------------------------------------------------------------
    # Gerenciamento da chave de criptografia
    # ------------------------------------------------------------------
    def _get_or_create_key(self) -> bytes:
        try:
            import keyring

            existing = keyring.get_password(KEYRING_SERVICE, KEYRING_KEY_NAME)
            if existing:
                return existing.encode("utf-8")
            new_key = Fernet.generate_key()
            keyring.set_password(KEYRING_SERVICE, KEYRING_KEY_NAME, new_key.decode("utf-8"))
            return new_key
        except Exception as exc:  # keyring sem backend disponível, etc.
            logger.warning(
                "Keyring do sistema indisponível (%s). Usando arquivo de chave local com "
                "permissões restritas em %s",
                exc,
                self.fallback_key_path,
            )
            return self._get_or_create_fallback_key()

    def _get_or_create_fallback_key(self) -> bytes:
        if self.fallback_key_path.exists():
            return self.fallback_key_path.read_bytes()
        key = Fernet.generate_key()
        self.fallback_key_path.write_bytes(key)
        try:
            self.fallback_key_path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
        except OSError:
            pass  # Windows não usa esses bits; ok ignorar.
        return key

    def _fernet_instance(self) -> Fernet:
        if self._fernet is None:
            self._fernet = Fernet(self._get_or_create_key())
        return self._fernet

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------
    def has_saved_credentials(self) -> bool:
        return self.credentials_path.exists()

    def has_active_session(self) -> bool:
        """Sessão do Telethon existe em disco (arquivo .session criado)."""
        return self.session_path.with_suffix(".session").exists()

    def save_credentials(self, api_id: int, api_hash: str, phone: str) -> None:
        payload: StoredCredentials = {"api_id": api_id, "api_hash": api_hash, "phone": phone}
        raw = json.dumps(payload).encode("utf-8")
        encrypted = self._fernet_instance().encrypt(raw)
        self.credentials_path.write_bytes(encrypted)
        try:
            self.credentials_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass

    def load_credentials(self) -> Optional[StoredCredentials]:
        if not self.credentials_path.exists():
            return None
        try:
            encrypted = self.credentials_path.read_bytes()
            raw = self._fernet_instance().decrypt(encrypted)
            return json.loads(raw.decode("utf-8"))
        except (InvalidToken, ValueError, json.JSONDecodeError) as exc:
            logger.error("Não foi possível decifrar as credenciais salvas: %s", exc)
            return None

    def clear(self, remove_session: bool = True) -> None:
        """Remove credenciais salvas e, opcionalmente, a sessão do Telegram (logout)."""
        if self.credentials_path.exists():
            self.credentials_path.unlink()
        if remove_session:
            session_file = self.session_path.with_suffix(".session")
            if session_file.exists():
                session_file.unlink()
