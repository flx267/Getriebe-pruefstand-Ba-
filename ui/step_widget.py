"""Anzeige eines Prüfschritts. Links: was zu tun ist („Jetzt: …“), Live-Werte, Startknopf.
Rechts je nach Schritt: Checkliste (Vorbereitung), Sperrbolzen-Status, Diagramme.

Der Ablauf selbst (Zeiten, Ventile, Bewertung) liegt komplett in core/test_runner.py –
dieses Widget zeigt nur an und meldet den Klick (start_clicked)."""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget,
)

import config.settings as _settings
from config.settings import PREPARE_CHECKLIST, SENSOR_MAP, STEPS
from ui import theme
from ui.chart_widget import ChartWidget


class StepWidget(QWidget):
    start_clicked = pyqtSignal()
    next_clicked = pyqtSignal()     # „Weiter“ nach dem Ergebnis eines Messschritts
    repeat_clicked = pyqtSignal()   # „Erneut durchführen“
    skip_clicked = pyqtSignal()     # „Kraftprüfung überspringen“ (nur Schritt Sperrbolzen einschieben)

    def __init__(self):
        super().__init__()
        self._action = ""
        self._value_labels: dict[str, QLabel] = {}
        self._targets: dict[str, float] = {}   # sensor_id → Sollwert (Prüfling, z. B. RPM1)
        self._charts: dict[str, ChartWidget] = {}
        self._ready = (False, "")
        self._running = False
        self._review = False
        self._setup_ui()

    def _setup_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(14)

        # ── Links ───────────────────────────────────────────────────────────
        left = theme.frame("panel")
        left.setFixedWidth(380)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(18, 16, 18, 16)
        ll.setSpacing(10)

        self._step_label = theme.overline("")
        self._group_label = theme.label("", "h1", wrap=True)
        self._instruction_label = theme.label("", "body", wrap=True)

        self._now_label = theme.label("", "box", "muted", wrap=True)
        self._now_label.setMinimumHeight(44)

        self._values_container = QWidget()
        self._values_layout = QGridLayout(self._values_container)
        self._values_layout.setContentsMargins(0, 0, 0, 0)
        self._values_layout.setSpacing(8)

        self._critical_disabled_label = theme.label("", "hint", "warn", wrap=True)
        self._critical_disabled_label.setVisible(False)

        # Restzeit + Fortschritt
        self._progress_box = QWidget()
        pl = QVBoxLayout(self._progress_box)
        pl.setContentsMargins(0, 2, 0, 0)
        pl.setSpacing(6)
        top = QHBoxLayout()
        top.addWidget(theme.label("Restzeit", "muted"))
        top.addStretch()
        self._countdown_label = theme.label("")
        self._countdown_label.setFont(theme.font(11, QFont.Weight.DemiBold, mono=True))
        top.addWidget(self._countdown_label)
        self._progress = QProgressBar()
        self._progress.setFixedHeight(6)
        self._progress.setTextVisible(False)
        pl.addLayout(top)
        pl.addWidget(self._progress)

        self._reason_label = theme.label("", "caption", "warn", wrap=True)
        self._reason_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._btn_start = theme.button("", "primary", height=52, size="lg")
        self._btn_start.setFont(theme.font(11))
        self._btn_start.clicked.connect(self._on_start_clicked)

        self._btn_repeat = theme.button("Prüfung erneut durchführen", "secondary", "refresh", height=44,
                                        size="lg")
        self._btn_repeat.setFont(theme.font(11))
        self._btn_repeat.clicked.connect(self.repeat_clicked.emit)
        self._btn_repeat.setVisible(False)

        self._btn_skip = theme.button("Kraftprüfung überspringen", "ghost", "right", height=38)
        self._btn_skip.setToolTip("Sperrbolzen einschieben, Kraftprüfung und Sperrbolzen ziehen "
                                  "auslassen – weiter mit der Sichtprüfung")
        self._btn_skip.clicked.connect(self.skip_clicked.emit)
        self._btn_skip.setVisible(False)

        ll.addWidget(self._step_label)
        ll.addWidget(self._group_label)
        ll.addWidget(self._instruction_label)
        ll.addWidget(self._now_label)
        ll.addWidget(self._values_container)
        ll.addWidget(self._critical_disabled_label)
        ll.addWidget(self._progress_box)
        ll.addStretch()
        ll.addWidget(self._reason_label)
        ll.addWidget(self._btn_repeat)
        ll.addWidget(self._btn_skip)
        ll.addWidget(self._btn_start)

        # ── Rechts ──────────────────────────────────────────────────────────
        self._right = theme.frame("panel")
        self._right_layout = QVBoxLayout(self._right)
        self._right_layout.setContentsMargins(16, 14, 16, 14)
        self._right_layout.setSpacing(10)

        root.addWidget(left)
        root.addWidget(self._right, stretch=1)

    # ── Public API ───────────────────────────────────────────────────────────

    def load_step(self, step_index: int) -> None:
        step = STEPS[step_index]
        self._action = step["action"]
        self._step_label.setText(f"SCHRITT {step_index + 1} / {len(STEPS)}")
        self._group_label.setText(step["name"])
        self._instruction_label.setText(step["instruction"])
        self._btn_start.setText(step["button"])
        self._critical_disabled_label.setText("")
        self._critical_disabled_label.setVisible(False)
        self.set_progress(0.0, 0.0)
        self.set_now("", "INFO")
        self._running = False
        self._review = False
        self._btn_repeat.setVisible(False)
        self._btn_skip.setVisible(self._action == "bolt_in")
        self._ready = (False, "")

        self._value_labels = {}
        self._targets = {}
        self._clear_layout(self._values_layout)
        # Mitgelieferte Sensoren als Kacheln; Sensoren des Prüflings (mit Sollwert, z. B. RPM1)
        # darunter als Soll/Ist-Vergleich ohne Ampel – der Prüfer beurteilt selbst
        own = [SENSOR_MAP[sid] for sid in step["ids"] if not SENSOR_MAP[sid].get("target_setting")]
        checked = [SENSOR_MAP[sid] for sid in step["ids"] if SENSOR_MAP[sid].get("target_setting")]
        cols = 3 if len(own) == 3 else 2
        for i, sensor in enumerate(own):
            self._values_layout.addWidget(self._make_value_tile(sensor, compact=cols == 3),
                                          i // cols, i % cols)
        row = (len(own) + cols - 1) // cols
        for k, sensor in enumerate(checked):
            self._values_layout.addWidget(self._make_target_tile(sensor), row + k, 0, 1, cols)
        self._values_container.setVisible(bool(step["ids"]))

        self._charts = {}
        self._clear_layout(self._right_layout)
        builder = {"prepare": self._build_checklist, "bolt_in": self._build_bolt,
                   "bolt_out": self._build_bolt, "visual": self._build_visual}.get(self._action)
        if builder:
            builder()
        else:
            self._build_charts(step["ids"])
        self._update_button()

    def update_data(self, data: dict, status: str) -> None:
        sensor_id, value = next(iter(data.items()))
        sensor = SENSOR_MAP.get(sensor_id)
        lbl = self._value_labels.get(sensor_id)
        if sensor is None or lbl is None:
            return
        decimals = 3 if sensor["unit"] in ("bar", "V") else 1
        if sensor_id in self._targets:
            lbl.setText(f"{value:.0f} {sensor['unit']}")
            target = self._targets[sensor_id]
            diff = value - target
            pct = f"  ({diff / target * 100:+.1f} %)" if target else ""
            self._value_labels[f"{sensor_id}_diff"].setText(f"{diff:+.0f} {sensor['unit']}{pct}")
            chart = self._charts.get(sensor_id)
            if chart:
                chart.add_value(sensor_id, value)
            return
        lbl.setText(f"{value:.{decimals}f}")
        tone = theme.tone_of(status, "ok")
        theme.set_tone(lbl, tone)
        dot = self._value_labels.get(f"{sensor_id}_dot")
        if dot:
            theme.set_tone(dot, tone)
        chart = self._charts.get(sensor_id)
        if chart:
            chart.add_value(sensor_id, value)

    def set_now(self, text: str, color: str) -> None:
        self._now_label.setText(text)
        theme.set_tone(self._now_label, theme.tone_of(color, "muted"))
        self._now_label.setVisible(bool(text))

    def set_progress(self, remaining: float, total: float) -> None:
        visible = total > 0
        self._progress_box.setVisible(visible)
        if visible:
            self._progress.setMaximum(int(total * 10))
            self._progress.setValue(int((total - remaining) * 10))
            s = int(remaining + 0.999)
            self._countdown_label.setText(f"{s // 60:02d}:{s % 60:02d}")

    def set_ready(self, ok: bool, reason: str) -> None:
        self._ready = (ok, reason)
        self._update_button()

    def set_running(self, running: bool) -> None:
        self._running = running
        self._update_button()

    def set_review(self, _index: int, status: str, text: str) -> None:
        """Messschritt fertig: Ergebnis zeigen, „Weiter“ oder „Erneut durchführen“."""
        self._review = True
        self.set_now(f"Ergebnis: {status}\n{text}", status if status in theme.STATUS_TONE else "INFO")
        self._btn_start.setText("Weiter  →")
        self._btn_repeat.setVisible(True)
        self._update_button()

    def set_bolt(self, inserted) -> None:
        lbl = getattr(self, "_bolt_label", None)
        if lbl is None or not self._action.startswith("bolt"):
            return
        want_in = self._action == "bolt_in"
        if inserted is None:
            text, tone = "Sperrbolzen: NICHT LESBAR", "crit"
        elif inserted:
            text, tone = "Sperrbolzen: EINGESCHOBEN", "ok" if want_in else "warn"
        else:
            text, tone = "Sperrbolzen: GEZOGEN", "warn" if want_in else "ok"
        lbl.setText(f"●  {text}")
        theme.set_tone(lbl, tone)

    def mark_critical_disabled(self, sensor_id: str) -> None:
        dot = self._value_labels.get(f"{sensor_id}_dot")
        if dot:
            dot.setText("⚠")
            theme.set_tone(dot, "warn")
        name = SENSOR_MAP.get(sensor_id, {}).get("name", sensor_id)
        line = f"{name}: Kritischer Grenzwert für diesen Schritt deaktiviert"
        existing = self._critical_disabled_label.text()
        self._critical_disabled_label.setText(f"{existing}\n{line}" if existing else line)
        self._critical_disabled_label.setVisible(True)

    # ── Rechte Seite ─────────────────────────────────────────────────────────

    def _add_title(self, text: str) -> None:
        title = theme.label(text, "h2")
        title.setContentsMargins(2, 2, 2, 6)
        self._right_layout.addWidget(title)

    def _add_items(self, items) -> None:
        for text in items:
            self._right_layout.addWidget(theme.label(f"•   {text}", "listitem", wrap=True))
        self._right_layout.addStretch()

    def _build_checklist(self) -> None:
        # Reine Info-Liste (Nutzer: Haken setzen ist lästig) – lesen, dann einmal klicken
        self._add_title("Bitte prüfen – alles angeschlossen?")
        self._add_items(PREPARE_CHECKLIST)

    def _build_bolt(self) -> None:
        want = "einschieben" if self._action == "bolt_in" else "ziehen"
        self._add_title(f"Sperrbolzen {want}")
        self._right_layout.addStretch()
        self._bolt_label = theme.label("●  Sperrbolzen: –", None, "muted")
        self._bolt_label.setFont(theme.font(22, QFont.Weight.DemiBold))
        self._bolt_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._right_layout.addWidget(self._bolt_label)
        hint = theme.label("Erkannt über Induktiv-Sensor DI3. Der Knopf „Weiter“ wird erst "
                           "aktiv, wenn der Bolzen richtig sitzt.", "muted", wrap=True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._right_layout.addWidget(hint)
        self._right_layout.addStretch()

    def _build_visual(self) -> None:
        self._add_title("Sichtprüfung")
        self._add_items(("Sichtbare Schäden am Gehäuse?", "Ölaustritt / Leckagen?",
                         "Sensoren abnehmen, Stecker NM1 / RPM1 lösen",
                         "Leckage-Schlauch abziehen"))

    def _build_charts(self, ids: list[str]) -> None:
        # Sensoren mit gleicher Einheit (bzw. chart_group) teilen sich ein Diagramm
        groups: dict[str, list[dict]] = {}
        for sid in ids:
            sensor = SENSOR_MAP[sid]
            if sensor.get("no_chart"):
                continue
            groups.setdefault(sensor.get("chart_group") or sensor["unit"], []).append(sensor)
        for sensors in groups.values():
            chart = ChartWidget(sensors)
            for s in sensors:
                self._charts[s["id"]] = chart
            self._right_layout.addWidget(chart)

    # ── Private ──────────────────────────────────────────────────────────────

    def _update_button(self) -> None:
        if self._review:
            self._btn_start.setEnabled(True)
            self._reason_label.setVisible(False)
            return
        ok, reason = self._ready
        self._btn_start.setEnabled(ok and not self._running)
        self._reason_label.setText("" if self._running else reason)
        self._reason_label.setVisible(bool(reason) and not self._running)

    def _make_target_tile(self, sensor: dict) -> QWidget:
        """Soll/Ist-Vergleich für einen Sensor des Prüflings (RPM1): keine Ampel, die
        Bewertung trifft der Prüfer."""
        target = float(getattr(_settings, sensor["target_setting"]))
        self._targets[sensor["id"]] = target
        unit = sensor["unit"]

        tile = theme.frame("checktile")
        grid = QGridLayout(tile)
        grid.setContentsMargins(12, 9, 12, 10)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(3)

        head = theme.label(f"{sensor['name']} (Prüfling) – bitte selbst beurteilen",
                           "muted", wrap=True)
        grid.addWidget(head, 0, 0, 1, 2)

        actual = theme.label("—", "valuesm")
        diff = theme.label("—", "muted")
        self._value_labels[sensor["id"]] = actual
        self._value_labels[f"{sensor['id']}_diff"] = diff
        rows = (("Motor dreht mit (Soll)", theme.label(f"{target:.0f} {unit}", "valuesm")),
                ("Sensor zeigt", actual),
                ("Abweichung", diff))
        for r, (text, value) in enumerate(rows, start=1):
            grid.addWidget(theme.label(text, "field"), r, 0)
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(value, r, 1)
        grid.setColumnStretch(0, 1)
        return tile

    def _make_value_tile(self, sensor: dict, compact: bool = False) -> QWidget:
        """Kachel: Name + Statuspunkt, darunter große Zahl + Einheit."""
        tile = theme.frame("tile")
        layout = QVBoxLayout(tile)
        layout.setContentsMargins(10 if compact else 12, 9, 10 if compact else 12, 10)
        layout.setSpacing(2)

        top = QHBoxLayout()
        top.setSpacing(6)
        top.addWidget(theme.label(sensor["name"], "muted", wrap=compact), stretch=1)
        dot = theme.label("●", None, "ok")
        dot.setFont(theme.font(9))
        top.addWidget(dot)
        self._value_labels[f"{sensor['id']}_dot"] = dot

        bottom = QHBoxLayout()
        bottom.setSpacing(5)
        value_lbl = theme.label("—", "valuesm" if compact else "value")
        self._value_labels[sensor["id"]] = value_lbl
        unit_lbl = theme.label(sensor["unit"], "unit")
        bottom.addWidget(value_lbl)
        bottom.addWidget(unit_lbl, alignment=Qt.AlignmentFlag.AlignBottom)
        bottom.addStretch()

        layout.addLayout(top)
        layout.addLayout(bottom)
        return tile

    def _on_start_clicked(self) -> None:
        # Kein eigenes Sperren: der Runner meldet running_changed bzw. lehnt ab (Doppelklick-
        # Schutz liegt dort), sonst bliebe der Knopf nach einer Ablehnung grau
        if self._review:
            self.next_clicked.emit()
        else:
            self.start_clicked.emit()

    def _clear_layout(self, layout) -> None:
        if layout is self._right_layout:
            self._bolt_label = None
        while layout.count():
            item = layout.takeAt(0)
            if item.layout():
                self._clear_layout(item.layout())
            elif item.widget():
                item.widget().deleteLater()
