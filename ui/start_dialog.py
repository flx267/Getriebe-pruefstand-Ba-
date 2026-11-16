"""Startdialog – Prüfdaten eingeben (Vorgaben Nutzer 27.10.2026).

Vorbelegung der Felder:
  Prüfnummer               – fortlaufender Zähler ab 00000 (Session-Datei), nicht editierbar
  Prüfer, Auftragsnummer   – nur innerhalb eines Programmlaufs („Neue Prüfung“), nach Exe-Start leer
  Baß/Kunden Artikel-Nr.,
  Getriebetyp              – dauerhaft (Session-Datei)
  Serien-Nr., Kommentar    – immer leer
Alles außer dem Kommentar ist Pflicht.
"""

import json
from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLineEdit, QSpinBox, QVBoxLayout, QWidget,
)

import config.settings as _settings
from config.settings import APP_NAME, APP_VERSION, SESSION_FILE
from ui import icons, theme
from ui.settings_dialog import GrenzwerteDialog, apply_grenzwerte_to_settings


# Nur für diesen Programmlauf (Prüfer, Auftragsnummer) – nach Exe-Neustart leer
_RUN_MEMORY: dict[str, str] = {}

# Dauerhaft gemerkte Felder (Schlüssel in der Session-Datei)
_PERSISTENT = ("bass_artikel_nr", "getriebetyp", "kunden_artikel_nr")
# Frühere Schlüssel, die nicht mehr gemerkt werden dürfen
_OBSOLETE = ("prufer", "pruefnummer", "auftragsnummer")


