import json

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QSpinBox, QVBoxLayout, QWidget,
)

import config.settings as _settings
from config.settings import SESSION_FILE, SENSORS
from ui import theme

# Live bewertete Sensoren: (sensor_id, Anzeige, Einheit) – Warnung / Kritisch
_SENSOR_ROWS = [
    ("vibration",    "Vibration",     "mm/s"),
    ("temperature",  "Temperatur T1", "°C"),
    ("temperature2", "Temperatur T2", "°C"),
]

# Einzelwerte in config.settings: (Attribut, Anzeige, Einheit, Nachkommastellen)
_PARAM_ROWS = [
    ("LEAK_FILL_S",             "Leckage: Befüllzeit",              "s",   1),
    ("LEAK_SETTLE_S",           "Leckage: Beruhigungszeit vor Messung", "s", 1),
    ("LEAK_VENT_STEP_S",        "Leckage: Entlüftungszeit",         "s",   1),
    ("LEAK_WARN_DROP_BAR",      "Leckage: Druckabfall Warnung ab",  "bar", 3),
    ("LEAK_CRITICAL_DROP_BAR",  "Leckage: Druckabfall kritisch ab", "bar", 3),
    ("LEAK_MIN_FILL_BAR",       "Leckage: Mindest-Befülldruck",     "bar", 2),
    ("TORQUE_PASS_NM",          "Kraft: bestanden ab",              "Nm",  1),
    ("MOTOR_RUN_RPM",           "Lastlauf: Motordrehzahl",          "rpm", 0),
    ("RUN_SETTLE_S",            "Lastlauf: erste Sekunden nicht bewerten", "s", 1),
    ("RPM1_WARN_PCT",           "Lastlauf: RPM1-Abweichung Warnung ab",  "%", 1),
    ("RPM1_CRITICAL_PCT",       "Lastlauf: RPM1-Abweichung kritisch ab", "%", 1),
    ("RPM1_FACTOR",             "RPM1: Faktor (rpm = Hz × Faktor)",   "rpm/Hz", 4),
]

# Prüfbericht – gleiche Speicherung wie _PARAM_ROWS, eigener Abschnitt im Dialog
_CSV_ROWS = [
    ("CSV_INTERVAL_S", "Rohdaten: ein Eintrag alle", "s", 1),
]

# Standardwerte beim Import festhalten – apply_grenzwerte_to_settings() ändert die
# Werte in config.settings später in place
_SENSOR_DEFAULTS = {
    s["id"]: {"warn": s["warn_threshold"], "critical": s["critical_threshold"]}
    for s in SENSORS if s["id"] in {r[0] for r in _SENSOR_ROWS}
}
_PARAM_DEFAULTS = {key: getattr(_settings, key) for key, *_ in _PARAM_ROWS + _CSV_ROWS}
_LIMIT_DEFAULTS = {
    "max_step1_min": _settings.MAX_STEP1_DURATION_MINUTES,
    "max_step2_sec": _settings.MAX_STEP2_DURATION_SECONDS,
    "max_step3_sec": _settings.MAX_STEP3_DURATION_SECONDS,
}


