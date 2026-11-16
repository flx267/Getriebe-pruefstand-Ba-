"""
Prüfablauf – steuert Schritt für Schritt die Hardware (STEPS in config/settings.py).

Jeder Schritt wird vom Werker per Klick gestartet (start_step); was danach automatisch
passiert, bestimmt STEPS[i]["action"]. Ein QTimer (200 ms) überwacht dabei ständig die
Sicherheit (hardware/safety.py) und treibt die Ablaufphasen voran. Sensorwerte kommen
aus je einem Thread pro Sensor (_SensorWorker).

Bei jedem Abbruch (Sicherheit, ABBRUCH-Knopf, kritischer Wert, Fenster schließen) wird
sicher abgefahren: Motor aus, Leckage entlüften, oberen Zylinder einfahren.
"""

import math
import time
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal

import config.settings as _settings
from config.settings import (
    CYLINDER_MOVE_S, MEASUREMENT_INTERVAL_MS, MOTOR_RAMP_S,
    SENSOR_MAP, STEPS, TORQUE_SETTLE_S,
)
from core.report_writer import ReportWriter
from core.evaluator import Evaluator
from hardware.base import SensorInterface
from hardware.cylinder_sequence import (
    LO_EXT, LO_RET, UP_EXT, UP_RET, at_home, home_deviations, move,
)
from hardware.leak_sequence import DO6, LeakSequence, phase_name, vent_blocking
from hardware.safety import bolt_inserted, di_violations

_TICK_MS = 200


def _vent_s() -> float:
    """Entlüftungszeit aus den Einstellungen (zur Laufzeit lesen, siehe
    apply_grenzwerte_to_settings); nie unter 1 s, damit 0 im Dialog das Entlüften nicht abschaltet."""
    return max(1.0, _settings.LEAK_VENT_STEP_S)

# Messschritte, die der Werker nach dem Ergebnis wiederholen kann („Erneut durchführen“)
_REPEATABLE = ("leak", "run", "torque")


class _SensorWorker(QThread):
    data_ready = pyqtSignal(dict, str)

    def __init__(self, hardware: SensorInterface, sensor_id: str, evaluator: Evaluator):
        super().__init__()
        self._hardware = hardware
        self._sensor_id = sensor_id
        self._evaluator = evaluator
        self._running = False

    def run(self):
        self._running = True
        interval = MEASUREMENT_INTERVAL_MS / 1000.0
        while self._running:
            value = self._hardware.read(self._sensor_id)
            if value is not None:
                status = self._evaluator.evaluate(self._sensor_id, value)
                self.data_ready.emit({self._sensor_id: value}, status)
            time.sleep(interval)

    def stop(self):
        self._running = False
        self.wait(2000)


def _mmss(seconds: float) -> str:
    s = max(0, int(math.ceil(seconds)))
    return f"{s // 60:d}:{s % 60:02d}"


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else math.nan