def _load_session() -> dict:
    try:
        return json.loads(SESSION_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _next_pruefnummer(session: dict) -> int:
    try:
        return max(0, int(session.get("next_pruefnummer", 0)))
    except (TypeError, ValueError):
        return 0


def _save_session(updates: dict) -> None:
    try:
        session = _load_session()
        for key in _OBSOLETE:
            session.pop(key, None)
        session.update(updates)
        SESSION_FILE.write_text(
            json.dumps(session, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


class StartDialog(QDialog):

    def __init__(self, simulated: bool = False):
        super().__init__()
        self._simulated = simulated
        self.setWindowTitle(APP_NAME)
        self.setMinimumWidth(480)
        self._values: dict[str, str] = {}
        self._messzeiten: dict[str, int] = {}
        self._next_num = _next_pruefnummer(_load_session())
        # Gespeicherte Einstellungen (u. a. Messzeit-Maxima) vor dem Aufbau übernehmen
        apply_grenzwerte_to_settings()
        self._build()
        self._prefill()
        # Vollbild (maximiert) – alle Felder in zwei Spalten, kein Scrollen nötig
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint
                            | Qt.WindowType.WindowMinimizeButtonHint)
        self.setWindowState(Qt.WindowState.WindowMaximized)

    def _build(self) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.addStretch()

        content = QWidget()
        content.setMaximumWidth(1100)
        outer.addWidget(content, stretch=100)
        outer.addStretch()

        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # Kopf: Logo + Titel, darunter Version/Modus
        head = QHBoxLayout()
        head.setSpacing(12)
        logo = theme.label("", "logo")
        logo.setPixmap(icons.pixmap("logo", theme.MUTED, 30))
        title = theme.label(APP_NAME, "h1")
        mode = "SIMULATION" if self._simulated else "USB-4711A"
        subtitle = theme.label(f"v{APP_VERSION}  ·  {mode}", "pill",
                               "warn" if self._simulated else None)
        head.addStretch()
        head.addWidget(logo)
        head.addWidget(title)
        head.addWidget(subtitle)
        head.addStretch()

        def field(text: str, edit: QWidget) -> list[QWidget]:
            edit.setProperty("size", "lg")
            return [theme.label(text, "field"), edit]

        self._version_edit = QLineEdit(APP_VERSION)
        self._version_edit.setReadOnly(True)
        self._num_edit = QLineEdit(f"{self._next_num:05d}")
        self._num_edit.setReadOnly(True)
        self._num_edit.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._date_edit = QLineEdit(datetime.now().strftime("%d.%m.%Y"))
        self._date_edit.setReadOnly(True)

        # Pflichtfelder in Eingabereihenfolge: (Schlüssel, Beschriftung, Platzhalter)
        self._edits: dict[str, QLineEdit] = {}
        for key, placeholder in (
            ("prufer", "z. B. Max Mustermann"),
            ("auftragsnummer", "z. B. AUF-2026-042"),
            ("bass_artikel_nr", "z. B. 123456"),
            ("getriebetyp", "z. B. GFRS-42"),
            ("kunden_artikel_nr", "z. B. 0007654321"),
            ("getriebeseriennummer", "z. B. SN-2026-00123"),
            ("kraftmessbolzen_seriennummer", "z. B. KMB-0007"),
            ("kommentar", "(optional)"),
        ):
            edit = QLineEdit()
            edit.setPlaceholderText(placeholder)
            edit.returnPressed.connect(self._on_start)
            self._edits[key] = edit

        self._t1_spin = QSpinBox()
        self._t1_spin.setRange(1, _settings.MAX_STEP1_DURATION_MINUTES)
        self._t1_spin.setValue(_settings.STEP1_DURATION_MINUTES)
        self._t2_spin = QSpinBox()
        self._t2_spin.setRange(1, _settings.MAX_STEP2_DURATION_SECONDS)
        self._t2_spin.setValue(_settings.STEP2_DURATION_SECONDS)
        self._t3_spin = QSpinBox()
        self._t3_spin.setRange(1, _settings.MAX_STEP3_DURATION_SECONDS)
        self._t3_spin.setValue(_settings.STEP3_DURATION_SECONDS)
        for spin in (self._t1_spin, self._t2_spin, self._t3_spin):
            spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)

        self._error_label = theme.label("", None, "crit")
        self._error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._start_btn = theme.button("Test starten  →", "primary", height=52)
        self._start_btn.setFont(theme.font(12))
        self._start_btn.clicked.connect(self._on_start)

        grenzwerte_row = QHBoxLayout()
        grenzwerte_row.addStretch()
        grenzwerte_btn = theme.button("Einstellungen", "ghost", "sliders", height=34)
        grenzwerte_btn.clicked.connect(self._on_grenzwerte)
        grenzwerte_row.addWidget(grenzwerte_btn)

        def panel(*items) -> QWidget:
            frame = theme.frame("panel")
            col = QVBoxLayout(frame)
            col.setContentsMargins(22, 18, 22, 18)
            col.setSpacing(6)
            for item in items:
                if isinstance(item, QHBoxLayout):
                    col.addLayout(item)
                else:
                    col.addWidget(item)
            col.addStretch()
            return frame

        e = self._edits
        left = panel(theme.overline("Prüfdaten"),
                     *field("Software Version", self._version_edit),
                     *field("Prüfnummer  (automatisch)", self._num_edit),
                     *field("Prüfer *", e["prufer"]),
                     *field("Auftragsnummer *", e["auftragsnummer"]),
                     *field("Baß Artikel-Nr. *", e["bass_artikel_nr"]),
                     *field("Getriebetyp *", e["getriebetyp"]),
                     *field("Kunden Artikel-Nr. *", e["kunden_artikel_nr"]))
        right = panel(theme.overline("Prüfling"),
                      *field("Serien-Nr. Getriebe *", e["getriebeseriennummer"]),
                      *field("Serien-Nr. Kraftmessbolzen *", e["kraftmessbolzen_seriennummer"]),
                      *field("Kommentar", e["kommentar"]),
                      *field("Datum", self._date_edit),
                      theme.separator(),
                      theme.overline("Messzeiten"),
                      *field("Lastlauf (Vibration / Temperatur)  [min]", self._t1_spin),
                      *field("Leckage – Haltezeit  [s]", self._t2_spin),
                      *field("Kraftprüfung – Haltezeit  [s]", self._t3_spin),
                      grenzwerte_row)
        columns = QHBoxLayout()
        columns.setSpacing(16)
        columns.addWidget(left, stretch=1)
        columns.addWidget(right, stretch=1)

        layout.addLayout(head)
        layout.addSpacing(4)
        layout.addLayout(columns, stretch=1)
        layout.addWidget(self._error_label)
        layout.addWidget(self._start_btn)

    def _prefill(self) -> None:
        session = _load_session()
        for key in ("prufer", "auftragsnummer"):
            self._edits[key].setText(_RUN_MEMORY.get(key, ""))
        for key in _PERSISTENT:
            if isinstance(session.get(key), str):
                self._edits[key].setText(session[key])
        # Fokus aufs erste leere Pflichtfeld
        empty = [ed for k, ed in self._edits.items() if k != "kommentar" and not ed.text().strip()]
        (empty[0] if empty else self._edits["kommentar"]).setFocus()
        mz = session.get("messzeiten", {})
        if "step1_min" in mz:
            self._t1_spin.setValue(min(mz["step1_min"], _settings.MAX_STEP1_DURATION_MINUTES))
        if "step2_sec" in mz:
            self._t2_spin.setValue(min(mz["step2_sec"], _settings.MAX_STEP2_DURATION_SECONDS))
        if "step3_sec" in mz:
            self._t3_spin.setValue(min(mz["step3_sec"], _settings.MAX_STEP3_DURATION_SECONDS))

    def _on_grenzwerte(self) -> None:
        GrenzwerteDialog(self).exec()
        # Neue Maximalwerte sofort in den Messzeit-Feldern übernehmen
        self._t1_spin.setMaximum(_settings.MAX_STEP1_DURATION_MINUTES)
        self._t2_spin.setMaximum(_settings.MAX_STEP2_DURATION_SECONDS)
        self._t3_spin.setMaximum(_settings.MAX_STEP3_DURATION_SECONDS)

    def _on_start(self) -> None:
        names = {
            "prufer": "Prüfer", "auftragsnummer": "Auftragsnummer",
            "bass_artikel_nr": "Baß Artikel-Nr.", "getriebetyp": "Getriebetyp",
            "kunden_artikel_nr": "Kunden Artikel-Nr.",
            "getriebeseriennummer": "Serien-Nr. Getriebe",
            "kraftmessbolzen_seriennummer": "Serien-Nr. Kraftmessbolzen",
        }
        for key, label in names.items():
            if not self._edits[key].text().strip():
                self._error_label.setText(f"Bitte {label} eingeben.")
                self._edits[key].setFocus()
                return
        self._values = {k: ed.text().strip() for k, ed in self._edits.items()}
        self._messzeiten = mz = {
            "step1_min": self._t1_spin.value(),
            "step2_sec": self._t2_spin.value(),
            "step3_sec": self._t3_spin.value(),
        }
        apply_grenzwerte_to_settings()
        _settings.step_by_action("run")["duration_seconds"] = mz["step1_min"] * 60
        _settings.step_by_action("leak")["hold_seconds"] = mz["step2_sec"]
        _settings.step_by_action("torque")["hold_seconds"] = mz["step3_sec"]
        self.accept()

    def commit(self) -> None:
        """Prüfung startet wirklich (Messkarte verbunden): Prüfnummer verbrauchen und Werte
        merken. Erst hier, damit bei „Keine Verbindung“ keine Nummer verloren geht."""
        for key in ("prufer", "auftragsnummer"):
            _RUN_MEMORY[key] = self._values[key]
        updates = {key: self._values[key] for key in _PERSISTENT}
        updates["next_pruefnummer"] = self._next_num + 1
        updates["messzeiten"] = self._messzeiten
        _save_session(updates)

    @property
    def prufer(self) -> str:
        return self._values.get("prufer", "")

    @property
    def pruefnummer(self) -> str:
        return f"{self._next_num:05d}"

    @property
    def auftragsnummer(self) -> str:
        return self._values.get("auftragsnummer", "")

    @property
    def bass_artikel_nr(self) -> str:
        return self._values.get("bass_artikel_nr", "")

    @property
    def getriebetyp(self) -> str:
        return self._values.get("getriebetyp", "")

    @property
    def kunden_artikel_nr(self) -> str:
        return self._values.get("kunden_artikel_nr", "")

    @property
    def getriebeseriennummer(self) -> str:
        return self._values.get("getriebeseriennummer", "")

    @property
    def kraftmessbolzen_seriennummer(self) -> str:
        return self._values.get("kraftmessbolzen_seriennummer", "")

    @property
    def kommentar(self) -> str:
        return self._values.get("kommentar", "")
