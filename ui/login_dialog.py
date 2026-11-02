"""Diálogo de autenticação com o Telegram, em etapas.

Etapa 1: api_id / api_hash (obtidos em https://my.telegram.org/apps) + telefone.
Etapa 2: código de verificação enviado pelo Telegram.
Etapa 3: senha de verificação em duas etapas (2FA), se o usuário tiver ativado.

Depois do primeiro login bem-sucedido, a sessão fica salva em disco e as
próximas aberturas do app pulam direto para a tela principal.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


class LoginDialog(QDialog):
    credentials_submitted = Signal(int, str, str)  # api_id, api_hash, phone
    code_submitted = Signal(str)
    password_submitted = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Conectar ao Telegram")
        self.setMinimumWidth(420)
        self.setModal(True)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        title = QLabel("Conectar sua conta do Telegram")
        title.setProperty("class", "sectionTitle")
        root.addWidget(title)

        self.stack = QStackedWidget()
        root.addWidget(self.stack)

        self.stack.addWidget(self._build_credentials_page())
        self.stack.addWidget(self._build_code_page())
        self.stack.addWidget(self._build_password_page())

        self.feedback_label = QLabel("")
        self.feedback_label.setWordWrap(True)
        self.feedback_label.setStyleSheet("color: #C1554B;")
        root.addWidget(self.feedback_label)

    def _build_credentials_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)

        hint = QLabel(
            'Crie um app em <b>my.telegram.org/apps</b> para obter o "api_id" e o "api_hash". '
            "Isso é feito uma única vez — depois disso o app não pede login novamente."
        )
        hint.setWordWrap(True)
        hint.setProperty("class", "muted")
        layout.addWidget(hint)

        form = QFormLayout()
        self.api_id_edit = QLineEdit()
        self.api_id_edit.setPlaceholderText("Ex.: 1234567")
        self.api_hash_edit = QLineEdit()
        self.api_hash_edit.setPlaceholderText("Ex.: 0123456789abcdef0123456789abcdef")
        self.phone_edit = QLineEdit()
        self.phone_edit.setPlaceholderText("+55 11 91234-5678")
        form.addRow("API ID", self.api_id_edit)
        form.addRow("API Hash", self.api_hash_edit)
        form.addRow("Telefone", self.phone_edit)
        layout.addLayout(form)

        self.remember_label = QLabel(
            "As credenciais ficam salvas de forma criptografada neste computador."
        )
        self.remember_label.setProperty("class", "muted")
        layout.addWidget(self.remember_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.connect_btn = QPushButton("Conectar")
        self.connect_btn.setProperty("class", "primary")
        self.connect_btn.clicked.connect(self._submit_credentials)
        btn_row.addWidget(self.connect_btn)
        layout.addLayout(btn_row)

        return page

    def _build_code_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)
        layout.addWidget(QLabel("Digite o código de verificação enviado pelo Telegram:"))
        self.code_edit = QLineEdit()
        self.code_edit.setPlaceholderText("12345")
        layout.addWidget(self.code_edit)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        confirm_btn = QPushButton("Confirmar código")
        confirm_btn.setProperty("class", "primary")
        confirm_btn.clicked.connect(lambda: self.code_submitted.emit(self.code_edit.text().strip()))
        btn_row.addWidget(confirm_btn)
        layout.addLayout(btn_row)
        return page

    def _build_password_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)
        layout.addWidget(QLabel("Sua conta tem verificação em duas etapas. Digite a senha:"))
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.password_edit)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        confirm_btn = QPushButton("Confirmar senha")
        confirm_btn.setProperty("class", "primary")
        confirm_btn.clicked.connect(
            lambda: self.password_submitted.emit(self.password_edit.text())
        )
        btn_row.addWidget(confirm_btn)
        layout.addLayout(btn_row)
        return page

    # ------------------------------------------------------------------
    def _submit_credentials(self) -> None:
        self.feedback_label.setText("")
        api_id_text = self.api_id_edit.text().strip()
        api_hash = self.api_hash_edit.text().strip()
        phone = self.phone_edit.text().strip()
        if not api_id_text.isdigit() or not api_hash or not phone:
            self.feedback_label.setText("Preencha API ID (número), API Hash e telefone.")
            return
        self.connect_btn.setEnabled(False)
        self.connect_btn.setText("Conectando...")
        self.credentials_submitted.emit(int(api_id_text), api_hash, phone)

    def show_code_step(self) -> None:
        self.stack.setCurrentIndex(1)

    def show_password_step(self) -> None:
        self.stack.setCurrentIndex(2)

    def show_error(self, message: str) -> None:
        self.feedback_label.setText(message)
        self.connect_btn.setEnabled(True)
        self.connect_btn.setText("Conectar")

    def prefill(self, api_id: str = "", api_hash: str = "", phone: str = "") -> None:
        self.api_id_edit.setText(api_id)
        self.api_hash_edit.setText(api_hash)
        self.phone_edit.setText(phone)
