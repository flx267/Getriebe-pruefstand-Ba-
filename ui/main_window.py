from datetime import datetime

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
    QSplitter, QStackedWidget, QTextEdit, QVBoxLayout, QWidget,
)

import config.settings as _settings
from config.settings import APP_NAME, APP_VERSION, SENSOR_MAP, STEPS
from core.test_runner import TestRunner
from hardware.base import SensorInterface
from ui import icons, theme
from ui.result_screen import ResultPage
from ui.step_widget import StepWidget

_PAGE_TEST   = 0
_PAGE_RESULT = 1

# Bewertung eines Schritts → Symbol im Kreis der Schrittliste
_STEP_ICONS = {"ok": ("check", theme.OK), "warn": ("warn", theme.WARN), "crit": ("x", theme.CRIT)}


def _alert_layout(dlg: QDialog, tone: str, icon_name: str, title: str,
                  subtitle: str = "") -> tuple[QVBoxLayout, QLabel]:
    """Gemeinsamer Aufbau der Warn-Dialoge: farbiger Streifen oben, Icon-Kachel, Titel.
    Gibt das Inhalts-Layout und das Titel-Label zurück."""
    dlg.setProperty("role", "alert")
    outer = QVBoxLayout(dlg)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)
    strip = theme.frame("strip", tone)
    strip.setFixedHeight(4)
    outer.addWidget(strip)

    body = QVBoxLayout()
    body.setContentsMargins(32, 24, 32, 22)
    body.setSpacing(14)
    outer.addLayout(body)

    head = QHBoxLayout()
    head.setSpacing(14)
    head.addWidget(theme.icon_tile(icon_name, tone), alignment=Qt.AlignmentFlag.AlignTop)
    texts = QVBoxLayout()
    texts.setSpacing(2)
    title_lbl = theme.label(title, "h2", wrap=True)
    texts.addWidget(title_lbl)
    if subtitle:
        texts.addWidget(theme.label(subtitle, "muted", wrap=True))
    texts.addStretch()
    head.addLayout(texts, stretch=1)
    body.addLayout(head)
    return body, title_lbl


def _button_row(*buttons_with_stretch) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(12)
    for btn, stretch in buttons_with_stretch:
        row.addWidget(btn, stretch=stretch)
    return row


class _SafetyDialog(QDialog):
    """Hinweisfeld bei fehlender Sicherheitsbedingung (Induktiv-Sensoren, Not-Aus-Kreis/
    Schrank, Sperrbolzen). Zeigt live, was fehlt; „Erneut prüfen“ macht an derselben
    Stelle weiter, ohne die Prüfung neu anzulegen."""

    def __init__(self, runner: TestRunner, parent=None):
        super().__init__(parent)
        self._runner = runner
        self.setWindowTitle("Sicherheitsbedingung nicht erfüllt")
        self.setModal(True)
        self.setMinimumWidth(620)

        layout, self._head = _alert_layout(
            self, "warn", "warn", "Sensoren gerade nicht richtig geschaltet", "Prüfung pausiert")

        self._reasons = theme.label("", "box", "crit", wrap=True)
        self._info = theme.label("", "body", wrap=True)

        self._retry_btn = theme.button("Erneut prüfen", "primary", "refresh", height=48)
        self._retry_btn.setFont(theme.font(12))
        self._retry_btn.clicked.connect(self._on_retry)
        abort_btn = theme.button("Prüfung abbrechen", "ghost", height=48)
        abort_btn.setFont(theme.font(11))
        abort_btn.clicked.connect(self._on_abort)

        layout.addWidget(self._reasons)
        layout.addWidget(self._info)
        layout.addSpacing(4)
        layout.addLayout(_button_row((self._retry_btn, 2), (abort_btn, 1)))

    def update_state(self, reasons: list, interrupted: str) -> None:
        if reasons:
            self._reasons.setText("\n".join(f"✕   {r}" for r in reasons))
            theme.set_tone(self._reasons, "crit")
        else:
            self._reasons.setText("✓   Alle Bedingungen sind jetzt erfüllt – „Erneut prüfen“ klicken")
            theme.set_tone(self._reasons, "ok")
        pressure = any(r.startswith("Druck DS1") for r in reasons)
        only_pressure = pressure and all(r.startswith("Druck DS1") for r in reasons)
        if reasons:   # bei „wieder OK“ die bisherige Überschrift stehen lassen
            self._head.setText("Druck zu hoch!" if only_pressure
                               else "Sensoren gerade nicht richtig geschaltet")
        text = ""
        if pressure:
            text += (f"Der Zylinderdruck DS1 liegt über {_settings.CYL_MAX_PRESSURE_BAR:g} bar. "
                     "Bitte den Druck am kleinen Regler oder am Hauptregler niedriger "
                     "einstellen.\n\n")
        if not only_pressure:
            text += ("Bitte prüfen: Tür geschlossen? Getriebe richtig angepresst? Motor ganz "
                     "im Getriebe? Blockierung richtig drin bzw. draußen?\n\n")
        if interrupted:
            text += (f"Der Schritt „{interrupted}“ wurde sicher unterbrochen (Motor aus, Leckage "
                     "entlüftet, oberer Zylinder eingefahren) und startet nach „Erneut prüfen“ neu.\n")
        text += "Alle Eingaben und bisherigen Ergebnisse bleiben erhalten."
        self._info.setText(text)

    def _on_retry(self) -> None:
        if self._runner.retry_safety():
            self.accept()

    def _on_abort(self) -> None:
        self.accept()
        self._runner.user_abort()

    def reject(self) -> None:
        # Fenster-X / Esc = „Erneut prüfen“ – die Pause lässt sich nicht einfach wegklicken.
        # Läuft keine Prüfung mehr (Programmende), normal schließen, sonst blockiert quit().
        if self._runner is None or not self._runner.active:
            super().reject()
            return
        self._on_retry()


