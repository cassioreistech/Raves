"""Central de Configurações Dark HUD (PySide6)."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from raves.core import database
from raves.core.licensing import current_status

DARK_QSS = (
    "QWidget { background-color: #070D19; color: #E0F7FA; "
    "font-family: 'Segoe UI'; font-size: 11px; }\n"
    "QTabWidget::pane { border: 1px solid #1A2A44; background: #0B1324; "
    "border-radius: 8px; }\n"
    "QTabBar::tab { background: #0E1A30; color: #7AA2C8; padding: 8px 14px; "
    "margin-right: 2px; border-top-left-radius: 6px; border-top-right-radius: 6px; }\n"
    "QTabBar::tab:selected { background: #0B1324; color: #00E5FF; "
    "border-bottom: 2px solid #00E5FF; }\n"
    "QPushButton { background: #0E1A30; color: #00E5FF; "
    "border: 1px solid #00E5FF; border-radius: 6px; padding: 6px 12px; }\n"
    "QPushButton:hover { background: #00E5FF; color: #070D19; }\n"
    "QLineEdit, QComboBox, QListWidget { background: #0E1A30; "
    "border: 1px solid #1A2A44; border-radius: 6px; padding: 4px; "
    "color: #E0F7FA; }\n"
    "QSlider::groove:horizontal { height: 4px; background: #1A2A44; "
    "border-radius: 2px; }\n"
    "QSlider::handle:horizontal { background: #00E5FF; width: 12px; "
    "margin: -4px 0; border-radius: 6px; }\n"
    "QLabel { color: #B0C4DE; }\n"
)


class SettingsWindow(QWidget):
    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("RAVES · Central de Controle")
        self.resize(720, 520)
        self.setStyleSheet(DARK_QSS)

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self.tabs.addTab(self._build_voice_tab(), "Voz & Áudio")
        self.tabs.addTab(self._build_brain_tab(), "Cérebro Local")
        self.tabs.addTab(self._build_workflows_tab(), "Workflows & Gatilhos")
        self.tabs.addTab(self._build_profile_tab(), "Perfil & Licença")

    # ------------------------------------------------------------------
    # Aba 1: Voz & Áudio
    # ------------------------------------------------------------------

    def _build_voice_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        layout.addWidget(QLabel("Microfone padrão:"))
        self.mic_combo = QComboBox()
        try:
            import sounddevice as sd

            devices = sd.query_devices()
            for index, device in enumerate(devices):
                if device.get("max_input_channels", 0) > 0:
                    self.mic_combo.addItem(f"{index}: {device['name']}", index)
        except Exception:
            self.mic_combo.addItem("(sounddevice indisponível)", -1)
        layout.addWidget(self.mic_combo)

        layout.addWidget(QLabel("Palavra de ativação:"))
        self.wake_word = QLineEdit("Robô")
        layout.addWidget(self.wake_word)

        layout.addWidget(QLabel("Voz do TTS:"))
        self.voice_gender_combo = QComboBox()
        self.voice_gender_combo.addItems(["feminina", "masculina"])
        try:
            from raves.engine.tts import get_gender

            current = get_gender()
            index = self.voice_gender_combo.findText(current)
            if index >= 0:
                self.voice_gender_combo.setCurrentIndex(index)
        except Exception:
            pass
        self.voice_gender_combo.currentTextChanged.connect(self._on_voice_gender_changed)
        layout.addWidget(self.voice_gender_combo)

        layout.addWidget(QLabel("Sensibilidade de silêncio:"))
        self.silence_slider = QSlider(Qt.Orientation.Horizontal)
        self.silence_slider.setRange(5, 30)
        self.silence_slider.setValue(15)
        layout.addWidget(self.silence_slider)

        calibrate_btn = QPushButton("Calibrar microfone")
        calibrate_btn.clicked.connect(self._on_calibrate)
        layout.addWidget(calibrate_btn)

        layout.addWidget(QLabel("Correções fonéticas aprendidas:"))
        self.corrections_list = QListWidget()
        self._refresh_corrections()
        layout.addWidget(self.corrections_list)

        delete_btn = QPushButton("Remover selecionada")
        delete_btn.clicked.connect(self._on_delete_correction)
        layout.addWidget(delete_btn)

        layout.addWidget(QLabel("Inicialização:"))
        self.autostart_checkbox = QCheckBox("Iniciar RAVES automaticamente com o Windows")
        try:
            from raves.core.autostart import is_enabled

            self.autostart_checkbox.setChecked(is_enabled())
        except Exception:
            pass
        self.autostart_checkbox.toggled.connect(self._on_autostart_toggled)
        layout.addWidget(self.autostart_checkbox)

        layout.addStretch(1)
        return widget

    def _refresh_corrections(self) -> None:
        self.corrections_list.clear()
        try:
            for row in database.get_speech_corrections():
                self.corrections_list.addItem(
                    f"{row['heard_phrase']} → {row['mapped_phrase']} ({row['hits']})"
                )
        except Exception:
            pass

    def _on_calibrate(self) -> None:
        try:
            from raves.engine.audio_pipeline import ResilientAudioCapture

            capture = ResilientAudioCapture()
            capture.start()
            floor = capture.calibrate(duration=0.5)
            capture.stop()
            self.corrections_list.addItem(f"[calibração] piso de ruído = {floor:.4f}")
        except Exception as exc:
            self.corrections_list.addItem(f"[erro] {exc}")

    def _on_autostart_toggled(self, checked: bool) -> None:
        try:
            from raves.core import autostart

            if checked:
                autostart.enable()
            else:
                autostart.disable()
        except Exception as exc:
            self.corrections_list.addItem(f"[erro autostart] {exc}")

    def _on_voice_gender_changed(self, gender: str) -> None:
        try:
            from raves.engine.tts import set_gender

            set_gender(gender)
        except Exception as exc:
            self.corrections_list.addItem(f"[erro voz] {exc}")

    def _on_delete_correction(self) -> None:
        item = self.corrections_list.currentItem()
        if item is None:
            return
        text = item.text()
        heard = text.split("→")[0].strip() if "→" in text else text.split(" ")[0]
        # Remove do banco via SQL direto (simples).
        try:
            with database._connect() as conn:
                conn.execute(
                    "DELETE FROM speech_corrections WHERE heard_phrase = ?", (heard.lower(),)
                )
            self._refresh_corrections()
        except Exception as exc:
            self.corrections_list.addItem(f"[erro] {exc}")

    # ------------------------------------------------------------------
    # Aba 2: Cérebro Local
    # ------------------------------------------------------------------

    def _build_brain_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.brain_status = QLabel("Status: verificando...")
        layout.addWidget(self.brain_status)

        layout.addWidget(QLabel("Modelo:"))
        self.model_combo = QComboBox()
        self.model_combo.addItems(["qwen2.5:1.5b", "qwen2.5:0.5b"])
        try:
            current = database.get_meta("ai_model") or "qwen2.5:1.5b"
            index = self.model_combo.findText(current)
            if index >= 0:
                self.model_combo.setCurrentIndex(index)
        except Exception:
            pass
        layout.addWidget(self.model_combo)

        btn_row = QHBoxLayout()
        install_btn = QPushButton("Instalar/Baixar Modelo")
        install_btn.clicked.connect(self._on_install_model)
        unload_btn = QPushButton("Descarregar RAM")
        unload_btn.clicked.connect(self._on_unload)
        status_btn = QPushButton("Atualizar Status")
        status_btn.clicked.connect(self._refresh_brain_status)
        btn_row.addWidget(install_btn)
        btn_row.addWidget(unload_btn)
        btn_row.addWidget(status_btn)
        layout.addLayout(btn_row)

        layout.addStretch(1)
        self._refresh_brain_status()
        return widget

    def _refresh_brain_status(self) -> None:
        try:
            from raves.ai.local_brain import LocalBrain

            brain = LocalBrain()
            available = brain.is_available()
            self.brain_status.setText(
                f"Ollama: {'ativo' if available else 'parado'} · modelo {brain.model}"
            )
        except Exception as exc:
            self.brain_status.setText(f"Erro: {exc}")

    def _on_install_model(self) -> None:
        import subprocess

        model = self.model_combo.currentText()
        try:
            subprocess.Popen(["ollama", "pull", model])
            self.brain_status.setText(f"Baixando {model}... (veja o terminal)")
        except Exception as exc:
            self.brain_status.setText(f"Falha: {exc}")

    def _on_unload(self) -> None:
        try:
            from raves.ai.local_brain import LocalBrain

            brain = LocalBrain()
            # Envia keep_alive=0 via urllib.
            import json
            import urllib.request

            payload = json.dumps({"model": brain.model, "prompt": "", "keep_alive": 0}).encode()
            req = urllib.request.Request(
                "http://localhost:11434/api/generate",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=10.0):
                    pass
                self.brain_status.setText("Modelo descarregado.")
            except Exception as exc:
                self.brain_status.setText(f"Falha: {exc}")
        except Exception as exc:
            self.brain_status.setText(f"Erro: {exc}")

    # ------------------------------------------------------------------
    # Aba 3: Workflows & Gatilhos
    # ------------------------------------------------------------------

    def _build_workflows_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        layout.addWidget(QLabel("Workflows disponíveis:"))
        self.workflows_list = QListWidget()
        self._refresh_workflows()
        layout.addWidget(self.workflows_list)

        btn_row = QHBoxLayout()
        run_btn = QPushButton("Executar selecionado")
        run_btn.clicked.connect(self._on_run_workflow)
        refresh_btn = QPushButton("Atualizar")
        refresh_btn.clicked.connect(self._refresh_workflows)
        new_btn = QPushButton("+ Criar Novo Workflow")
        new_btn.clicked.connect(self._on_new_workflow)
        btn_row.addWidget(run_btn)
        btn_row.addWidget(refresh_btn)
        btn_row.addWidget(new_btn)
        layout.addLayout(btn_row)

        layout.addWidget(QLabel("Gatilhos reativos:"))
        self.triggers_list = QListWidget()
        self._refresh_triggers()
        layout.addWidget(self.triggers_list)

        tbtn_row = QHBoxLayout()
        trefresh = QPushButton("Atualizar gatilhos")
        trefresh.clicked.connect(self._refresh_triggers)
        tbtn_row.addWidget(trefresh)
        layout.addLayout(tbtn_row)

        layout.addStretch(1)
        return widget

    def _refresh_workflows(self) -> None:
        self.workflows_list.clear()
        try:
            from raves.commands.workflow import WORKFLOWS_DIR

            if WORKFLOWS_DIR.exists():
                for path in sorted(WORKFLOWS_DIR.glob("*.yaml")):
                    self.workflows_list.addItem(path.stem)
        except Exception:
            pass

    def _on_run_workflow(self) -> None:
        item = self.workflows_list.currentItem()
        if item is None:
            return
        name = item.text()
        try:
            import subprocess

            subprocess.Popen(
                ["raves", "workflow", "run", name, "--apply"],
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
        except Exception as exc:
            self.workflows_list.addItem(f"[erro] {exc}")

    def _on_new_workflow(self) -> None:
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTextEdit, QVBoxLayout

        dialog = QDialog(self)
        dialog.setWindowTitle("Novo Workflow")
        dialog.resize(520, 400)
        vlayout = QVBoxLayout(dialog)

        name_edit = QLineEdit()
        name_edit.setPlaceholderText("nome_do_workflow")
        vlayout.addWidget(QLabel("Nome:"))
        vlayout.addWidget(name_edit)

        text_edit = QTextEdit()
        text_edit.setPlainText(
            "name: Novo Workflow\ndescription: criado pela UI\ncaminho:\nsteps:\n"
            "  - name: passo 1\n    action: wait\n    params: { seconds: 1 }\n"
        )
        vlayout.addWidget(text_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        vlayout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name = name_edit.text().strip() or "novo_workflow"
        content = text_edit.toPlainText()
        try:
            from raves.commands.workflow import WORKFLOWS_DIR

            WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)
            path = WORKFLOWS_DIR / f"{name}.yaml"
            path.write_text(content, encoding="utf-8")
            self._refresh_workflows()
        except Exception as exc:
            self.workflows_list.addItem(f"[erro] {exc}")

    def _refresh_triggers(self) -> None:
        self.triggers_list.clear()
        try:
            from raves.engine.triggers import TriggerManager

            for rule in TriggerManager().list_rules():
                self.triggers_list.addItem(f"{rule['name']} · {rule['event']} · {rule['run']}")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Aba 4: Perfil & Licença
    # ------------------------------------------------------------------

    def _build_profile_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        layout.addWidget(QLabel("Interesses aprendidos:"))
        self.interests_list = QListWidget()
        self._refresh_interests()
        layout.addWidget(self.interests_list)

        layout.addWidget(QLabel("Licença:"))
        status = current_status()
        self.license_label = QLabel(
            f"Status: {status.state} · HWID: {status.hwid} · Plano: {status.plan or '-'}"
        )
        layout.addWidget(self.license_label)

        layout.addWidget(QLabel("Chave de licença (RAVES1....):"))
        self.license_input = QLineEdit()
        layout.addWidget(self.license_input)
        activate_btn = QPushButton("Ativar licença")
        activate_btn.clicked.connect(self._on_activate_license)
        layout.addWidget(activate_btn)

        layout.addStretch(1)
        return widget

    def _refresh_interests(self) -> None:
        self.interests_list.clear()
        try:
            for item in database.get_interest_profile(limit=20):
                self.interests_list.addItem(
                    f"{item['category']} · {item['keyword']} (peso {item['effective_weight']:.2f})"
                )
        except Exception:
            pass

    def _on_activate_license(self) -> None:
        key = self.license_input.text().strip()
        if not key:
            return
        try:
            from pathlib import Path

            path = Path.home() / "AppData" / "Local" / "RAVES" / "license.key"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(key, encoding="utf-8")
            status = current_status()
            self.license_label.setText(f"Status: {status.state} · HWID: {status.hwid}")
        except Exception as exc:
            self.license_label.setText(f"Erro: {exc}")
