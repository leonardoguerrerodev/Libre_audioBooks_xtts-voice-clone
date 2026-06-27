#!/usr/bin/env python3
# gui.py — GUI Wayland nativa (Qt6/PySide6) para convertir .txt a audio
#          con Kokoro (CPU) o XTTS-v2 voz clonada (GPU).
#
# - Lanza los backends como subproceso (QProcess) → terminal real en vivo.
# - Dos barras de progreso: carga del modelo y conversión.
# - Se ejecuta en Wayland nativo (sin XWayland).

import os
import sys
import json
import shutil

# Forzar Wayland nativo (sin XWayland) antes de cargar Qt
os.environ.setdefault("QT_QPA_PLATFORM", "wayland")

from PySide6.QtCore import Qt, QProcess, QProcessEnvironment
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QRadioButton, QPushButton, QLineEdit, QLabel, QProgressBar, QPlainTextEdit,
    QFileDialog, QButtonGroup, QSizePolicy, QComboBox, QMessageBox, QSlider,
    QInputDialog,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

BACKENDS = {
    "cpu": {
        "label": "CPU · Kokoro (rápido, voz fija)",
        "venv": os.path.join(BASE_DIR, "venv"),
        "python": os.path.join(BASE_DIR, "venv", "bin", "python"),
        "script": os.path.join(BASE_DIR, "audiobook.py"),
        "needs_voice": False,
        "reqs": "requirements-cpu.txt",
    },
    "gpu": {
        "label": "GPU · XTTS-v2 (voz clonada)",
        "venv": os.path.join(BASE_DIR, "venv_xtts"),
        "python": os.path.join(BASE_DIR, "venv_xtts", "bin", "python"),
        "script": os.path.join(BASE_DIR, "audiobook_xtts.py"),
        "needs_voice": True,
        "reqs": "requirements-gpu.txt",
    },
}
VOZ_DIR = os.path.join(BASE_DIR, "voz_clonada")
VOZ_REF = os.path.join(VOZ_DIR, "clonada.wav")  # voz por defecto
PRESETS_FILE = os.path.join(BASE_DIR, "voces_config.json")  # configs guardadas