class _StepRow(QFrame):
    """Eine Zeile der Schrittliste: Kreis (Nummer bzw. Bewertungs-Symbol) + Name."""

    def __init__(self, number: int, name: str):
        super().__init__()
        self.setProperty("role", "steprow")
        self._number = number
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 7, 8, 7)
        layout.setSpacing(10)
        self._circle = theme.label(str(number), "stepnum")
        self._circle.setFixedSize(22, 22)
        self._circle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._name = theme.label(name, "stepname", wrap=True)
        layout.addWidget(self._circle)
        layout.addWidget(self._name, stretch=1)
        self._state = None
        self.set_state("open")

    def set_state(self, state: str) -> None:
        """state: open | active | ok | warn | crit | skip"""
        if state == self._state:
            return
        self._state = state
        theme.set_prop(self, "state", "active" if state == "active" else "")
        theme.set_prop(self._circle, "state", state)
        theme.set_prop(self._name, "state", "active" if state == "active" else "skip" if state == "skip"
                       else "done" if state in _STEP_ICONS else "")
        if state == "skip":
            self._circle.clear()
            self._circle.setText("–")
        elif state in _STEP_ICONS:
            name, color = _STEP_ICONS[state]
            self._circle.setText("")
            self._circle.setPixmap(icons.pixmap(name, color, 12))
        else:
            self._circle.clear()
            self._circle.setText(str(self._number))