class TestRunner(QObject):
    step_changed      = pyqtSignal(int)
    data_updated      = pyqtSignal(dict, str)
    now_text          = pyqtSignal(str, str)        # Text, Farbe ("INFO"/"AKTIV"/"OK"/"WARNUNG"/"KRITISCH")
    progress          = pyqtSignal(float, float)    # verbleibend s, gesamt s (0 → ausblenden)
    ready_changed     = pyqtSignal(bool, str)       # Startknopf erlaubt?, Grund
    running_changed   = pyqtSignal(bool)
    step_result       = pyqtSignal(int, str, str)   # Schritt-Index, Status, Text
    step_review       = pyqtSignal(int, str, str)   # Ergebnis da → „Weiter“ oder „Erneut durchführen“
    bolt_state        = pyqtSignal(object)          # True = steckt, False = gezogen, None
    safety_state      = pyqtSignal(bool, str)       # in Ordnung?, Text
    critical_reached  = pyqtSignal(str, str, float) # sensor_id, sensor_name, value
    sensor_critical_disabled = pyqtSignal(str)
    safety_blocked    = pyqtSignal(list, str)       # Gründe (leer = wieder OK), unterbrochener Schritt
    safety_cleared    = pyqtSignal()
    test_finished     = pyqtSignal(bool)
    aborted           = pyqtSignal(str, list)       # Titel, Gründe
    log_message       = pyqtSignal(str)

    def __init__(self, hardware: SensorInterface):
        super().__init__()
        self._hw = hardware
        self._evaluator = Evaluator()
        self._csv = ReportWriter()
        self._workers: list[_SensorWorker] = []
        self._timer = QTimer(self)
        self._timer.setInterval(_TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._reset()

    def _reset(self) -> None:
        self._active = False
        self._step = 0
        self._running = False
        self._phase = ""
        self._phase_end = 0.0
        self._step_start = 0.0
        self._step_total = 0.0
        self._results: list[dict] = []
        self._latest: dict = {}
        self._csv_last = -math.inf
        self._csv_worst = "OK"
        self._max: dict[str, float] = {}
        self._worst: dict[str, str] = {}
        self._bolt_expect: Optional[str] = None
        self._critical_active = False
        self._paused_at = 0.0
        self._disabled_critical: set[str] = set()
        self._critical_streak: dict[str, int] = {}
        self._leak: Optional[LeakSequence] = None
        self._samples: dict[str, list[float]] = {}
        self._settle_end = 0.0                  # Lastlauf: bis dahin nicht bewerten
        self._ready: tuple = ()
        self._safety: tuple = ()
        self._bolt: object = "?"
        # Sicherheitsbedingung verletzt → Prüfung pausiert, bis der Werker „Erneut prüfen“
        # klickt (None = frei, [] = wieder OK aber noch nicht bestätigt, [...] = Gründe)
        self._blocked: Optional[list[str]] = None
        self._interrupted = ""
        self._review = False                    # Messschritt fertig, Werker entscheidet
        self._attempts: dict[int, int] = {}     # Schritt-Index → Anzahl Durchläufe

    # ── Start / Ende ──────────────────────────────────────────────────────────

    def start_test(self, prufer: str, pruefnummer: str, **kopfdaten: str) -> None:
        """kopfdaten: Felder des Startdialogs (Auftragsnummer, Artikel-Nr., Serien-Nr., …),
        siehe ReportWriter.open."""
        self._reset()
        # Fehlende Sicherheitsbedingungen blockieren hier nicht mehr – _tick() zeigt dann das
        # Hinweisfeld, die Eingaben aus dem Startdialog bleiben erhalten
        self._csv.open(prufer, pruefnummer, **kopfdaten)
        self._active = True
        self.log_message.emit(f"Prüfung gestartet  |  Prüfer: {prufer}  |  Prüfnummer: {pruefnummer}")
        self._timer.start()
        self._load_step(0)

    def _load_step(self, index: int) -> None:
        self._step = index
        self._running = False
        self._review = False
        self._phase = ""
        self._ready = ()
        self._bolt = "?"    # Bolzenzustand für die neue Anzeige erneut melden
        self._latest = {}   # CSV-Zeilen nur mit Werten des aktuellen Schritts
        self._csv_last = -math.inf   # erste Zeile eines Schritts sofort schreiben
        self._csv_worst = "OK"       # schlechtester Status seit der letzten CSV-Zeile
        self.running_changed.emit(False)
        self.progress.emit(0.0, 0.0)
        self.step_changed.emit(index)
        action = STEPS[index]["action"]
        # Simulation: Werker schiebt den Bolzen ein / zieht ihn
        if action in ("bolt_in", "bolt_out") and hasattr(self._hw, "simulate_bolt"):
            self._hw.simulate_bolt(action == "bolt_in")
        self._tick()

    def _complete_step(self, status: Optional[str] = None, text: str = "") -> None:
        self._stop_workers()
        step = STEPS[self._step]
        if status is not None:
            attempt = self._attempts.get(self._step, 0) + 1
            self._attempts[self._step] = attempt
            name = step["name"] + (f" (Versuch {attempt})" if attempt > 1 else "")
            self._results.append({"step": self._step + 1, "sensor": name,
                                  "worst_status": status, "text": text})
            self._csv.add_result(self._step + 1, name, text, status)
            self.log_message.emit(f"{name}: {text} → {status}")
        else:
            self.log_message.emit(f"{step['name']} abgeschlossen.")
        self.step_result.emit(self._step, status or "OK", text)
        self._bolt_expect = None
        if status is not None and step["action"] in _REPEATABLE:
            # Nicht automatisch weiter: Werker wählt „Weiter“ oder „Erneut durchführen“
            self._set_running(False)
            self._review = True
            self.step_review.emit(self._step, status, text)
            return
        self._advance()

    def _advance(self) -> None:
        if self._step + 1 >= len(STEPS):
            self._finish_test()
        else:
            self._load_step(self._step + 1)

    def _finish_test(self) -> None:
        self._timer.stop()
        self._running = False
        self._hw.stop_motor()
        passed = self._evaluator.calculate_pass_fail(self._results)
        self._csv.finalize(passed)
        self._active = False
        self.log_message.emit(f"Prüfung abgeschlossen.  Ergebnis: {'BESTANDEN' if passed else 'NICHT BESTANDEN'}")
        self.log_message.emit(f"Prüfbericht gespeichert: {self._csv.path}")
        self.test_finished.emit(passed)

    # ── Abbruch ───────────────────────────────────────────────────────────────

    def user_abort(self) -> None:
        self._abort("Abbruch durch Bediener (ABBRUCH-Knopf)", [])

    def shutdown(self) -> None:
        """Fenster wird geschlossen – laufende Prüfung sicher beenden."""
        self._abort("Programm geschlossen", [])

    def _abort(self, title: str, reasons: list[str]) -> None:
        if not self._active:
            return
        self._active = False
        self._timer.stop()
        self.log_message.emit(f"ABBRUCH: {title}" + (f" – {', '.join(reasons)}" if reasons else ""))
        self._safe_shutdown()
        self._csv.finalize(False, note=f"Abgebrochen: {title}" + (f" ({', '.join(reasons)})" if reasons else ""))
        self._running = False
        self.running_changed.emit(False)
        self.aborted.emit(title, reasons)

    def _safe_shutdown(self) -> None:
        """Motor aus, oberen Zylinder einfahren, Leckage entlüften. Der untere bleibt.
        Zylinder zuerst: das Entlüften blockiert für die eingestellte Entlüftungszeit."""
        self._stop_workers()
        self._hw.stop_motor()
        do = self._hw.read_do()
        if do is None or do[UP_EXT]:
            errors = [e for e in (self._hw.write_do(UP_EXT, 0), self._hw.write_do(UP_RET, 1)) if e]
            self.log_message.emit(f"Oberer Zylinder einfahren: {', '.join(errors) or 'OK'}")
        leak_running = self._leak is not None and self._leak.running
        if leak_running or do is None or do[DO6]:
            def write(ch: int, bit: int) -> None:
                error = self._hw.write_do(ch, bit)
                if error:
                    raise RuntimeError(error)
            for err in vent_blocking(write, _vent_s()):
                self.log_message.emit(f"Entlüften: {err}")
            p = self._hw.read("pressure")
            self.log_message.emit("Leckage-Strang entlüftet"
                                  + (f": DS2 {p:.3f} bar." if p is not None else "."))

    # ── Werker-Aktionen ───────────────────────────────────────────────────────

    def next_step(self) -> None:
        """„Weiter“ nach dem Ergebnis eines Messschritts."""
        if not self._active or not self._review or self._blocked is not None:
            return
        self._review = False
        self._advance()

    def repeat_step(self) -> None:
        """„Erneut durchführen“: Messschritt noch einmal. Das alte Ergebnis bleibt im
        Prüfbericht stehen (als wiederholt markiert), gewertet wird der letzte Durchlauf."""
        if not self._active or not self._review or self._blocked is not None:
            return
        self._review = False
        step = STEPS[self._step]
        last = self._results[-1]
        last["superseded"] = True
        last["sensor"] += " – wiederholt, nicht gewertet"
        self._csv.supersede_last_result()
        self._disabled_critical.clear()
        self.log_message.emit(f"{step['name']} wird wiederholt.")
        if step["action"] == "torque":
            # Unterer Zylinder ist nach der Kraftprüfung eingefahren. Sperrbolzen bleibt
            # stecken (Nutzer 19.10.2026): nur unten wieder aus (Grundstellung), danach
            # startet die Kraftprüfung direkt neu (_tick_torque, Phase "rehome")
            self.step_changed.emit(self._step)   # Ergebnisanzeige/„Weiter“ ausblenden
            self._set_running(True, CYLINDER_MOVE_S)
            if self._move(LO_EXT):
                self._enter("rehome", CYLINDER_MOVE_S, "Unterer Zylinder fährt aus (Grundstellung) …")
            return
        self._load_step(self._step)
        self.start_step()

    def skip_force_test(self) -> None:
        """Sperrbolzen einschieben → Kraftprüfung → Sperrbolzen ziehen überspringen (z. B.
        wenn die Kraftprüfung am Prüfstand gerade nicht geht). Nur vor dem Einschieben des
        Bolzens: Zylinder stehen dann in Grundstellung, es muss nichts gefahren werden.
        Im Bericht steht die Kraftprüfung als „übersprungen – nicht geprüft“ (WARNUNG)."""
        if (not self._active or self._running or self._review or self._critical_active
                or self._blocked is not None or STEPS[self._step]["action"] != "bolt_in"):
            return
        if bolt_inserted(self._hw.read_di()) is not False:
            self.now_text.emit("Überspringen nicht möglich: Sperrbolzen erst ziehen", "WARNUNG")
            return
        skipped = [i for i, s in enumerate(STEPS) if s["action"] in ("bolt_in", "torque", "bolt_out")]
        torque = next(i for i in skipped if STEPS[i]["action"] == "torque")
        text = "übersprungen – nicht geprüft (Werker)"
        self._results.append({"step": torque + 1, "sensor": STEPS[torque]["name"],
                              "worst_status": "WARNUNG", "text": text})
        self._csv.add_result(torque + 1, STEPS[torque]["name"], text, "WARNUNG")
        self.log_message.emit("Kraftprüfung mit Sperrbolzen übersprungen (Werker).")
        for i in skipped:
            self.step_result.emit(i, "ÜBERSPRUNGEN", text)
        self._step = skipped[-1]
        self._advance()

    def start_step(self) -> None:
        if (not self._active or self._running or self._review or self._critical_active
                or self._blocked is not None):
            return
        ok, reason = self._readiness(self._hw.read_di(), self._hw.read_do())
        if not ok:
            self.now_text.emit(reason, "WARNUNG")
            return
        action = STEPS[self._step]["action"]
        getattr(self, f"_begin_{action}")()


    def resume_after_critical(self, sensor_id: str) -> None:
        if not self._critical_active:
            return
        error = self._hw.start_motor(_settings.MOTOR_RUN_RPM)
        if error:
            self._critical_active = False
            self._abort("Motor ließ sich nicht neu starten", [error])
            return
        self._disabled_critical.add(sensor_id)
        self._critical_active = False
        self._phase_end += time.monotonic() - self._paused_at
        self._step_start += time.monotonic() - self._paused_at
        self._start_workers()
        self.log_message.emit(f"Motor neu gestartet. Krit. Grenzwert für '{SENSOR_MAP[sensor_id]['name']}' "
                              "in diesem Schritt deaktiviert.")
        self.sensor_critical_disabled.emit(sensor_id)

    # ── Takt ──────────────────────────────────────────────────────────────────

    def _tick(self) -> None:
        if not self._active:
            return
        di = self._hw.read_di()
        violations = self._violations(di)
        state =(not violations, "Sicherheit OK" if not violations else "FEHLT: " + ", ".join(violations))
        if state != self._safety:
            self._safety = state
            self.safety_state.emit(*state)
        bolt = bolt_inserted(di)
        if bolt != self._bolt:
            self._bolt = bolt
            self.bolt_state.emit(bolt)
        if violations:
            self._set_blocked(violations)
            return
        if self._blocked is not None:
            if self._blocked:   # wieder in Ordnung → Hinweisfeld zeigt es, Werker bestätigt
                self._blocked = []
                self.safety_blocked.emit([], self._interrupted)
            return
        if self._critical_active or self._review:
            return
        if self._running:
            action = STEPS[self._step]["action"]
            getattr(self, f"_tick_{action}")(time.monotonic())
            if self._running and self._step_total > 0:
                self.progress.emit(max(0.0, self._step_start + self._step_total - time.monotonic()),
                                   self._step_total)
        else:
            ready = self._readiness(di, self._hw.read_do())
            if ready != self._ready:
                self._ready = ready
                self.ready_changed.emit(*ready)
                self.now_text.emit(*self._idle_text(ready))

    def _ignored_di(self) -> list[int]:
        return STEPS[self._step].get("ignore_di", [])

    def _violations(self, di) -> list[str]:
        """Digitaleingänge + Überdruck DS1 (gilt immer, egal welcher Schritt)."""
        violations = di_violations(di, self._bolt_expect, self._ignored_di())
        p = self._hw.read("pressure_cyl")
        limit = _settings.CYL_MAX_PRESSURE_BAR + _settings.CYL_PRESSURE_TOLERANCE_BAR
        if p is not None and p > limit:
            violations.append(f"Druck DS1 zu hoch: {p:.1f} bar (max. {_settings.CYL_MAX_PRESSURE_BAR:g} bar)")
        return violations

    # ── Sicherheitspause ──────────────────────────────────────────────────────

    def _set_blocked(self, violations: list[str]) -> None:
        """Sicherheitsbedingung verletzt: laufenden Schritt sicher unterbrechen (Motor aus,
        Leckage entlüften, oben einfahren) und warten – die Prüfung selbst bleibt erhalten."""
        if self._blocked is None:
            self._interrupted = ""
            if self._running or self._critical_active:
                self._interrupted = STEPS[self._step]["name"]
                self._safe_shutdown()
                self._leak = None
                self._critical_active = False
                self._bolt_expect = None
                self._set_running(False)
                self._csv.add_note(f"Schritt {self._step + 1} {self._interrupted} unterbrochen: "
                                   + ", ".join(violations))
            self.log_message.emit("SICHERHEIT: " + ", ".join(violations)
                                  + (f" – {self._interrupted} unterbrochen" if self._interrupted else ""))
            self.now_text.emit("Sicherheitsbedingung fehlt – siehe Hinweis", "KRITISCH")
            self._ready = (False, "Sicherheitsbedingung fehlt")
            self.ready_changed.emit(*self._ready)
        if violations != self._blocked:
            self._blocked = violations
            self.safety_blocked.emit(violations, self._interrupted)

    def retry_safety(self) -> bool:
        """„Erneut prüfen“: True, wenn alles erfüllt ist und es weitergehen kann."""
        if not self._active or self._blocked is None:
            return True
        violations = self._violations(self._hw.read_di())
        if violations:
            self._set_blocked(violations)
            return False
        step = STEPS[self._step]["name"]
        self.log_message.emit(f"Sicherheitsbedingungen wieder erfüllt – weiter mit „{step}“"
                              + (" (Schritt startet neu)" if self._interrupted else "") + ".")
        self._blocked = None
        self._interrupted = ""
        self._ready = ()
        self._bolt = "?"
        self.safety_cleared.emit()
        if self._review:   # Ergebnisanzeige wiederherstellen (Hinweistext hat sie überschrieben)
            last = self._results[-1]
            self.step_review.emit(self._step, last["worst_status"], last["text"])
        self._tick()
        return True

    def _readiness(self, di, do) -> tuple[bool, str]:
        """Darf der Startknopf des aktuellen Schritts gedrückt werden? (ok, Grund)"""
        action = STEPS[self._step]["action"]
        bolt = bolt_inserted(di)
        home = do is not None and at_home(do)
        if action == "run":
            if bolt is not False:
                return False, "Sperrbolzen steckt – bitte ziehen"
            if not home:
                return False, "Zylinder nicht in Grundstellung"
        elif action == "bolt_in" and bolt is not True:
            return False, "Warte auf Sperrbolzen (DI3) …"
        elif action == "torque":
            if bolt is not True:
                return False, "Sperrbolzen nicht erkannt – bitte einschieben"
            if not home:
                return False, "Zylinder nicht in Grundstellung"
        elif action == "bolt_out" and bolt is not False:
            return False, "Warte, bis der Sperrbolzen gezogen ist (DI3) …"
        return True, ""

    def _idle_text(self, ready: tuple[bool, str]) -> tuple[str, str]:
        ok, reason = ready
        action = STEPS[self._step]["action"]
        if not ok:
            if action in ("bolt_in", "bolt_out"):
                verb = "einschieben" if action == "bolt_in" else "ziehen"
                return f"Jetzt: Sperrbolzen {verb}", "AKTIV"
            return reason, "WARNUNG"
        if action == "bolt_in":
            return "Sperrbolzen erkannt ✓ – „Weiter“ klicken", "OK"
        if action == "bolt_out":
            return "Sperrbolzen gezogen ✓ – „Weiter“ klicken", "OK"
        if action == "prepare":
            return "Jetzt: Anschlüsse prüfen, dann starten", "AKTIV"
        return f"Jetzt: „{STEPS[self._step]['button']}“ klicken", "AKTIV"

    def _set_running(self, running: bool, total_s: float = 0.0) -> None:
        self._running = running
        if running:
            self._step_start = time.monotonic()
            self._step_total = total_s
        else:
            self._phase = ""
            self._step_total = 0.0
            self._ready = ()
            self.progress.emit(0.0, 0.0)
        self.running_changed.emit(running)

    def _enter(self, phase: str, duration: float, text: str, color: str = "AKTIV") -> None:
        self._phase = phase
        self._phase_end = time.monotonic() + duration
        self.now_text.emit(text, color)

    def _move(self, channel: int) -> bool:
        """Zylinderbewegung mit Regelprüfung; bei Fehler Abbruch."""
        error = move(channel, self._hw.read_do() or [None] * 8, self._hw.write_do)
        if error:
            self._abort("Zylinder konnte nicht geschaltet werden", [error])
            return False
        return True

    def _write_valves(self, valves: Optional[dict[int, int]]) -> bool:
        for ch, bit in (valves or {}).items():
            error = self._hw.write_do(ch, bit)
            if error:
                self._abort("Leckage-Ventil konnte nicht geschaltet werden", [error])
                return False
        return True

    # ── Schritt: Vorbereitung ─────────────────────────────────────────────────

    def _begin_prepare(self) -> None:
        self._set_running(True, 2 * CYLINDER_MOVE_S)
        self.log_message.emit("Checkliste bestätigt – Zylinder fahren in Grundstellung.")
        if self._move(UP_RET):
            self._enter("up_ret", CYLINDER_MOVE_S, "Grundstellung: oberer Zylinder fährt ein …")

    def _tick_prepare(self, now: float) -> None:
        if now < self._phase_end:
            return
        if self._phase == "up_ret":
            if self._move(LO_EXT):
                self._enter("lo_ext", CYLINDER_MOVE_S, "Grundstellung: unterer Zylinder fährt aus …")
        elif self._phase == "lo_ext":
            do = self._hw.read_do()
            if do is None or not at_home(do):
                detail = "DO nicht lesbar" if do is None else ", ".join(home_deviations(do))
                self._abort("Grundstellung nicht erreicht", [detail])
                return
            self._complete_step()

    # ── Schritt: Leckage ──────────────────────────────────────────────────────

    def _begin_leak(self) -> None:
        step = STEPS[self._step]
        hold = step["hold_seconds"]
        # _settings statt direktem Import: apply_grenzwerte_to_settings() ändert den Wert zur Laufzeit
        fill, settle, vent = _settings.LEAK_FILL_S, _settings.LEAK_SETTLE_S, _vent_s()
        self._set_running(True, fill + settle + hold + vent)
        self._leak = LeakSequence(fill, hold, vent, settle_s=settle)
        self._start_workers()
        self.log_message.emit(f"Leckageprüfung gestartet: Befüllen {fill:g} s, Beruhigen {settle:g} s, "
                              f"Halten {hold:g} s, Entlüften {vent:g} s.")
        self._write_valves(self._leak.start(time.monotonic()))

    def _tick_leak(self, now: float) -> None:
        seq = self._leak
        p = self._latest.get("pressure", math.nan)
        if not self._write_valves(seq.update(now, p)):
            return
        if not seq.done:
            text = f"{phase_name(seq.phase)} – noch {_mmss(seq.remaining_s(now))}"
            if seq.phase == "hold" and not math.isnan(seq.drop_bar()):
                text += f"  ·  Druckabfall bisher {seq.drop_bar():.3f} bar"
            self.now_text.emit(text, "AKTIV")
            return
        # Nur zur Kontrolle (drucklos zeigt DS2 ≈ 0,2 bar) – keine Bewertung
        self.log_message.emit("Entlüftet: DS2 " + ("–" if math.isnan(seq.p_vent)
                                                    else f"{seq.p_vent:.3f} bar") + ".")
        p_fill, drop = seq.p_start, seq.drop_bar()
        if math.isnan(p_fill) or p_fill < _settings.LEAK_MIN_FILL_BAR:
            shown = "–" if math.isnan(p_fill) else f"{p_fill:.3f} bar"
            status = "KRITISCH"
            text = (f"kein Prüfdruck ({shown} < {_settings.LEAK_MIN_FILL_BAR:g} bar) – "
                    "Schlauch / Druckregler prüfen")
        else:
            status = self._evaluator.evaluate_drop(drop, _settings.LEAK_WARN_DROP_BAR,
                                                   _settings.LEAK_CRITICAL_DROP_BAR)
            text = f"Druckabfall {drop:.3f} bar ({p_fill:.3f} → {seq.p_end:.3f} bar)"
        self._leak = None
        self._complete_step(status, text)

    # ── Schritt: Lastlauf ─────────────────────────────────────────────────────

    def _begin_run(self) -> None:
        step = STEPS[self._step]
        rpm = _settings.MOTOR_RUN_RPM
        self._bolt_expect = "out"
        error = self._hw.start_motor(rpm)
        if error:
            self._bolt_expect = None
            self.log_message.emit(error)
            self.now_text.emit(error, "KRITISCH")
            return
        self._set_running(True, MOTOR_RAMP_S + step["duration_seconds"])
        self.log_message.emit(f"Motor gestartet: {rpm:.0f} rpm (Sollwert-Skalierung ist Annahme).")
        self._enter("ramp", MOTOR_RAMP_S, f"Motor läuft hoch ({rpm:.0f} rpm) …")

    def _tick_run(self, now: float) -> None:
        if self._phase == "ramp" and now >= self._phase_end:
            self._max, self._worst = {}, {}
            self._samples = {"speed": []}
            self._rpm1_rejected_start = getattr(self._hw, "rpm1_rejected", 0)
            self._start_workers()
            self._phase = "measure"
            self._phase_end = now + STEPS[self._step]["duration_seconds"]
            # Anfangsspitze (RPM1) nicht in die Bewertung am Ende – nur Anzeige
            self._settle_end = now + _settings.RUN_SETTLE_S
        if self._phase == "measure":
            if now < self._phase_end:
                self.now_text.emit(f"Lastlauf – noch {_mmss(self._phase_end - now)}", "AKTIV")
                return
            self._stop_workers()
            self._hw.stop_motor()
            self.log_message.emit("Motor gestoppt.")
            status, parts = "OK", []
            for sid in STEPS[self._step]["ids"]:
                if sid == "speed":
                    continue
                status = self._evaluator.worst(status, self._worst.get(sid, "OK"))
                if sid in self._max:
                    parts.append(f"{SENSOR_MAP[sid]['name']} max {self._max[sid]:.1f} {SENSOR_MAP[sid]['unit']}")
            if "speed" in STEPS[self._step]["ids"]:
                rpm_status, rpm_text = self._rpm1_result()
                status = self._evaluator.worst(status, rpm_status)
                parts.append(rpm_text)
            self._complete_step(status, " · ".join(parts) or "keine Messwerte")

    def _rpm1_result(self) -> tuple[str, str]:
        """Drehzahlsensor RPM1: Ø über den Lastlauf gegen die Soll-Drehzahl."""
        values = self._samples.get("speed", [])
        target = _settings.MOTOR_RUN_RPM
        if not values:
            return "KRITISCH", "RPM1: keine Messwerte"
        mean = _mean(values)
        dev = (mean - target) / target * 100.0 if target else math.inf
        status = self._evaluator.evaluate_drop(abs(dev), _settings.RPM1_WARN_PCT,
                                               _settings.RPM1_CRITICAL_PCT)
        text = (f"RPM1 Ø {mean:.0f} RPM (Soll {target:.0f}, Abw. {dev:+.1f} %, "
                f"min {min(values):.0f} / max {max(values):.0f})")
        # Ausreißer-Filter (hardware/rpm_filter.py): verworfene Werte offen ausweisen
        rejected = getattr(self._hw, "rpm1_rejected", 0) - getattr(self, "_rpm1_rejected_start", 0)
        if rejected:
            text += f" · {rejected} Ausreißer verworfen"
            self.log_message.emit(f"RPM1: {rejected} unplausible Messwerte (Ausreißer) verworfen.")
        return status, text

    # ── Schritt: Sperrbolzen / Sichtprüfung ───────────────────────────────────

    def _begin_bolt_in(self) -> None:
        self._complete_step()

    def _begin_bolt_out(self) -> None:
        self._set_running(True, CYLINDER_MOVE_S)
        if self._move(LO_EXT):
            self._enter("lo_ext", CYLINDER_MOVE_S, "Unterer Zylinder fährt aus (Grundstellung) …")

    def _tick_bolt_out(self, now: float) -> None:
        if now < self._phase_end:
            return
        do = self._hw.read_do()
        if do is None or not at_home(do):
            detail = "DO nicht lesbar" if do is None else ", ".join(home_deviations(do))
            self._abort("Grundstellung nicht erreicht", [detail])
            return
        self._complete_step()

    def _begin_visual(self) -> None:
        self._complete_step("OK", "Sichtprüfung durch Werker bestätigt")

    # ── Schritt: Kraftprüfung ─────────────────────────────────────────────────

    def _begin_torque(self) -> None:
        # Keine Druckwarnung mehr vorab (Nutzer 19.10.2026) – Knopf startet direkt
        self._set_running(True)
        if self._hw.read("pressure_cyl") is None:
            self._abort("Zylinderdruck DS1 nicht lesbar", [])
            return
        hold = STEPS[self._step]["hold_seconds"]
        self._step_start = time.monotonic()
        self._step_total = TORQUE_SETTLE_S + hold + 2 * CYLINDER_MOVE_S
        self._samples = {"torque": [], "torque_nm1": [], "torque_nm1_v": [], "pressure_cyl": []}
        self._start_workers()
        if not self._move(UP_EXT):
            return
        self._bolt_expect = "in"
        self.log_message.emit("Oberer Zylinder fährt aus – Kraftprüfung läuft.")
        self._enter("settle", TORQUE_SETTLE_S, "Oberer Zylinder fährt aus und baut Kraft auf …")

    def _tick_torque(self, now: float) -> None:
        if self._phase == "rehome":   # „Erneut durchführen“: unten ist wieder aus
            if now < self._phase_end:
                return
            do = self._hw.read_do()
            if do is None or not at_home(do):
                detail = "DO nicht lesbar" if do is None else ", ".join(home_deviations(do))
                self._abort("Grundstellung nicht erreicht", [detail])
                return
            self._load_step(self._step)
            self.start_step()
            return
        if self._phase == "settle" and now >= self._phase_end:
            self._samples = {k: [] for k in self._samples}
            self._phase = "hold"
            self._phase_end = now + STEPS[self._step]["hold_seconds"]
        if self._phase == "hold":
            if now < self._phase_end:
                m = _mean(self._samples["torque"])
                shown = "" if math.isnan(m) else f"  ·  Ø {m:.1f} Nm"
                self.now_text.emit(f"Kraftprüfung – noch {_mmss(self._phase_end - now)}{shown}", "AKTIV")
                return
            self._stop_workers()
            if self._move(UP_RET):
                self._enter("retract", CYLINDER_MOVE_S, "Oberer Zylinder fährt ein …")
            return
        if self._phase == "retract" and now >= self._phase_end:
            if self._move(LO_RET):
                self._enter("relieve", CYLINDER_MOVE_S, "Getriebe wird entlastet (unterer Zylinder fährt ein) …")
            return
        if self._phase == "relieve" and now >= self._phase_end:
            self._complete_step(*self._torque_result())

    def _torque_result(self) -> tuple[str, str]:
        torque = self._samples.get("torque", [])
        if not torque:
            return "KRITISCH", "keine Messwerte"
        mean, peak = _mean(torque), max(torque)
        nm1, p = _mean(self._samples["torque_nm1"]), _mean(self._samples["pressure_cyl"])
        u_nm1 = _mean(self._samples["torque_nm1_v"])
        status = self._evaluator.evaluate_min(mean, _settings.TORQUE_PASS_NM)
        src = "NM1" if _settings.TORQUE_SOURCE == "nm1" else "DS1"
        text = (f"Ø {mean:.1f} Nm aus {src} (Spitze {peak:.1f}, Soll ≥ {_settings.TORQUE_PASS_NM:g} Nm)"
                f" · NM1 Ø {nm1:.1f} Nm ({u_nm1:.3f} V) · DS1 Ø {p:.2f} bar")
        return status, text

    # ── Sensoren ──────────────────────────────────────────────────────────────

    def _start_workers(self) -> None:
        self._stop_workers()
        for sensor_id in STEPS[self._step]["ids"]:
            worker = _SensorWorker(self._hw, sensor_id, self._evaluator)
            worker.data_ready.connect(self._on_data)
            worker.start()
            self._workers.append(worker)

    def _stop_workers(self) -> None:
        for w in self._workers:
            w.stop()
        self._workers.clear()

    def _on_data(self, data: dict, status: str) -> None:
        if not self._active:
            return
        sensor_id, value = next(iter(data.items()))
        self._latest[sensor_id] = value
        action = STEPS[self._step]["action"]
        if action != "run":
            status = "OK"   # Druck/Moment werden am Schrittende bewertet, nicht live
        if action == "torque" and self._phase == "hold" and sensor_id in self._samples:
            self._samples[sensor_id].append(value)
        # Erste RUN_SETTLE_S s der Messung zählen nicht für das Ergebnis (Ø/min/max/Status);
        # der Not-Halt bei kritischem Live-Wert bleibt davon unberührt
        settled = time.monotonic() >= self._settle_end
        if action == "run" and sensor_id == "speed" and self._phase == "measure" and settled:
            self._samples.setdefault("speed", []).append(value)
        if action == "run" and settled:
            self._max[sensor_id] = max(self._max.get(sensor_id, value), value)
            if status == "KRITISCH" and sensor_id in self._disabled_critical:
                status = "WARNUNG"
            self._worst[sensor_id] = self._evaluator.worst(self._worst.get(sensor_id, "OK"), status)
        # Live wird alle MEASUREMENT_INTERVAL_MS gemessen, ins CSV nur alle CSV_INTERVAL_S
        # eine Zeile mit den jeweils letzten Werten aller Sensoren des Schritts
        self._csv_worst = self._evaluator.worst(self._csv_worst, status)
        now = time.monotonic()
        if now - self._csv_last >= _settings.CSV_INTERVAL_S:
            self._csv_last = now
            self._csv.write_row(self._latest, self._step + 1, self._csv_worst)
            self._csv_worst = "OK"
        self.data_updated.emit(data, status)
        if status == "KRITISCH" and not self._critical_active:
            debounce = SENSOR_MAP.get(sensor_id, {}).get("critical_debounce", 1)
            self._critical_streak[sensor_id] = self._critical_streak.get(sensor_id, 0) + 1
            if self._critical_streak[sensor_id] >= debounce:
                self._critical_streak[sensor_id] = 0
                self._handle_critical(sensor_id, value)
        elif status != "KRITISCH":
            self._critical_streak[sensor_id] = 0

    def _handle_critical(self, sensor_id: str, value: float) -> None:
        self._critical_active = True
        self._paused_at = time.monotonic()
        self._stop_workers()
        self._hw.stop_motor()
        sensor_name = SENSOR_MAP[sensor_id]["name"]
        self.log_message.emit(f"KRITISCH: {sensor_name} = {value:.2f} – Motor gestoppt!")
        self.now_text.emit(f"KRITISCH: {sensor_name} = {value:.1f} – Motor gestoppt", "KRITISCH")
        self.critical_reached.emit(sensor_id, sensor_name, value)

    def critical_abort(self) -> None:
        self._critical_active = False
        self._abort("Abbruch nach kritischem Messwert", [])

    # ── Eigenschaften ─────────────────────────────────────────────────────────

    @property
    def step_results(self) -> list[dict]:
        return self._results

    @property
    def csv_path(self) -> Path:
        return self._csv.path

    @property
    def active(self) -> bool:
        return self._active