def _load_session() -> dict:
    try:
        return json.loads(SESSION_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _update_session(**entries) -> None:
    try:
        session = _load_session()
        session.update(entries)
        SESSION_FILE.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _load_grenzwerte() -> dict:
    """Gespeicherte Sensor-Grenzwerte; unbekannte/alte Einträge werden ignoriert."""
    saved = _load_session().get("grenzwerte", {})
    return {sid: {k: saved.get(sid, {}).get(k, v) for k, v in d.items()}
            for sid, d in _SENSOR_DEFAULTS.items()}


def _load_parameter() -> dict:
    saved = _load_session().get("parameter", {})
    return {key: saved.get(key, default) for key, default in _PARAM_DEFAULTS.items()}


def _load_messzeit_limits() -> dict:
    return _load_session().get("messzeit_limits", {})


def apply_grenzwerte_to_settings() -> None:
    """Überträgt die gespeicherten Werte in config.settings (SENSORS in place, Parameter,
    MAX_STEP*). Vor dem Anlegen des MainWindow aufrufen."""
    data = _load_grenzwerte()
    for sensor in _settings.SENSORS:
        if sensor["id"] in data:
            sensor["warn_threshold"] = data[sensor["id"]]["warn"]
            sensor["critical_threshold"] = data[sensor["id"]]["critical"]
    for key, value in _load_parameter().items():
        setattr(_settings, key, value)

    limits = _load_messzeit_limits()
    if "max_step1_min" in limits:
        _settings.MAX_STEP1_DURATION_MINUTES = limits["max_step1_min"]
    if "max_step2_sec" in limits:
        _settings.MAX_STEP2_DURATION_SECONDS = limits["max_step2_sec"]
    if "max_step3_sec" in limits:
        _settings.MAX_STEP3_DURATION_SECONDS = limits["max_step3_sec"]


def _separator() -> QFrame:
    return theme.separator()


def _section(text: str) -> QLabel:
    return theme.label(text, "section")


class GrenzwerteDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Einstellungen")
        self.setMinimumWidth(560)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.MSWindowsFixedSizeDialogHint)
        self._sensor_boxes: dict[tuple[str, str], QDoubleSpinBox] = {}
        self._param_boxes: dict[str, QDoubleSpinBox] = {}
        self._limit_boxes: dict[str, QSpinBox] = {}
        self._build_ui()
        self._fill(_load_grenzwerte(), _load_parameter(), _load_messzeit_limits())

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 18, 28, 18)
        root.setSpacing(8)

        title = theme.label("Einstellungen", "h2")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(title)
        subtitle = theme.label("Änderungen gelten für den nächsten Testdurchlauf.", "muted")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(subtitle)

        # Zwei Spalten nebeneinander – Höhe ist auf dem Laptop (1536×816) knapp
        columns = QHBoxLayout()
        columns.setSpacing(28)
        left = QVBoxLayout()
        left.setSpacing(8)
        right = QVBoxLayout()
        right.setSpacing(8)
        columns.addLayout(left, stretch=1)
        columns.addLayout(right, stretch=1)
        root.addLayout(columns)

        # ── Sensoren (live) ──────────────────────────────────────────────────
        left.addWidget(_section("Lastlauf – live überwachte Sensoren"))
        grid = self._grid(["Sensor", "Einheit", "Warnung", "Kritisch"])
        for i, (sid, display, unit) in enumerate(_SENSOR_ROWS):
            row = i + 1
            grid.addWidget(QLabel(display), row, 0)
            grid.addWidget(self._unit(unit), row, 1)
            for col, key in ((2, "warn"), (3, "critical")):
                sb = self._spinbox(1)
                grid.addWidget(sb, row, col)
                self._sensor_boxes[(sid, key)] = sb
        left.addWidget(grid.parentWidget())

        # ── Prüfparameter ────────────────────────────────────────────────────
        right.addWidget(_section("Prüfparameter"))
        grid = self._grid(["Parameter", "Einheit", "Wert"])
        for i, (key, display, unit, decimals) in enumerate(_PARAM_ROWS):
            row = i + 1
            grid.addWidget(QLabel(display), row, 0)
            grid.addWidget(self._unit(unit), row, 1)
            sb = self._spinbox(decimals)
            grid.addWidget(sb, row, 2)
            self._param_boxes[key] = sb
        hint = QLabel("Drehzahl → AO0-Sollwert ist eine Annahme (0–10 V ≙ 0–50 Hz), "
                      "am Prüfstand noch abgleichen.")
        hint.setProperty("role", "caption")
        hint.setWordWrap(True)
        right.addWidget(grid.parentWidget())
        right.addWidget(hint)

        # ── Prüfbericht (Excel) ──────────────────────────────────────────────
        right.addWidget(_separator())
        right.addWidget(_section("Prüfbericht (Excel)"))
        grid = self._grid(["Parameter", "Einheit", "Wert"])
        for i, (key, display, unit, decimals) in enumerate(_CSV_ROWS):
            grid.addWidget(QLabel(display), i + 1, 0)
            grid.addWidget(self._unit(unit), i + 1, 1)
            sb = self._spinbox(decimals)
            sb.setRange(0.0, 3600.0)
            grid.addWidget(sb, i + 1, 2)
            self._param_boxes[key] = sb
        csv_hint = QLabel("Live-Anzeige und Bewertung laufen weiter mit "
                          f"{_settings.MEASUREMENT_INTERVAL_MS} ms – nur in den Bericht wird seltener "
                          "geschrieben. 0 = jeden Messwert schreiben.")
        csv_hint.setProperty("role", "caption")
        csv_hint.setWordWrap(True)
        right.addWidget(grid.parentWidget())
        right.addWidget(csv_hint)
        right.addStretch()

        # ── Messzeiten – Maximalwerte ────────────────────────────────────────
        left.addWidget(_separator())
        left.addWidget(_section("Messzeiten – Maximalwerte im Startdialog"))
        grid = self._grid(["Schritt", "Einheit", "Maximum"])
        time_rows = [
            ("max_step1_min", "Lastlauf",                "min", 1, 9999),
            ("max_step2_sec", "Leckage – Haltezeit",     "s",   1, 86400),
            ("max_step3_sec", "Kraftprüfung – Haltezeit", "s",  1, 86400),
        ]
        for i, (key, label, unit, mn, mx) in enumerate(time_rows):
            row = i + 1
            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(self._unit(unit), row, 1)
            sb = QSpinBox()
            sb.setRange(mn, mx)
            sb.setFixedWidth(110)
            sb.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
            grid.addWidget(sb, row, 2)
            self._limit_boxes[key] = sb
        left.addWidget(grid.parentWidget())
        left.addStretch()

        root.addWidget(_separator())
        btn_row = QHBoxLayout()
        default_btn = theme.button("Standard", "secondary", "refresh", height=38)
        default_btn.clicked.connect(self._on_default)
        save_btn = theme.button("Speichern", "primary", "check", height=38)
        save_btn.setMinimumWidth(140)
        save_btn.clicked.connect(self._on_save)
        # Enter in einem Eingabefeld soll nur den Wert übernehmen – QDialog würde
        # sonst den ersten Button ("Standard") auslösen und alles zurücksetzen.
        for btn in (default_btn, save_btn):
            btn.setAutoDefault(False)
            btn.setDefault(False)
        btn_row.addWidget(default_btn)
        btn_row.addStretch()
        btn_row.addWidget(save_btn)
        root.addLayout(btn_row)

    def _grid(self, headers: list[str]) -> QGridLayout:
        widget = QWidget(self)   # Parent hält das Widget am Leben, bis es eingefügt ist
        grid = QGridLayout(widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(0, 1)
        for col, text in enumerate(headers):
            grid.addWidget(theme.label(text, "caption"), 0, col)
        return grid

    @staticmethod
    def _unit(text: str) -> QLabel:
        return theme.label(text, "muted")

    @staticmethod
    def _spinbox(decimals: int) -> QDoubleSpinBox:
        sb = QDoubleSpinBox()
        sb.setDecimals(decimals)
        sb.setRange(0.0, 99999.0)
        sb.setFixedWidth(110)
        sb.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        return sb

    def _fill(self, sensors: dict, params: dict, limits: dict) -> None:
        for (sid, key), sb in self._sensor_boxes.items():
            sb.setValue(sensors[sid][key])
        for key, sb in self._param_boxes.items():
            sb.setValue(params[key])
        for key, sb in self._limit_boxes.items():
            sb.setValue(limits.get(key, _LIMIT_DEFAULTS[key]))

    def _on_default(self) -> None:
        self._fill(_SENSOR_DEFAULTS, _PARAM_DEFAULTS, {})

    def _on_save(self) -> None:
        sensors: dict = {}
        for (sid, key), sb in self._sensor_boxes.items():
            sensors.setdefault(sid, {})[key] = sb.value()
        params = {key: sb.value() for key, sb in self._param_boxes.items()}
        limits = {key: sb.value() for key, sb in self._limit_boxes.items()}
        _update_session(grenzwerte=sensors, parameter=params, messzeit_limits=limits)
        apply_grenzwerte_to_settings()
        self.accept()