class MainWindow(QMainWindow):

    session_ended = pyqtSignal(bool)   # True = neue Prüfung, False = Programm beenden

    def __init__(
        self,
        hardware: SensorInterface,
        simulated: bool,
        prufer: str,
        pruefnummer: str,
        auftragsnummer: str = "",
        bass_artikel_nr: str = "",
        getriebetyp: str = "",
        kunden_artikel_nr: str = "",
        getriebeseriennummer: str = "",
        kraftmessbolzen_seriennummer: str = "",
        kommentar: str = "",
    ):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME}  –  {pruefnummer}  |  {prufer}")
        self._apply_screen_aware_size(1200, 760)
        self._simulated = simulated
        self._ended = False
        self._step_status: dict[int, str] = {}
        self._current = 0

        self._runner = TestRunner(hardware)
        self._safety_dialog: _SafetyDialog | None = None
        self._build_ui(f"Prüfung {pruefnummer}  ·  {prufer}")

        r = self._runner
        r.step_changed.connect(self._on_step_changed)
        r.data_updated.connect(self._step_widget.update_data)
        r.now_text.connect(self._step_widget.set_now)
        r.progress.connect(self._step_widget.set_progress)
        r.ready_changed.connect(self._step_widget.set_ready)
        r.running_changed.connect(self._step_widget.set_running)
        r.bolt_state.connect(self._step_widget.set_bolt)
        r.step_result.connect(self._on_step_result)
        r.safety_state.connect(self._on_safety_state)
        r.safety_blocked.connect(self._on_safety_blocked)
        r.safety_cleared.connect(self._on_safety_cleared)
        r.critical_reached.connect(self._on_critical)
        r.sensor_critical_disabled.connect(self._step_widget.mark_critical_disabled)
        r.test_finished.connect(self._on_test_finished)
        r.aborted.connect(self._on_aborted)
        r.log_message.connect(self._append_log)
        r.step_review.connect(self._step_widget.set_review)
        self._step_widget.start_clicked.connect(r.start_step)
        self._step_widget.next_clicked.connect(r.next_step)
        self._step_widget.repeat_clicked.connect(r.repeat_step)
        self._step_widget.skip_clicked.connect(self._on_skip_force)

        # Erst starten, wenn das Fenster sichtbar ist (sonst erscheint ein „Start nicht
        # möglich“-Dialog vor dem Hauptfenster)
        QTimer.singleShot(300, lambda: r.start_test(
            prufer, pruefnummer, auftragsnummer=auftragsnummer, bass_artikel_nr=bass_artikel_nr,
            getriebetyp=getriebetyp, kunden_artikel_nr=kunden_artikel_nr,
            getriebeseriennummer=getriebeseriennummer,
            kraftmessbolzen_seriennummer=kraftmessbolzen_seriennummer, kommentar=kommentar))

    def _apply_screen_aware_size(self, target_w: int, target_h: int) -> None:
        """Setzt Mindest-/Startgröße, ohne den verfügbaren Bildschirmplatz zu überschreiten
        (relevant bei kleineren oder skalierten Displays)."""
        screen = QApplication.primaryScreen()
        if screen is None:
            self.setMinimumSize(target_w, target_h)
            return
        available = screen.availableGeometry()
        margin = 40
        width = min(target_w, max(800, available.width() - margin))
        height = min(target_h, max(600, available.height() - margin))
        self.setMinimumSize(width, height)
        self.resize(width, height)

    # ── UI construction ──────────────────────────────────────────────────────

    def _build_ui(self, session_text: str) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._make_header(session_text))

        self._stack = QStackedWidget()
        self._stack.addWidget(self._make_test_page())
        self._result_page = ResultPage()
        self._result_page.new_test_clicked.connect(lambda: self._end_session(True))
        self._result_page.quit_clicked.connect(lambda: self._end_session(False))
        self._stack.addWidget(self._result_page)
        root.addWidget(self._stack, stretch=1)

    def _make_header(self, session_text: str) -> QFrame:
        bar = theme.frame("header")
        bar.setFixedHeight(56)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 0, 20, 0)
        layout.setSpacing(12)

        logo = theme.label("", "logo")
        logo.setPixmap(icons.pixmap("logo", theme.MUTED, 22))
        title = theme.label(APP_NAME, "apptitle")
        mode = theme.label(f"v{APP_VERSION}  ·  {'SIMULATION' if self._simulated else 'USB-4711A'}",
                           "pill", "warn" if self._simulated else None)
        session = theme.label(session_text, "muted")

        self._safety_lbl = theme.label("●  Sicherheit: –", "badge")

        self._abort_btn = theme.button("ABBRUCH", "danger", "stop")
        self._abort_btn.setFixedSize(150, 40)
        self._abort_btn.setFont(theme.font(11))
        self._abort_btn.setToolTip("Prüfung sofort abbrechen: Motor aus, Leckage entlüften, "
                                   "oberen Zylinder einfahren.\nDer echte Not-Aus sitzt am Prüfstand.")
        self._abort_btn.clicked.connect(self._on_abort_clicked)

        layout.addWidget(logo)
        layout.addWidget(title)
        layout.addWidget(mode)
        layout.addStretch()
        layout.addWidget(session)
        layout.addSpacing(4)
        layout.addWidget(self._safety_lbl)
        layout.addSpacing(4)
        layout.addWidget(self._abort_btn)
        return bar

    def _make_test_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._make_sidebar())
        splitter.addWidget(self._make_content())
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([230, 970])

        layout.addWidget(splitter)
        return page

    def _make_sidebar(self) -> QFrame:
        sidebar = theme.frame("sidebar")
        sidebar.setFixedWidth(230)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(12, 18, 12, 16)
        layout.setSpacing(4)

        heading = theme.overline("Prüfschritte")
        heading.setContentsMargins(8, 0, 8, 8)
        layout.addWidget(heading)

        self._step_rows = [_StepRow(i + 1, step["name"]) for i, step in enumerate(STEPS)]
        for row in self._step_rows:
            layout.addWidget(row)
        layout.addStretch()
        self._refresh_sidebar()
        return sidebar

    def _make_content(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._step_widget = StepWidget()

        log_frame = theme.frame("logbar")
        log_frame.setFixedHeight(120)
        log_layout = QVBoxLayout(log_frame)
        log_layout.setContentsMargins(16, 8, 16, 12)
        log_layout.setSpacing(6)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFont(theme.font(9, mono=True))

        log_layout.addWidget(theme.overline("Protokoll"))
        log_layout.addWidget(self._log)

        layout.addWidget(self._step_widget, stretch=1)
        layout.addWidget(log_frame)
        return panel

    def _refresh_sidebar(self) -> None:
        for i, row in enumerate(self._step_rows):
            if i in self._step_status:
                if self._step_status[i] == "ÜBERSPRUNGEN":
                    row.set_state("skip")
                    continue
                state = theme.tone_of(self._step_status[i], "ok")
                row.set_state(state if state in _STEP_ICONS else "ok")
            elif i == self._current:
                row.set_state("active")
            else:
                row.set_state("open")

    # ── Slots ────────────────────────────────────────────────────────────────

    @pyqtSlot(int)
    def _on_step_changed(self, index: int) -> None:
        self._current = index
        self._step_widget.load_step(index)
        self._refresh_sidebar()

    @pyqtSlot(int, str, str)
    def _on_step_result(self, index: int, status: str, _text: str) -> None:
        self._step_status[index] = status
        self._refresh_sidebar()

    @pyqtSlot(bool, str)
    def _on_safety_state(self, ok: bool, text: str) -> None:
        self._safety_lbl.setText(f"●  {text}")
        self._safety_lbl.setToolTip(text)
        theme.set_tone(self._safety_lbl, "ok" if ok else "crit")

    @pyqtSlot(list, str)
    def _on_safety_blocked(self, reasons: list, interrupted: str) -> None:
        if self._safety_dialog is None:
            self._safety_dialog = _SafetyDialog(self._runner, self)
        self._safety_dialog.update_state(reasons, interrupted)
        if not self._safety_dialog.isVisible():
            self._safety_dialog.show()   # nicht exec(): der Takt muss live weiterlaufen

    @pyqtSlot()
    def _on_safety_cleared(self) -> None:
        if self._safety_dialog is not None and self._safety_dialog.isVisible():
            self._safety_dialog.accept()

    @pyqtSlot(bool)
    def _on_test_finished(self, passed: bool) -> None:
        self._abort_btn.setEnabled(False)
        self._result_page.show_result(passed, self._runner.step_results, self._runner.csv_path)
        self._stack.setCurrentIndex(_PAGE_RESULT)

    @pyqtSlot()
    def _on_abort_clicked(self) -> None:
        # Sofort, ohne Rückfrage – Abbruch muss schnell gehen (Nutzer 01.10.2026)
        self._runner.user_abort()

    @pyqtSlot()
    def _on_skip_force(self) -> None:
        reply = QMessageBox.question(
            self,
            "Kraftprüfung überspringen?",
            "Sperrbolzen einschieben, Kraftprüfung und Sperrbolzen ziehen werden übersprungen, "
            "es geht direkt mit der Sichtprüfung weiter.\n\n"
            "Im Prüfbericht steht die Kraftprüfung als „übersprungen – nicht geprüft“ (WARNUNG).",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._runner.skip_force_test()

    @pyqtSlot(str, str, float)
    def _on_critical(self, sensor_id: str, sensor_name: str, value: float) -> None:
        unit = SENSOR_MAP.get(sensor_id, {}).get("unit", "")

        dlg = QDialog(self)
        dlg.setWindowTitle("Kritischer Messwert")
        dlg.setModal(True)
        dlg.setMinimumWidth(580)

        layout, _ = _alert_layout(dlg, "crit", "warn", "Kritischer Messwert erreicht!",
                                  "Der Motor wurde gestoppt.")
        layout.addWidget(theme.label(f"Sensor: {sensor_name}\n"
                                     f"Gemessener Wert: {value:.2f} {unit}", "box", "crit"))
        layout.addWidget(theme.label("Bitte Ursache prüfen und dann entscheiden:", "body", wrap=True))

        btn_continue = theme.button("Motor neu starten und fortfahren", "primary", "refresh", height=46)
        btn_continue.setFont(theme.font(11))
        btn_continue.clicked.connect(dlg.accept)
        btn_abort = theme.button("Prüfung abbrechen", "ghost", height=46)
        btn_abort.setFont(theme.font(11))
        btn_abort.clicked.connect(dlg.reject)

        layout.addSpacing(4)
        layout.addLayout(_button_row((btn_continue, 1), (btn_abort, 1)))

        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._runner.resume_after_critical(sensor_id)
        else:
            self._runner.critical_abort()

    @pyqtSlot(str, list)
    def _on_aborted(self, title: str, reasons: list) -> None:
        self._abort_btn.setEnabled(False)
        if self._safety_dialog is not None and self._safety_dialog.isVisible():
            self._safety_dialog.done(0)
        if self._ended:
            return   # Programm wird gerade geschlossen
        csv = self._runner.csv_path
        keep = self._show_abort_dialog(title, reasons, has_report=bool(csv and csv.exists()))
        if not keep and csv:
            try:
                csv.unlink()
            except Exception:
                pass
            csv = None
        self._result_page.show_result(False, self._runner.step_results, csv,
                                      aborted=title, reasons=reasons)
        self._stack.setCurrentIndex(_PAGE_RESULT)

    def _show_abort_dialog(self, title: str, reasons: list, has_report: bool) -> bool:
        """Gibt True zurück, wenn der Prüfbericht behalten werden soll."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Prüfung abgebrochen")
        dlg.setModal(True)
        dlg.setMinimumWidth(600)

        layout, _ = _alert_layout(dlg, "warn", "warn", title)
        if reasons:
            layout.addWidget(theme.label("\n".join(f"•   {r}" for r in reasons), "box", "warn",
                                         wrap=True))
        if has_report or self._runner.step_results or title != "Prüfung kann nicht starten":
            info = ("Motor ist aus, der Leckage-Strang entlüftet, der obere Zylinder "
                    "eingefahren. Vor einer neuen Prüfung ggf. den Sperrbolzen ziehen.")
        else:
            info = ("Bitte Ursache beheben (Not-Aus entriegeln, Schaltschrank schließen, "
                    "Induktiv-Sensoren prüfen) und dann „Neue Prüfung“ wählen.")
        layout.addWidget(theme.label(info, "body", wrap=True))
        layout.addSpacing(4)

        if has_report:
            btn_keep = theme.button("Prüfbericht behalten", "primary", "check", height=46)
            btn_keep.setFont(theme.font(11))
            btn_keep.clicked.connect(dlg.accept)
            btn_del = theme.button("Prüfbericht löschen", "ghost", height=46)
            btn_del.setFont(theme.font(11))
            btn_del.clicked.connect(dlg.reject)
            layout.addLayout(_button_row((btn_keep, 1), (btn_del, 1)))
        else:
            btn_ok = theme.button("OK", "primary", height=46)
            btn_ok.setFont(theme.font(11))
            btn_ok.setMinimumWidth(180)
            btn_ok.clicked.connect(dlg.accept)
            row = QHBoxLayout()
            row.addStretch()
            row.addWidget(btn_ok)
            row.addStretch()
            layout.addLayout(row)
        return dlg.exec() == QDialog.DialogCode.Accepted

    @pyqtSlot(str)
    def _append_log(self, msg: str) -> None:
        self._log.append(f"[{datetime.now().strftime('%H:%M:%S')}]  {msg}")

    def _end_session(self, new_test: bool) -> None:
        if self._ended:
            return
        self._ended = True
        self._runner.shutdown()
        self.session_ended.emit(new_test)
        self.close()

    def closeEvent(self, event) -> None:
        if not self._ended:
            if self._runner.active:
                reply = QMessageBox.question(
                    self, "Prüfung läuft",
                    "Die Prüfung läuft noch. Wirklich abbrechen und das Programm beenden?\n\n"
                    "Motor aus, Leckage wird entlüftet, oberer Zylinder fährt ein.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    event.ignore()
                    return
            self._ended = True
            self._runner.shutdown()
            self.session_ended.emit(False)
        super().closeEvent(event)
