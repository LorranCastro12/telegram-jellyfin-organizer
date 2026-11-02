"""Diálogo de configurações: caminhos da biblioteca Jellyfin e preferências de download."""

from __future__ import annotations

from typing import Dict

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from config.settings import LIBRARY_FIELDS, AppSettings


class SettingsDialog(QDialog):
    logout_requested = Signal()

    def __init__(self, settings: AppSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configurações")
        self.setMinimumWidth(520)
        self._settings = settings
        # nome do campo em AppSettings -> QLineEdit correspondente
        self._path_edits: Dict[str, QLineEdit] = {}
        self._build_ui()
        self._load_from_settings()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        title = QLabel("Bibliotecas do Jellyfin")
        title.setProperty("class", "sectionTitle")
        root.addWidget(title)

        form = QFormLayout()

        # Uma linha por biblioteca, na ordem definida em config.settings.
        for _content_type, field_name, label in LIBRARY_FIELDS:
            form.addRow(f"Pasta de {label}", self._build_path_row(field_name))

        self.concurrent_spin = QSpinBox()
        self.concurrent_spin.setRange(1, 10)
        form.addRow("Downloads simultâneos", self.concurrent_spin)

        root.addLayout(form)

        hint = QLabel(
            "As pastas devem apontar para as raízes das bibliotecas configuradas no Jellyfin "
            "(ex.: /dados/jellyfin/Filmes e /dados/jellyfin/Series). Desenhos, animes e "
            "documentários são organizados por temporada, igual às séries — deixe em branco "
            "as bibliotecas que você não usa."
        )
        hint.setWordWrap(True)
        hint.setProperty("class", "muted")
        root.addWidget(hint)

        root.addSpacing(8)
        account_title = QLabel("Conta do Telegram")
        account_title.setProperty("class", "sectionTitle")
        root.addWidget(account_title)

        logout_btn = QPushButton("Sair e esquecer credenciais")
        logout_btn.setProperty("class", "danger")
        logout_btn.clicked.connect(self._confirm_logout)
        root.addWidget(logout_btn)

        root.addStretch(1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = QPushButton("Cancelar")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Salvar")
        save_btn.setProperty("class", "primary")
        save_btn.clicked.connect(self._save_and_close)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        root.addLayout(btn_row)

    def _build_path_row(self, field_name: str) -> QHBoxLayout:
        """Monta o par [QLineEdit + botão Procurar] de uma biblioteca."""
        edit = QLineEdit()
        browse = QPushButton("Procurar...")
        browse.clicked.connect(lambda _=False, e=edit: self._browse(e))
        row = QHBoxLayout()
        row.addWidget(edit)
        row.addWidget(browse)
        self._path_edits[field_name] = edit
        return row

    def _browse(self, line_edit: QLineEdit) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Selecionar pasta")
        if directory:
            line_edit.setText(directory)

    def _load_from_settings(self) -> None:
        for field_name, edit in self._path_edits.items():
            edit.setText(getattr(self._settings, field_name, ""))
        self.concurrent_spin.setValue(self._settings.max_concurrent_downloads)

    def _confirm_logout(self) -> None:
        answer = QMessageBox.question(
            self,
            "Sair da conta",
            "Isso vai apagar a sessão salva e as credenciais criptografadas deste "
            "computador. Você precisará fazer login novamente. Continuar?",
        )
        if answer == QMessageBox.Yes:
            self.logout_requested.emit()
            self.accept()

    def _save_and_close(self) -> None:
        for field_name, edit in self._path_edits.items():
            setattr(self._settings, field_name, edit.text().strip())
        self._settings.max_concurrent_downloads = self.concurrent_spin.value()
        self.accept()

    def updated_settings(self) -> AppSettings:
        return self._settings