class Main(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("XTTS · Texto → Audio")
        self.resize(760, 680)
        self.proc = None
        self.play_proc = None
        self._play_after = None
        self._buf = ""
        # instalación de backends bajo demanda
        self.install_proc = None
        self._installing = None        # clave en curso, o None
        self._install_buf = ""
        # worker XTTS residente para previews rápidas
        self.worker = None
        self.worker_ready = False
        self._worker_buf = ""
        self._pending_preview = None
        self._preview_busy = False

        root = QVBoxLayout(self)

        # ── Selector de modelo ─────────────────────────────────────────
        gb = QGroupBox("Modelo / dispositivo")
        gbl = QVBoxLayout(gb)
        self.bg = QButtonGroup(self)
        self.rb_cpu = QRadioButton(BACKENDS["cpu"]["label"])
        self.rb_gpu = QRadioButton(BACKENDS["gpu"]["label"])
        self.rb_cpu.setChecked(True)
        self.bg.addButton(self.rb_cpu, 0)
        self.bg.addButton(self.rb_gpu, 1)
        gbl.addWidget(self.rb_cpu)
        gbl.addWidget(self.rb_gpu)

        # Selector de voz clonada (solo GPU)
        voice_row = QHBoxLayout()
        self.lbl_voice_sel = QLabel("Voz clonada:")
        self.cb_voice = QComboBox()
        self.cb_voice.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.btn_refresh = QPushButton("↻")
        self.btn_refresh.setToolTip("Releer la carpeta voz_clonada")
        self.btn_refresh.setFixedWidth(34)
        self.btn_refresh.clicked.connect(self.reload_voices)
        voice_row.addWidget(self.lbl_voice_sel)
        voice_row.addWidget(self.cb_voice, 1)
        voice_row.addWidget(self.btn_refresh)
        gbl.addLayout(voice_row)

        self.lbl_voice = QLabel("")
        self.lbl_voice.setWordWrap(True)
        gbl.addWidget(self.lbl_voice)
        root.addWidget(gb)
        self.rb_cpu.toggled.connect(self._update_voice_hint)
        self.rb_gpu.toggled.connect(self._update_voice_hint)
        self.cb_voice.currentIndexChanged.connect(self._update_voice_hint)
        self.bg.buttonClicked.connect(self._on_backend_clicked)
        self.reload_voices()

        # ── Prosodia / naturalidad (solo XTTS/GPU) ─────────────────────
        # Cada deslizador escribe una variable de entorno que lee
        # audiobook_xtts.py al lanzarse.
        self.gb_pros = QGroupBox("Prosodia / naturalidad (XTTS)")
        pg = QGridLayout(self.gb_pros)
        self.prosody = {}   # env -> (slider, factor, value_label)
        # (título, env, min, max, default, factor, formato, tooltip)
        specs = [
            ("Temperatura", "XTTS_TEMPERATURE", 50, 95, 75, 0.01, "{:.2f}",
             "Baja = monótona/robótica · Alta = más expresiva (y variable)"),
            ("Velocidad", "XTTS_SPEED", 85, 115, 100, 0.01, "{:.2f}",
             "1.00 normal · <1 más calmada/narrador · >1 más rápida"),
            ("Penaliz. repetición", "XTTS_REPETITION_PENALTY", 10, 100, 50, 0.1,
             "{:.1f}", "Súbela si 'tartamudea' o alarga sílabas"),
            ("Variación (top-p)", "XTTS_TOP_P", 50, 95, 85, 0.01, "{:.2f}",
             "Variedad de entonación entre frases"),
            ("Tamaño de fragmento", "XTTS_MAX_CHARS", 120, 250, 180, 1, "{:.0f}",
             "Caracteres por fragmento · más corto = menos artefactos, "
             "pero demasiado corto rompe la prosodia (~150–220)"),
        ]
        for r, (title, env, mn, mx, dflt, factor, fmt, tip) in enumerate(specs):
            lab = QLabel(title); lab.setToolTip(tip)
            sl = QSlider(Qt.Horizontal)
            sl.setMinimum(mn); sl.setMaximum(mx); sl.setValue(dflt)
            sl.setToolTip(tip)
            val = QLabel(fmt.format(dflt * factor))
            val.setFixedWidth(44)
            val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            sl.valueChanged.connect(
                lambda v, vl=val, f=factor, ft=fmt: vl.setText(ft.format(v * f)))
            pg.addWidget(lab, r, 0)
            pg.addWidget(sl, r, 1)
            pg.addWidget(val, r, 2)
            self.prosody[env] = (sl, factor, val)
        self.btn_preview = QPushButton("▶  Probar voz")
        self.btn_preview.setToolTip(
            "Genera una frase de muestra con estos ajustes y la reproduce")
        self.btn_preview.clicked.connect(self.preview)
        pg.addWidget(self.btn_preview, len(specs), 0)
        btn_reset = QPushButton("Restablecer")
        btn_reset.setToolTip("Vuelve a los valores recomendados")
        btn_reset.clicked.connect(self._reset_prosody)
        pg.addWidget(btn_reset, len(specs), 2)
        self._prosody_defaults = {
            "XTTS_TEMPERATURE": 75, "XTTS_SPEED": 100,
            "XTTS_REPETITION_PENALTY": 50, "XTTS_TOP_P": 85,
            "XTTS_MAX_CHARS": 180,
        }
        root.addWidget(self.gb_pros)

        # ── Configuraciones guardadas (voz + prosodia) ─────────────────
        self.gb_cfg = QGroupBox("Configuraciones guardadas (voz + prosodia)")
        cfg_row = QHBoxLayout(self.gb_cfg)
        cfg_row.addWidget(QLabel("Config:"))
        self.cb_preset = QComboBox()
        self.cb_preset.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.cb_preset.activated.connect(self._on_preset_selected)
        cfg_row.addWidget(self.cb_preset, 1)
        self.btn_cfg_save = QPushButton("Guardar")
        self.btn_cfg_save.setToolTip("Guardar la voz y los ajustes actuales "
                                     "(crea una nueva o sobrescribe una existente)")
        self.btn_cfg_save.clicked.connect(self.save_preset)
        self.btn_cfg_del = QPushButton("Eliminar")
        self.btn_cfg_del.setToolTip("Eliminar la configuración seleccionada")
        self.btn_cfg_del.clicked.connect(self.delete_preset)
        cfg_row.addWidget(self.btn_cfg_save)
        cfg_row.addWidget(self.btn_cfg_del)
        root.addWidget(self.gb_cfg)
        self.reload_presets()

        # ── Archivos ───────────────────────────────────────────────────
        grid = QGridLayout()
        grid.addWidget(QLabel("Archivo .txt:"), 0, 0)
        self.ed_in = QLineEdit(); self.ed_in.setReadOnly(True)
        grid.addWidget(self.ed_in, 0, 1)
        b_in = QPushButton("Examinar…"); b_in.clicked.connect(self.pick_input)
        grid.addWidget(b_in, 0, 2)

        grid.addWidget(QLabel("Carpeta destino:"), 1, 0)
        self.ed_out = QLineEdit(); self.ed_out.setReadOnly(True)
        grid.addWidget(self.ed_out, 1, 1)
        b_out = QPushButton("Examinar…"); b_out.clicked.connect(self.pick_outdir)
        grid.addWidget(b_out, 1, 2)
        root.addLayout(grid)

        # ── Botones de acción ──────────────────────────────────────────
        row = QHBoxLayout()
        self.btn_go = QPushButton("▶  Convertir a audio")
        self.btn_go.clicked.connect(self.start)
        self.btn_cancel = QPushButton("■  Cancelar")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel)
        row.addWidget(self.btn_go)
        row.addWidget(self.btn_cancel)
        root.addLayout(row)

        # ── Mantenimiento de entornos (venvs) ──────────────────────────
        gb_env = QGroupBox("Mantenimiento de entornos")
        env_grid = QGridLayout(gb_env)
        env_grid.addWidget(QLabel("Backend"), 0, 0)
        env_grid.addWidget(QLabel("Estado"), 0, 1)
        env_grid.addWidget(QLabel(""), 0, 2)
        env_grid.addWidget(QLabel(""), 0, 3)
        self.env_status = {}      # key -> QLabel
        self.env_install = {}     # key -> QPushButton
        self.env_uninstall = {}   # key -> QPushButton
        for r, key in enumerate(("cpu", "gpu"), start=1):
            name = "CPU · Kokoro" if key == "cpu" else "GPU · XTTS-v2"
            env_grid.addWidget(QLabel(name), r, 0)
            st = QLabel("—")
            self.env_status[key] = st
            env_grid.addWidget(st, r, 1)
            bi = QPushButton("Instalar")
            bi.setToolTip(f"Crea {os.path.basename(BACKENDS[key]['venv'])} e "
                          f"instala {BACKENDS[key]['reqs']} (PyTorch incluido)")
            bi.clicked.connect(lambda _=False, k=key: self.install_backend(k))
            self.env_install[key] = bi
            env_grid.addWidget(bi, r, 2)
            bu = QPushButton("Desinstalar")
            bu.setToolTip(f"Borra la carpeta {os.path.basename(BACKENDS[key]['venv'])} "
                          "para liberar espacio")
            bu.clicked.connect(lambda _=False, k=key: self.uninstall_venv(k))
            self.env_uninstall[key] = bu
            env_grid.addWidget(bu, r, 3)
        root.addWidget(gb_env)
        self._refresh_env_status()

        # ── Barras de progreso ─────────────────────────────────────────
        self.lbl_load = QLabel("Carga del modelo")
        root.addWidget(self.lbl_load)
        self.pb_load = QProgressBar(); self.pb_load.setRange(0, 100)
        root.addWidget(self.pb_load)

        self.lbl_gen = QLabel("Conversión")
        root.addWidget(self.lbl_gen)
        self.pb_gen = QProgressBar(); self.pb_gen.setRange(0, 100)
        root.addWidget(self.pb_gen)

        # ── Terminal ───────────────────────────────────────────────────
        root.addWidget(QLabel("Salida del proceso:"))
        self.term = QPlainTextEdit(); self.term.setReadOnly(True)
        self.term.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        f = QFont("monospace"); f.setStyleHint(QFont.Monospace); f.setPointSize(9)
        self.term.setFont(f)
        self.term.setStyleSheet(
            "QPlainTextEdit{background:#11141a;color:#c8e1c8;"
            "border:1px solid #333;}")
        root.addWidget(self.term)

        self._update_voice_hint()

    # ── helpers ────────────────────────────────────────────────────────
    def _backend_key(self):
        return "gpu" if self.rb_gpu.isChecked() else "cpu"

    def _venv_installed(self, key):
        return os.path.isfile(BACKENDS[key]["python"])

    def _reset_prosody(self):
        for env, val in self._prosody_defaults.items():
            self.prosody[env][0].setValue(val)

    def _prosody_env(self):
        """Devuelve {VAR: valor} con los ajustes actuales de los deslizadores."""
        out = {}
        for env, (sl, factor, _val) in self.prosody.items():
            out[env] = f"{sl.value() * factor:.3f}"
        return out

    # ── configuraciones guardadas (presets) ─────────────────────────────
    def _load_presets(self):
        """Lee el archivo JSON de configuraciones (o {} si no existe/está mal)."""
        try:
            with open(PRESETS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write_presets(self, data):
        try:
            with open(PRESETS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except OSError as e:
            self.log(f"✗ No se pudo guardar configuraciones: {e}", "#ff6b6b")
            return False

    def reload_presets(self, select=None):
        presets = self._load_presets()
        self.cb_preset.blockSignals(True)
        self.cb_preset.clear()
        self.cb_preset.addItem("— sin guardar —", None)
        for name in sorted(presets, key=str.lower):
            self.cb_preset.addItem(name, name)
        idx = self.cb_preset.findData(select) if select else 0
        self.cb_preset.setCurrentIndex(idx if idx >= 0 else 0)
        self.cb_preset.blockSignals(False)
        has_sel = self.cb_preset.currentData() is not None
        self.btn_cfg_del.setEnabled(has_sel)

    def _on_preset_selected(self, _idx):
        name = self.cb_preset.currentData()
        self.btn_cfg_del.setEnabled(name is not None)
        if not name:
            return
        cfg = self._load_presets().get(name)
        if not cfg:
            return
        # aplicar voz (si existe en el combo)
        voice = cfg.get("voice")
        if voice:
            vi = self.cb_voice.findText(voice)
            if vi >= 0:
                self.cb_voice.setCurrentIndex(vi)
            else:
                self.log(f"⚠ La voz «{voice}» de esta config ya no está en "
                         "voz_clonada.", "#ffcc66")
        # aplicar deslizadores (valores ya en escala de slider)
        for env, (sl, _factor, _val) in self.prosody.items():
            if env in cfg.get("sliders", {}):
                sl.setValue(int(cfg["sliders"][env]))
        self.log(f"• Config cargada: {name}", "#7fd1ff")

    def _current_config(self):
        voz = self.selected_voice()
        return {
            "voice": os.path.basename(voz) if voz else None,
            "sliders": {env: sl.value()
                        for env, (sl, _f, _v) in self.prosody.items()},
        }

    def save_preset(self):
        presets = self._load_presets()
        current = self.cb_preset.currentData() or ""
        name, ok = QInputDialog.getText(
            self, "Guardar configuración",
            "Nombre de la configuración:", text=current)
        name = name.strip()
        if not ok or not name:
            return
        if name in presets:
            if QMessageBox.question(
                    self, "Sobrescribir",
                    f"Ya existe «{name}». ¿Sobrescribirla?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No) != QMessageBox.Yes:
                return
        presets[name] = self._current_config()
        if self._write_presets(presets):
            self.reload_presets(select=name)
            self.log(f"✓ Configuración guardada: {name}", "#7CFC00")

    def delete_preset(self):
        name = self.cb_preset.currentData()
        if not name:
            return
        if QMessageBox.question(
                self, "Eliminar configuración",
                f"¿Eliminar la configuración «{name}»?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No) != QMessageBox.Yes:
            return
        presets = self._load_presets()
        presets.pop(name, None)
        if self._write_presets(presets):
            self.reload_presets()
            self.log(f"🗑  Configuración eliminada: {name}", "#ffcc66")

    def _refresh_env_status(self):
        """Actualiza etiquetas de estado y botones Instalar/Desinstalar."""
        radios = {"cpu": self.rb_cpu, "gpu": self.rb_gpu}
        busy = self._installing is not None
        for key in ("cpu", "gpu"):
            installed = self._venv_installed(key)
            st = self.env_status[key]
            if self._installing == key:
                st.setText("⏳ instalando…"); st.setStyleSheet("color:#b58900;")
            elif installed:
                st.setText("✓ instalado"); st.setStyleSheet("color:#2e7d32;")
            else:
                st.setText("✗ no instalado"); st.setStyleSheet("color:#c62828;")
            self.env_install[key].setEnabled(not installed and not busy)
            self.env_uninstall[key].setEnabled(installed and not busy)
            # el modelo siempre se puede seleccionar: si no está, se ofrece instalar
            radios[key].setToolTip("" if installed else
                                   "No instalado — al seleccionarlo se ofrece instalarlo")

    def _on_backend_clicked(self, _btn):
        """Si eligen un backend no instalado, ofrecer instalarlo al momento."""
        key = self._backend_key()
        if not self._venv_installed(key) and self._installing is None:
            self.install_backend(key, ask=True)

    # ── instalación de backends bajo demanda ────────────────────────────
    def install_backend(self, key, ask=True):
        if self._installing is not None:
            self.log("⏳ Ya hay una instalación en curso.", "#ffcc66"); return
        if self._venv_installed(key):
            return
        name = "CPU · Kokoro" if key == "cpu" else "GPU · XTTS-v2"
        script = os.path.join(BASE_DIR, "install_backend.sh")
        if not os.path.isfile(script):
            self.log(f"✗ Falta {script}", "#ff6b6b"); return
        extra = ("\n\nDescargará PyTorch con CUDA (varios GB); puede tardar."
                 if key == "gpu" else
                 "\n\nDescargará PyTorch (CPU) y dependencias.")
        if ask and QMessageBox.question(
                self, "Instalar backend",
                f"¿Instalar el entorno «{name}»?\n"
                f"Se creará {os.path.basename(BACKENDS[key]['venv'])}/ con "
                f"{BACKENDS[key]['reqs']}.{extra}",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No) != QMessageBox.Yes:
            return

        self._installing = key
        self._install_buf = ""
        self.term.clear()
        self.btn_go.setEnabled(False)
        self.btn_preview.setEnabled(False)
        self.pb_load.setRange(0, 0)            # barra "ocupada"
        self.lbl_load.setText(f"Instalando {name} (mira la terminal)…")
        self._refresh_env_status()
        self.log(f"⚙ Instalando backend «{name}»…", "#7fd1ff")

        env = self._base_env()
        py3 = shutil.which("python3") or "python3"
        env.insert("PYTHON", py3)
        self.install_proc = QProcess(self)
        self.install_proc.setProcessEnvironment(env)
        self.install_proc.setWorkingDirectory(BASE_DIR)
        self.install_proc.setProcessChannelMode(QProcess.MergedChannels)
        self.install_proc.readyReadStandardOutput.connect(self._on_install_out)
        self.install_proc.finished.connect(self._on_install_finished)
        self.install_proc.errorOccurred.connect(
            lambda e: self.log(f"✗ Error del instalador: {e}", "#ff6b6b"))
        self.install_proc.start("bash", [script, key])

    def _on_install_out(self):
        self._install_buf += bytes(
            self.install_proc.readAllStandardOutput()).decode("utf-8", "replace")
        while "\n" in self._install_buf:
            line, self._install_buf = self._install_buf.split("\n", 1)
            if line.strip():
                self.log(line)

    def _on_install_finished(self, code, _status):
        key = self._installing
        self._installing = None
        self.install_proc = None
        self.pb_load.setRange(0, 100); self.pb_load.setValue(0)
        self.lbl_load.setText("Carga del modelo")
        self.btn_go.setEnabled(True)
        self.btn_preview.setEnabled(self._venv_installed("gpu"))
        if code == 0 and self._venv_installed(key):
            self.log("✓ Backend instalado.", "#7CFC00")
        else:
            self.log(f"✗ La instalación falló (código {code}).", "#ff6b6b")
        self._refresh_env_status()
        self._update_voice_hint()

    def uninstall_venv(self, key):
        bk = BACKENDS[key]
        venv_dir = bk["venv"]
        name = "CPU · Kokoro" if key == "cpu" else "GPU · XTTS-v2"
        if not os.path.isdir(venv_dir):
            self._refresh_env_status()
            return
        # no permitir borrar el entorno mientras se está usando
        if self.proc and self.proc.state() != QProcess.NotRunning \
                and self._backend_key() == key:
            QMessageBox.warning(
                self, "En uso",
                "Hay una conversión en curso con este backend. "
                "Cancélala antes de desinstalarlo.")
            return

        running_from_here = os.path.abspath(sys.executable).startswith(
            os.path.abspath(venv_dir) + os.sep)
        msg = (f"¿Borrar el entorno «{name}»?\n\n"
               f"Se eliminará la carpeta:\n{venv_dir}\n\n"
               f"Podrás reinstalarlo desde aquí cuando quieras.")
        if running_from_here:
            msg += ("\n\n⚠  La GUI se está ejecutando con este entorno. "
                    "Podrás seguir usándola ahora, pero al cerrarla no "
                    "volverá a abrirse hasta reinstalarlo.")
        if QMessageBox.question(
                self, "Desinstalar entorno", msg,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            shutil.rmtree(venv_dir)
            self.log(f"🗑  Entorno «{name}» desinstalado: {venv_dir}", "#ffcc66")
        except OSError as e:
            self.log(f"✗ No se pudo borrar {venv_dir}: {e}", "#ff6b6b")
            QMessageBox.critical(self, "Error", f"No se pudo borrar:\n{e}")
        self._refresh_env_status()

    def uninstall_venv(self, key):
        bk = BACKENDS[key]
        venv_dir = bk["venv"]
        name = "CPU · Kokoro" if key == "cpu" else "GPU · XTTS-v2"
        if not os.path.isdir(venv_dir):
            self._refresh_env_status()
            return
        # no permitir borrar el entorno mientras se está usando
        if self.proc and self.proc.state() != QProcess.NotRunning \
                and self._backend_key() == key:
            QMessageBox.warning(
                self, "En uso",
                "Hay una conversión en curso con este backend. "
                "Cancélala antes de desinstalarlo.")
            return

        running_from_here = os.path.abspath(sys.executable).startswith(
            os.path.abspath(venv_dir) + os.sep)
        msg = (f"¿Borrar el entorno «{name}»?\n\n"
               f"Se eliminará la carpeta:\n{venv_dir}\n\n"
               f"Reinstálalo cuando quieras con:\n"
               f"    pip install -r {bk['reqs']}")
        if running_from_here:
            msg += ("\n\n⚠  La GUI se está ejecutando con este entorno. "
                    "Podrás seguir usándola ahora, pero al cerrarla no "
                    "volverá a abrirse hasta reinstalarlo.")
        if QMessageBox.question(
                self, "Desinstalar entorno", msg,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            shutil.rmtree(venv_dir)
            self.log(f"🗑  Entorno «{name}» desinstalado: {venv_dir}", "#ffcc66")
        except OSError as e:
            self.log(f"✗ No se pudo borrar {venv_dir}: {e}", "#ff6b6b")
            QMessageBox.critical(self, "Error", f"No se pudo borrar:\n{e}")
        self._refresh_env_status()

    def reload_voices(self):
        """Relee voz_clonada y llena el combo con los .wav (nombre sin extensión)."""
        prev = self.cb_voice.currentData()
        self.cb_voice.blockSignals(True)
        self.cb_voice.clear()
        wavs = []
        if os.path.isdir(VOZ_DIR):
            wavs = sorted(
                (f for f in os.listdir(VOZ_DIR) if f.lower().endswith(".wav")),
                key=str.lower)
        for f in wavs:
            stem = os.path.splitext(f)[0]            # nombre sin extensión
            self.cb_voice.addItem(stem, os.path.join(VOZ_DIR, f))
        # restaurar selección previa o preferir clonada.wav
        idx = self.cb_voice.findData(prev) if prev else -1
        if idx < 0:
            idx = self.cb_voice.findData(VOZ_REF)
        self.cb_voice.setCurrentIndex(idx if idx >= 0 else 0)
        self.cb_voice.blockSignals(False)
        self._update_voice_hint()

    def selected_voice(self):
        """Ruta del .wav elegido en el combo (o None si no hay ninguno)."""
        return self.cb_voice.currentData()

    def _update_voice_hint(self):
        is_gpu = self._backend_key() == "gpu"
        # el selector de voz y la prosodia solo aplican al modo GPU
        self.lbl_voice_sel.setEnabled(is_gpu)
        self.cb_voice.setEnabled(is_gpu)
        self.btn_refresh.setEnabled(is_gpu)
        if hasattr(self, "gb_pros"):
            self.gb_pros.setEnabled(is_gpu)
        if hasattr(self, "gb_cfg"):
            self.gb_cfg.setEnabled(is_gpu)
        if is_gpu:
            voz = self.selected_voice()
            if voz and os.path.isfile(voz):
                self.lbl_voice.setText(f"✓ Usando: {os.path.basename(voz)}")
                self.lbl_voice.setStyleSheet("color:#2e7d32;")
            else:
                self.lbl_voice.setText(
                    "✗ No hay ningún .wav en voz_clonada — grábalo con "
                    "voz_clonada/grabar_muestras.sh")
                self.lbl_voice.setStyleSheet("color:#c62828;")
        else:
            self.lbl_voice.setText("Voz fija española (ef_dora).")
            self.lbl_voice.setStyleSheet("color:#777;")

    def log(self, text, color=None):
        if color:
            self.term.appendHtml(
                f'<span style="color:{color}">{text}</span>')
        else:
            self.term.appendPlainText(text)
        self.term.moveCursor(QTextCursor.End)

    # ── selección de archivos ──────────────────────────────────────────
    def pick_input(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Selecciona el .txt", BASE_DIR, "Texto (*.txt);;Todos (*)")
        if path:
            self.ed_in.setText(path)
            if not self.ed_out.text():
                self.ed_out.setText(os.path.dirname(path))

    def pick_outdir(self):
        path = QFileDialog.getExistingDirectory(
            self, "Carpeta de destino", self.ed_out.text() or BASE_DIR)
        if path:
            self.ed_out.setText(path)

    # ── ejecución ──────────────────────────────────────────────────────
    def start(self):
        if self._installing is not None:
            self.log("⏳ Espera a que termine la instalación.", "#ffcc66"); return
        key = self._backend_key()
        bk = BACKENDS[key]
        # backend no instalado → ofrecer instalarlo en vez de fallar
        if not self._venv_installed(key):
            self.log("• Ese backend no está instalado; ofreciendo instalación…",
                     "#ffcc66")
            self.install_backend(key, ask=True)
            return
        inp = self.ed_in.text().strip()
        outd = self.ed_out.text().strip()

        if not inp or not os.path.isfile(inp):
            self.log("✗ Selecciona un archivo .txt válido.", "#ff6b6b"); return
        if not outd or not os.path.isdir(outd):
            self.log("✗ Selecciona una carpeta de destino válida.", "#ff6b6b"); return
        voz = self.selected_voice()
        if bk["needs_voice"] and (not voz or not os.path.isfile(voz)):
            self.log("✗ Selecciona una voz clonada válida (carpeta voz_clonada).", "#ff6b6b"); return

        stem = os.path.splitext(os.path.basename(inp))[0]
        outp = os.path.join(outd, stem + ".wav")

        # reset UI
        self.pb_load.setValue(0); self.pb_gen.setValue(0)
        self.lbl_load.setText("Carga del modelo")
        self.lbl_gen.setText("Conversión")
        self.term.clear()
        self.btn_go.setEnabled(False); self.btn_cancel.setEnabled(True)

        args = [bk["script"], inp, outp]
        if bk["needs_voice"]:
            args.append(voz)
            self.log(f"• Voz clonada: {os.path.basename(voz)}", "#7fd1ff")
        self.log(f"$ {bk['python']} {os.path.basename(bk['script'])} "
                 f"{inp} {outp}", "#7fd1ff")

        env = self._base_env()
        if self._backend_key() == "gpu":
            for k, v in self._prosody_env().items():
                env.insert(k, v)

        self._play_after = None
        self._launch(bk["python"], args, env)

    def _base_env(self):
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")
        env.insert("TTS_HOME", os.path.join(BASE_DIR, "models"))
        env.insert("COQUI_TOS_AGREED", "1")
        return env

    def _launch(self, python, args, env):
        self.proc = QProcess(self)
        self.proc.setProcessEnvironment(env)
        self.proc.setWorkingDirectory(BASE_DIR)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.readyReadStandardOutput.connect(self.on_output)
        self.proc.finished.connect(self.on_finished)
        self.proc.errorOccurred.connect(
            lambda e: self.log(f"✗ Error de proceso: {e}", "#ff6b6b"))
        self._buf = ""
        self.proc.start(python, args)

    # ── prueba de voz (preview rápida vía worker residente) ─────────────
    # Frase corta (~10 palabras) con entonación variada → preview rápida.
    SAMPLE_TEXT = "Hola, esta es mi voz. ¿Suena natural así?"

    def preview(self):
        if self.proc and self.proc.state() != QProcess.NotRunning:
            self.log("⏳ Espera a que termine la conversión en curso.", "#ffcc66")
            return
        if self._preview_busy:
            self.log("⏳ Prueba en curso…", "#ffcc66"); return
        bk = BACKENDS["gpu"]
        if not os.path.isfile(bk["python"]):
            self.log(f"✗ No existe el intérprete: {bk['python']}", "#ff6b6b"); return
        voz = self.selected_voice()
        if not voz or not os.path.isfile(voz):
            self.log("✗ Selecciona una voz clonada válida para la prueba.", "#ff6b6b"); return

        tmpdir = os.path.join(BASE_DIR, "models", ".preview")
        os.makedirs(tmpdir, exist_ok=True)
        sample_wav = os.path.join(tmpdir, "muestra.wav")
        pro = self._prosody_env()
        req = {
            "text": self.SAMPLE_TEXT,
            "voice": voz,
            "out": sample_wav,
            "temperature": float(pro["XTTS_TEMPERATURE"]),
            "speed": float(pro["XTTS_SPEED"]),
            "repetition_penalty": float(pro["XTTS_REPETITION_PENALTY"]),
            "top_p": float(pro["XTTS_TOP_P"]),
        }

        self._preview_busy = True
        self.btn_go.setEnabled(False); self.btn_preview.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.pb_gen.setRange(0, 0)   # barra "ocupada" (indeterminada)
        self.lbl_gen.setText("Prueba de voz")
        self.log(f"▶ Prueba con {os.path.basename(voz)} · {pro}", "#7fd1ff")

        if self.worker and self.worker.state() != QProcess.NotRunning:
            if self.worker_ready:
                self._send_preview(req)
            else:
                self._pending_preview = req      # aún cargando
        else:
            self._pending_preview = req
            self._start_worker(bk["python"])

    def _start_worker(self, python):
        self.worker_ready = False
        self._worker_buf = ""
        self.lbl_load.setText("Cargando worker XTTS (solo la 1ª vez)…")
        self.pb_load.setRange(0, 0)
        env = self._base_env()
        self.worker = QProcess(self)
        self.worker.setProcessEnvironment(env)
        self.worker.setWorkingDirectory(BASE_DIR)
        self.worker.setProcessChannelMode(QProcess.MergedChannels)
        self.worker.readyReadStandardOutput.connect(self._on_worker_out)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.start(python, [os.path.join(BASE_DIR, "xtts_worker.py")])

    def _send_preview(self, req):
        try:
            self.worker.write((json.dumps(req) + "\n").encode("utf-8"))
        except Exception as e:   # noqa: BLE001
            self.log(f"✗ No se pudo enviar al worker: {e}", "#ff6b6b")
            self._end_preview()

    def _on_worker_out(self):
        self._worker_buf += bytes(
            self.worker.readAllStandardOutput()).decode("utf-8", "replace")
        while "\n" in self._worker_buf:
            line, self._worker_buf = self._worker_buf.split("\n", 1)
            line = line.rstrip()
            if line == "@READY":
                self.worker_ready = True
                self.pb_load.setRange(0, 100); self.pb_load.setValue(100)
                self.lbl_load.setText("Worker XTTS listo (en memoria)")
                if self._pending_preview:
                    self._send_preview(self._pending_preview)
                    self._pending_preview = None
            elif line.startswith("@DONE|"):
                path = line.split("|", 1)[1]
                self.log("✓ Prueba lista.", "#7CFC00")
                self._play_wav(path)
                self._end_preview()
            elif line.startswith("@ERR|"):
                self.log(f"✗ {line.split('|', 1)[1]}", "#ff6b6b")
                self._end_preview()
            elif line.strip():
                self.log(line)

    def _on_worker_finished(self, _code, _status):
        self.worker_ready = False
        self.worker = None
        if self._preview_busy:
            self._end_preview()

    def _end_preview(self):
        self._preview_busy = False
        self.pb_gen.setRange(0, 100)
        self.btn_go.setEnabled(True)
        self.btn_preview.setEnabled(self._venv_installed("gpu"))
        self.btn_cancel.setEnabled(False)

    def _play_wav(self, path):
        if not os.path.isfile(path):
            return
        for player in ("pw-play", "paplay", "aplay", "ffplay", "play"):
            exe = shutil.which(player)
            if not exe:
                continue
            pa = [exe]
            if player == "ffplay":
                pa += ["-nodisp", "-autoexit", "-loglevel", "quiet"]
            pa.append(path)
            self.play_proc = QProcess(self)
            self.play_proc.start(pa[0], pa[1:])
            self.log(f"🔊 Reproduciendo muestra ({player})…", "#7CFC00")
            return
        self.log(f"♪ Muestra guardada en: {path} (no encontré reproductor)",
                 "#ffcc66")

    def cancel(self):
        if self.proc and self.proc.state() != QProcess.NotRunning:
            self.proc.kill()
            self.log("■ Cancelado por el usuario.", "#ffcc66")
        elif self._preview_busy and self.worker:
            # matar el worker corta la prueba (y libera la GPU)
            self.worker.kill()
            self.log("■ Prueba cancelada.", "#ffcc66")

    def closeEvent(self, event):
        # cerrar el worker residente al salir para no dejar la GPU ocupada
        if self.worker and self.worker.state() != QProcess.NotRunning:
            try:
                self.worker.write(b'{"cmd": "quit"}\n')
                self.worker.waitForBytesWritten(200)
            except Exception:   # noqa: BLE001
                pass
            self.worker.terminate()
            if not self.worker.waitForFinished(1500):
                self.worker.kill()
        super().closeEvent(event)

    def on_output(self):
        data = bytes(self.proc.readAllStandardOutput()).decode(
            "utf-8", errors="replace")
        self._buf += data
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self.handle_line(line)

    def handle_line(self, line):
        if line.startswith("@PROGRESS|"):
            parts = line.split("|")
            if len(parts) >= 4:
                phase, val, extra = parts[1], parts[2], parts[3]
                if phase == "load":
                    try:
                        self.pb_load.setValue(int(float(val) * 100))
                    except ValueError:
                        pass
                    self.lbl_load.setText(f"Carga del modelo — {extra}")
                elif phase == "gen":
                    try:
                        done = int(val); total = max(1, int(extra))
                        self.pb_gen.setValue(int(done * 100 / total))
                        self.lbl_gen.setText(
                            f"Conversión — fragmento {done}/{total}")
                    except ValueError:
                        pass
            return
        if line.strip():
            self.log(line)

    def on_finished(self, code, _status):
        self.btn_go.setEnabled(True); self.btn_cancel.setEnabled(False)
        self.btn_preview.setEnabled(self._venv_installed("gpu"))
        if code == 0:
            self.pb_gen.setValue(100)
            self.log("✓ Conversión finalizada.", "#7CFC00")
        else:
            self.log(f"✗ El proceso terminó con código {code}.", "#ff6b6b")
        self.proc = None


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("XTTS Texto a Audio")
    w = Main()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
