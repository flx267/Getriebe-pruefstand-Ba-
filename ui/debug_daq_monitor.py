"""
DEBUG: Live DAQ Monitor – zeigt ALLE Ports der USB-4711A in Echtzeit.
Temporäres Werkzeug, nicht für Produktion.

Angezeigt werden:
  AI0–AI15   Rohspannung [V] + Beschriftung laut Pinplan + skalierter Wert
             laut aktueller Code-Zuordnung (SENSOR_CHANNEL_MAP)
  DI0–DI7    Digital-Eingänge
  DO0–DO7    Digital-Ausgänge (nur Rücklesen des aktuellen Zustands)
  AO0–AO1    Analog-Ausgänge (Hardware kann nicht zurückgelesen werden)
  CNT0       Zähler-Eingang als Frequenzmessung [Hz] (CNT1 kann das nicht)

Schreiboperationen:
  - Messbereich ±10 V der AI-Kanäle (siehe RealHardware._configure_ai_ranges),
    ohne den die Karte nur 0 V liefert.
  - NUR auf Knopfdruck „Motor starten": AO0 (Sollwert) + DO0 (Motor on).
    Start nur, wenn alle Bedingungen aus MOTOR_START_REQUIRED_DI erfüllt sind
    (Induktiv A–E, Not-Aus-Kreis). Motor stoppt automatisch bei „Motor stoppen",
    Wegfall einer Bedingung, Lesefehler oder Schließen des Fensters.
  - NUR auf Knopfdruck: Leckage-Ventile V3 (DO5) / V4 (DO6), einzeln oder als
    kompletter Ablauf „Leckageprüfung“ (hardware/leak_sequence.py, DO5/DO6):
    Befüllen 1/1 → Halten 0/LEAK_HOLD_DO6 → Entlüften 1/0 → Fertig 0/0.
    Abbruch und Schließen des Fensters fahren immer die Entlüft-Folge (nur DO6
    abschalten entlüftet nicht).
  - NUR auf Knopfdruck im Feld „Druck & Kraft“: Zylinder-Ventile V1/V2 (DO1–DO4, bistabil
    5/2, siehe CYLINDER_VALVES / CYLINDER_HOME). Ablauf: Grundstellung (unten aus, oben
    ein) → Sperrbolzen rein → oben aus/ein messen → oben ein → unten entlasten →
    Sperrbolzen raus → unten aus. Zusätzlich DO1–DO4 manuell per Knopf in der DO-Tabelle
    (ohne Reihenfolge-Regel). Im Feld erzwingt _cylinder_violation() die Reihenfolge; Einschalten
    einer Spule schaltet vorher die Gegenspule ab. Nur bei stehendem Motor; Motorstart
    nur in Grundstellung (DO1=0, DO2=1, DO3=1, DO4=0). Schließen des Fensters setzt
    DO1–DO4 auf 0 – die Zylinder bleiben dabei stehen, wo sie sind.
  - Kraftmessung: Drehmoment rechnerisch aus DS1 (M = p · π/4·d² · r) neben NM1 (AI4).

Druck-Anzeige: DS1 (AI2, Zylinder) und DS2 (AI3, Getriebe/Leckage), Skalierung laut
SENSOR_SCALE["pressure"] (Sensor 995410, Zwei-Punkt-Abgleich am Prüfstand).

Standalone starten:
    cd Pruefstand_Software
    python ui/debug_daq_monitor.py
"""

import sys
import os
import math
import random
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PyQt6.QtCore import Qt, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication, QDialog, QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from ui import icons, theme

import config.settings as _settings   # RPM1_FACTOR live lesen (einstellbar im Grenzwerte-Dialog)
from config.settings import (
    SENSOR_MAP, VALVE_CHANNEL_MAP, CYLINDER_VALVES, DI_LABELS,
    CYLINDER_BORE_MM, LEVER_ARM_MM, MOTOR_NOMINAL_RPM_AT_50HZ,
    MOTOR_ON_DO_CHANNEL, MOTOR_SPEED_AO_CHANNEL, MOTOR_AO_MAX_V, MOTOR_AO_MAX_HZ,
    MOTOR_TEST_DEFAULT_V, MOTOR_TEST_MAX_V, MOTOR_START_REQUIRED_DI,
    LEAK_HOLD_S, LEAK_VENT_STEP_S, LEAK_HOLD_DO6,
)
from hardware.leak_sequence import (
    DO5, DO6, LEAK_CRITICAL_DROP_BAR, LEAK_WARN_DROP_BAR,
    LeakSequence, phase_name, rate_drop, vent_blocking,
)
from hardware.cylinder_sequence import (
    CYL_HOME_DO, LO_EXT, LO_RET, NM_PER_BAR, UP_EXT, UP_RET,
    cylinder_violation, lower_extended, upper_retracted,
)
from hardware.real_hardware import SENSOR_CHANNEL_MAP, SENSOR_SCALE, _scale
from hardware.safety import di_violations

DEVICE_DESCRIPTION = "USB-4711A,BID#0"

AI_COUNT = 16
DI_COUNT = 8
DO_COUNT = 8
AO_COUNT = 2
CNT_COUNT = 1   # Treiber meldet 2 Zähler, Frequenzmessung geht aber nur auf CNT0

# Beschriftung laut Pin-Portbelegung-DAC-advantech.pdf (Rev. 0, 11.09.2026)
PINPLAN_AI = {0: "T1", 1: "T2", 2: "DS1", 3: "DS2", 4: "NM1", 7: "Vibrationssensor"}
PINPLAN_DI = DI_LABELS
PINPLAN_DO = {0: "Freq. Umw. Motor on"} | {ch: sig for sig, ch in VALVE_CHANNEL_MAP.items()}
PINPLAN_AO = {0: "Freq. Umw. Drehzahl"}
PINPLAN_CNT = {}   # RPM1 liegt laut Pinplan am Zähler-/Trigger-Bereich, Kanal noch unklar


def _volt_to_hz(voltage: float) -> float:
    return voltage / MOTOR_AO_MAX_V * MOTOR_AO_MAX_HZ


def _start_violations(di: list) -> list[str]:
    """Nicht erfüllte Startbedingungen (MOTOR_START_REQUIRED_DI = Sicherheit + Sperrbolzen
    gezogen); leer = Start erlaubt."""
    return di_violations(di, bolt="out")


# Umkehrung der Code-Zuordnung: AI-Kanal → sensor_id. Teilen sich mehrere Sensoren
# einen Kanal, gewinnt der erste Eintrag.
_CODE_AI: dict[int, str] = {}
for _sid, _ch in SENSOR_CHANNEL_MAP.items():
    _CODE_AI.setdefault(_ch, _sid)

# Ventile, die der Monitor schalten darf. DO0 (Motor) läuft nur über den Motor-Test.
_LEAK_VALVES: list[tuple[str, int, str]] = [
    ("V4", VALVE_CHANNEL_MAP["V4_6"], "Befüllen/Entlüften"),
    ("V3", VALVE_CHANNEL_MAP["V3_5"], "Absperren"),
]
_LEAK_VALVE_CHANNELS = {ch for _, ch, _ in _LEAK_VALVES}
# Zylinder-Ventile 5/2 bistabil (CYLINDER_VALVES): (Name, DO-Kanal, Funktion)
_CYL_VALVES: list[tuple[str, int, str]] = []
# Gegenspule je Kanal: Ausfahren ↔ Einfahren desselben Zylinders nie gleichzeitig an
_CYL_PARTNER: dict[int, int] = {}
for _cyl, _sig in CYLINDER_VALVES.items():
    _ext, _ret = VALVE_CHANNEL_MAP[_sig["extend"]], VALVE_CHANNEL_MAP[_sig["retract"]]
    _CYL_VALVES += [(_sig["extend"], _ext, f"Zylinder {_cyl} ausfahren"),
                    (_sig["retract"], _ret, f"Zylinder {_cyl} einfahren")]
    _CYL_PARTNER[_ext], _CYL_PARTNER[_ret] = _ret, _ext
    PINPLAN_DO[_ext] = f"{_sig['extend']} {_cyl} ausfahren"
    PINPLAN_DO[_ret] = f"{_sig['retract']} {_cyl} einfahren"
_CYL_VALVE_CHANNELS = {ch for _, ch, _ in _CYL_VALVES}
# Regeln/Kanäle gemeinsam mit dem Prüfablauf (hardware/cylinder_sequence.py)
_UP_EXT, _UP_RET, _LO_EXT, _LO_RET = UP_EXT, UP_RET, LO_EXT, LO_RET
_CYL_HOME_DO = CYL_HOME_DO
_upper_retracted = upper_retracted
_lower_extended = lower_extended
_cylinder_violation = cylinder_violation
_NM_PER_BAR = NM_PER_BAR
_DS1_CH = SENSOR_CHANNEL_MAP["pressure_cyl"]
_NM1_CH = SENSOR_CHANNEL_MAP["torque_nm1"]
_FORCE_AVG_N = 10   # gleitender Mittelwert über 10 × 200 ms (NM1 rauscht ≈ 170 mV)
_SWITCHABLE_CHANNELS = _LEAK_VALVE_CHANNELS | _CYL_VALVE_CHANNELS
_LEAK_PRESSURE_CH = SENSOR_CHANNEL_MAP["pressure"]   # DS2 – wird im Leckage-Ablauf bewertet
_VENT_ON_CLOSE_BAR = 0.35   # DS2 darüber beim Schließen → entlüften (drucklos zeigt er ≈ 0,2 bar)

# Drucksensoren laut Nutzer (25.09.2026): (Name, AI-Kanal, Strang, SENSOR_SCALE-Schlüssel)
_PRESSURE_AI: list[tuple[str, int, str, str]] = [
    ("DS1", _DS1_CH, "Zylinder", "pressure_cyl"),
    ("DS2", 3, "Getriebe / Leckage", "pressure"),
]

_POLL_INTERVAL_S = 0.2
_BAR_MAX_V = 10.0
_BAR_WIDTH = 120   # px, Balken ±10 V

# Töne wie im Prüfprogramm (ui/theme.py, theme.set_tone)
_T_OK = "ok"
_T_WARN = "warn"
_T_CRIT = "crit"
_T_DIM = "muted"
_T_TEXT = ""
_T_OFF = "off"



# ── Backends ──────────────────────────────────────────────────────────────────

class _RealBackend:
    """Liest alle Ports der Karte direkt über DAQNavi (unabhängig von RealHardware,
    damit kein FU-/COM-Port-Verbindungsaufbau blockiert)."""

    def __init__(self):
        from Automation.BDaq import ValueRange
        from Automation.BDaq.InstantAiCtrl import InstantAiCtrl

        self._ai = InstantAiCtrl(DEVICE_DESCRIPTION)
        for ch in self._ai.channels:
            ch.valueRange = ValueRange.V_Neg5To5
            ch.valueRange = ValueRange.V_Neg10To10

        self._di = self._open("InstantDiCtrl")
        self._do = self._open("InstantDoCtrl")
        self._ao = self._open("InstantAoCtrl")
        self._fm = self._open("FreqMeterCtrl")
        self.motor_on = False
        if self._fm is not None:
            try:
                self._fm.channelStart = 0
                self._fm.channelCount = CNT_COUNT
                self._fm.enabled = True
            except Exception as exc:
                print(f"[DAQ-Monitor] Frequenzmessung nicht verfügbar: {exc}")
                self._fm = None

    @staticmethod
    def _open(class_name: str):
        try:
            module = __import__(f"Automation.BDaq.{class_name}", fromlist=[class_name])
            return getattr(module, class_name)(DEVICE_DESCRIPTION)
        except Exception as exc:
            print(f"[DAQ-Monitor] {class_name} nicht verfügbar: {exc}")
            return None

    def read(self) -> dict:
        from Automation.BDaq import ErrorCode
        from Automation.BDaq.BDaqApi import BioFailed

        snap = {"ai": [math.nan] * AI_COUNT, "di": [None] * DI_COUNT,
                "do": [None] * DO_COUNT, "cnt": [math.nan] * CNT_COUNT, "error": ""}

        ret, data = self._ai.readData(0, AI_COUNT)
        if BioFailed(ret) or ret == ErrorCode.WarningParamOutOfRange or not data:
            snap["error"] = f"AI: {ret.name}"
        else:
            snap["ai"] = list(data)

        snap["di"] = self._read_port(self._di)
        snap["do"] = self._read_port(self._do)

        if self._fm is not None:
            ret, data = self._fm.read(CNT_COUNT)
            if not BioFailed(ret):
                snap["cnt"] = list(data)
        return snap

    @staticmethod
    def _read_port(ctrl) -> list:
        from Automation.BDaq.BDaqApi import BioFailed

        if ctrl is None:
            return [None] * 8
        ret, data = ctrl.readAny(0, 1)
        if BioFailed(ret) or not data:
            return [None] * 8
        return [(data[0] >> bit) & 1 for bit in range(8)]

    @property
    def can_drive_motor(self) -> bool:
        return self._ao is not None and self._do is not None and self._di is not None

    def motor_start(self, voltage: float) -> str:
        """Setzt erst den Sollwert (AO0), dann Motor on (DO0). Gibt Fehlertext oder "" zurück."""
        from Automation.BDaq import ValueRange
        from Automation.BDaq.BDaqApi import BioFailed

        if not self.can_drive_motor:
            return "AO/DO/DI nicht verfügbar"
        violations = _start_violations(self._read_port(self._di))
        if violations:
            return "Start verweigert: " + ", ".join(violations)
        # Bistabile Ventile: DO = 0 sagt nichts über die Lage → Start nur, wenn zuletzt
        # aktiv in die Grundstellung gefahren wurde (oben ein, unten aus)
        do = self._read_port(self._do)
        wrong = [f"DO{ch}={do[ch]}" for ch, bit in _CYL_HOME_DO.items() if do[ch] != bit]
        if wrong:
            return ("Start verweigert: Zylinder nicht in Grundstellung (" + ", ".join(wrong)
                    + ") – oben einfahren, unten ausfahren")
        voltage = max(0.0, min(voltage, MOTOR_TEST_MAX_V))

        # Karte steht ab Werk auf 0–5 V; Sollwert-Skalierung geht von 0–10 V aus
        self._ao.channels[MOTOR_SPEED_AO_CHANNEL].valueRange = ValueRange.V_0To10
        ret = self._ao.writeAny(MOTOR_SPEED_AO_CHANNEL, 1, None, [voltage])
        if BioFailed(ret):
            return f"AO{MOTOR_SPEED_AO_CHANNEL} schreiben fehlgeschlagen: {ret.name}"
        ret = self._do.writeBit(0, MOTOR_ON_DO_CHANNEL, 1)
        if BioFailed(ret):
            self.motor_stop()
            return f"DO{MOTOR_ON_DO_CHANNEL} schreiben fehlgeschlagen: {ret.name}"
        self.motor_on = True
        return ""

    def motor_stop(self) -> None:
        """Erst Motor on weg (DO0), dann Sollwert auf 0 V. Fehler werden nur geloggt,
        damit der zweite Schritt auch bei Fehler im ersten versucht wird."""
        if self._do is not None:
            try:
                self._do.writeBit(0, MOTOR_ON_DO_CHANNEL, 0)
            except Exception as exc:
                print(f"[DAQ-Monitor] DO{MOTOR_ON_DO_CHANNEL} aus fehlgeschlagen: {exc}")
        if self._ao is not None:
            try:
                self._ao.writeAny(MOTOR_SPEED_AO_CHANNEL, 1, None, [0.0])
            except Exception as exc:
                print(f"[DAQ-Monitor] AO{MOTOR_SPEED_AO_CHANNEL} auf 0 V fehlgeschlagen: {exc}")
        self.motor_on = False

    @property
    def can_switch_valves(self) -> bool:
        return self._do is not None

    def set_valve(self, channel: int, on: bool, sequence: bool = True) -> str:
        """Schaltet ein Ventil (DO1–DO6). Gibt Fehlertext oder "" zurück.
        sequence=False: manuelles Schalten aus der DO-Tabelle ohne Reihenfolge-Regel –
        Gegenspulen-Sperre und „nur bei stehendem Motor“ gelten trotzdem."""
        from Automation.BDaq.BDaqApi import BioFailed

        if channel not in _SWITCHABLE_CHANNELS:
            return f"DO{channel} ist kein Ventil – verweigert"
        if on and channel in _CYL_VALVE_CHANNELS and self.motor_on:
            return f"DO{channel}: Zylinder nur bei stehendem Motor – verweigert"
        if self._do is None:
            return "DO nicht verfügbar"
        if sequence and channel in _CYL_VALVE_CHANNELS:
            reason = _cylinder_violation(channel, on, self._read_port(self._do))
            if reason:
                return f"DO{channel} verweigert: {reason}"
        if on and channel in _CYL_PARTNER:
            partner = _CYL_PARTNER[channel]
            ret = self._do.writeBit(0, partner, 0)
            if BioFailed(ret):
                return f"DO{partner} (Gegenspule) aus fehlgeschlagen: {ret.name} – DO{channel} nicht geschaltet"
        ret = self._do.writeBit(0, channel, 1 if on else 0)
        if BioFailed(ret):
            return f"DO{channel} schreiben fehlgeschlagen: {ret.name}"
        return ""

    def close(self) -> None:
        if self.motor_on:
            self.motor_stop()
        if self._do is not None:
            for ch in sorted(_SWITCHABLE_CHANNELS):
                try:
                    self._do.writeBit(0, ch, 0)
                except Exception as exc:
                    print(f"[DAQ-Monitor] DO{ch} aus fehlgeschlagen: {exc}")
        if self._fm is not None:
            try:
                self._fm.enabled = False
            except Exception:
                pass
        for ctrl in (self._ai, self._di, self._do, self._ao, self._fm):
            if ctrl is not None:
                try:
                    ctrl.dispose()
                except Exception:
                    pass


class _SimBackend:
    """Ersatzwerte, wenn keine Karte/kein SDK vorhanden ist."""

    can_drive_motor = False
    can_switch_valves = True
    motor_on = False

    def __init__(self):
        self._base = [random.uniform(0.0, 8.0) for _ in range(AI_COUNT)]
        self._do = [0] * DO_COUNT

    def motor_start(self, voltage: float) -> str:
        return "Simulation – keine Karte"

    def motor_stop(self) -> None:
        pass

    def set_valve(self, channel: int, on: bool, sequence: bool = True) -> str:
        if channel not in _SWITCHABLE_CHANNELS:
            return f"DO{channel} ist kein Ventil – verweigert"
        if sequence and channel in _CYL_VALVE_CHANNELS:
            reason = _cylinder_violation(channel, on, self._do)
            if reason:
                return f"DO{channel} verweigert: {reason}"
        if on and channel in _CYL_PARTNER:
            self._do[_CYL_PARTNER[channel]] = 0
        self._do[channel] = 1 if on else 0
        return ""

    def read(self) -> dict:
        return {
            "ai": [b + random.uniform(-0.05, 0.05) for b in self._base],
            "di": [random.choice((0, 1)) if i < 5 else 1 for i in range(DI_COUNT)],
            "do": list(self._do),
            "cnt": [0.0] * CNT_COUNT,
            "error": "",
        }

    def close(self) -> None:
        pass


class _PollWorker(QThread):
    """Verbindet und liest im Hintergrund – blockiert nie den UI-Thread."""

    # (echte Hardware, Motor steuerbar, Ventile schaltbar, Fehlertext)
    connected = pyqtSignal(bool, bool, bool, str)
    connection_failed = pyqtSignal(str)       # Karte vorhanden, aber nicht nutzbar
    data_ready = pyqtSignal(dict)
    motor_state = pyqtSignal(bool, str)       # (läuft, Meldung)
    valve_message = pyqtSignal(bool, str)     # (Fehler?, Meldung)
    leak_state = pyqtSignal(dict)             # Zustand Leckage-Ablauf, siehe _emit_leak

    def __init__(self):
        super().__init__()
        self._running = False
        self._motor_request: float | None = None   # Sollspannung für Start
        self._stop_request = False
        self._valve_requests: list[tuple[int, bool, bool]] = []   # (Kanal, an, Reihenfolge prüfen)
        # Leckage-Ablauf: (fill_s, hold_s, vent_s, nur_entlüften)
        self._leak_request: tuple[float, float, float, bool] | None = None
        self._leak_abort = False
        self._leak_seq: LeakSequence | None = None
        self._leak_errors: list[str] = []
        self._vent_s = LEAK_VENT_STEP_S
        self._last_do: list = [None] * DO_COUNT
        self._last_ds2 = 0.0

    def request_motor_start(self, voltage: float) -> None:
        self._motor_request = voltage

    def request_motor_stop(self) -> None:
        self._stop_request = True

    def request_valve(self, channel: int, on: bool, sequence: bool = True) -> None:
        self._valve_requests.append((channel, on, sequence))

    def request_leak_start(self, fill_s: float, hold_s: float, vent_s: float) -> None:
        self._leak_request = (fill_s, hold_s, vent_s, False)

    def request_vent(self, vent_s: float) -> None:
        """Nur die Entlüft-Folge fahren (z. B. nach manuellem Befüllen per Einzelknopf)."""
        self._leak_request = (0.0, 0.0, vent_s, True)

    def request_leak_abort(self) -> None:
        self._leak_abort = True

    def run(self):
        self._running = True
        try:
            backend = _RealBackend()
            self.connected.emit(True, backend.can_drive_motor, backend.can_switch_valves, "")
        except ImportError as exc:
            # Nur ohne DAQNavi-SDK simulieren (z. B. Entwicklungs-PC)
            backend = _SimBackend()
            self.connected.emit(False, False, True, f"DAQNavi-SDK fehlt: {exc}")
        except Exception as exc:
            # Karte da, aber nicht nutzbar → KEINE Ersatzwerte, die echt aussehen
            msg = str(exc)
            if "0xE0000010" in msg:
                msg = ("Karte wird von einem anderen Programm benutzt "
                       "(z. B. zweiter DAQ-Monitor oder Advantech Navigator offen)")
            self.connection_failed.emit(msg)
            return

        try:
            while self._running:
                self._handle_motor_requests(backend)
                self._handle_valve_requests(backend)
                try:
                    snap = backend.read()
                except Exception as exc:
                    snap = {"error": f"Lesefehler: {exc}"}
                self._motor_watchdog(backend, snap)
                if snap.get("do"):
                    self._last_do = list(snap["do"])
                ai = snap.get("ai") or []
                if _LEAK_PRESSURE_CH < len(ai) and not math.isnan(ai[_LEAK_PRESSURE_CH]):
                    self._last_ds2 = _scale(ai[_LEAK_PRESSURE_CH], *SENSOR_SCALE["pressure"])
                self._leak_step(backend, snap)
                self.data_ready.emit(snap)
                time.sleep(_POLL_INTERVAL_S)
        finally:
            was_on = backend.motor_on
            # Leckage-Strang unter Druck → erst korrekt entlüften, dann erst alles aus.
            # Mit Halten 0/0 hält V3 den Druck auch bei DO5=DO6=0 → zusätzlich über DS2 prüfen
            if ((self._leak_seq is not None and self._leak_seq.running) or self._last_do[DO6]
                    or self._last_do[DO5] or self._last_ds2 > _VENT_ON_CLOSE_BAR):
                errors = vent_blocking(lambda ch, bit: self._write_valve(backend, ch, bit),
                                       self._vent_s)
                for err in errors:
                    print(f"[DAQ-Monitor] Entlüften: {err}")
            backend.close()
            if was_on:
                self.motor_state.emit(False, "Motor gestoppt (Monitor geschlossen).")

    def _handle_motor_requests(self, backend) -> None:
        if self._stop_request:
            self._stop_request = False
            self._motor_request = None
            backend.motor_stop()
            self.motor_state.emit(False, "Motor gestoppt.")
        elif self._motor_request is not None:
            voltage, self._motor_request = self._motor_request, None
            error = backend.motor_start(voltage)
            if error:
                self.motor_state.emit(False, error)
            else:
                hz = _volt_to_hz(voltage)
                self.motor_state.emit(
                    True, f"Motor läuft: AO0 = {voltage:.2f} V ≈ {hz:.1f} Hz "
                          f"≈ {hz / 50.0 * MOTOR_NOMINAL_RPM_AT_50HZ:.0f} RPM")

    def _handle_valve_requests(self, backend) -> None:
        while self._valve_requests:
            channel, on, sequence = self._valve_requests.pop(0)
            if (channel in _LEAK_VALVE_CHANNELS and self._leak_seq is not None
                    and self._leak_seq.running):
                self.valve_message.emit(True, "Leckage-Ablauf läuft – Einzelschalten gesperrt")
                continue
            try:
                error = backend.set_valve(channel, on, sequence)
            except Exception as exc:
                error = f"DO{channel}: {exc}"
            if error:
                self.valve_message.emit(True, error)
            else:
                self.valve_message.emit(False, f"DO{channel} → {'AN' if on else 'AUS'}")

    @staticmethod
    def _write_valve(backend, channel: int, bit: int) -> None:
        error = backend.set_valve(channel, bool(bit))
        if error:
            raise RuntimeError(error)

    def _apply_leak_valves(self, backend, valves: dict[int, int] | None) -> None:
        """Schreibt die Ventilzustände einer Phase. Bei Fehler → sofort in die
        Entlüft-Folge (bzw. dort weitermachen), nie einfach stehen bleiben."""
        if not valves:
            return
        failed = False
        for ch, bit in valves.items():
            try:
                self._write_valve(backend, ch, bit)
            except Exception as exc:
                failed = True
                self._leak_errors.append(f"DO{ch}={bit}: {exc}")
        if failed:
            self._apply_leak_valves(backend, self._leak_seq.abort(time.monotonic()))

    def _leak_step(self, backend, snap: dict) -> None:
        now = time.monotonic()
        if self._leak_request is not None:
            fill_s, hold_s, vent_s, vent_only = self._leak_request
            self._leak_request = None
            if self._leak_seq is not None and self._leak_seq.running:
                self._emit_leak(now, "Ablauf läuft bereits")
            elif backend.motor_on and not vent_only:
                self.leak_state.emit({"rejected": "Start verweigert: Leckageprüfung nur bei "
                                                  "stehendem Motor"})
            else:
                self._vent_s = vent_s
                self._leak_errors = []
                self._leak_seq = LeakSequence(fill_s, hold_s, vent_s)
                self._apply_leak_valves(backend, self._leak_seq.start(now, vent_only))

        seq = self._leak_seq
        if seq is None or seq.done:
            self._leak_abort = False
            return
        if self._leak_abort:
            self._leak_abort = False
            self._apply_leak_valves(backend, seq.abort(now))

        ai = snap.get("ai") or []
        voltage = ai[_LEAK_PRESSURE_CH] if _LEAK_PRESSURE_CH < len(ai) else math.nan
        pressure = math.nan if math.isnan(voltage) else _scale(voltage, *SENSOR_SCALE["pressure"])
        self._apply_leak_valves(backend, seq.update(now, pressure))
        self._emit_leak(now)

    def _emit_leak(self, now: float, message: str = "") -> None:
        seq = self._leak_seq
        self.leak_state.emit({
            "running": seq.running,
            "phase": seq.phase,
            "remaining_s": seq.remaining_s(now),
            "p_start": seq.p_start,
            "p_end": seq.p_end,
            "p_now": seq.p_last,
            "drop": seq.drop_bar(),
            "aborted": seq.aborted,
            "errors": list(self._leak_errors),
            "message": message,
        })

    def _motor_watchdog(self, backend, snap: dict) -> None:
        """Stoppt den Motor, sobald eine Startbedingung (Induktiv-Sensoren, Not-Aus-Kreis)
        wegfällt oder nicht mehr gelesen werden kann."""
        if not backend.motor_on:
            return
        violations = _start_violations(snap.get("di") or [None] * DI_COUNT)
        if violations:
            backend.motor_stop()
            self.motor_state.emit(False, "Motor gestoppt: " + ", ".join(violations))

    def stop(self):
        self._running = False
        # Reserve für die blockierende Entlüft-Folge (1 Wartezeit) im run()-finally
        self.wait(int(2000 + 2 * self._vent_s * 1000))


# ── Hilfsfunktionen ───────────────────────────────────────────────────────────

def _bar(voltage: float) -> int:
    """Balkenwert 0–1000 für |U| bezogen auf 10 V."""
    return max(0, min(1000, round(abs(voltage) / _BAR_MAX_V * 1000)))


def _make_bar() -> QProgressBar:
    bar = QProgressBar()
    bar.setRange(0, 1000)
    bar.setValue(0)
    bar.setTextVisible(False)
    bar.setFixedSize(_BAR_WIDTH, 6)
    return bar


def _status_color(sensor_id: str, value: float) -> str:
    s = SENSOR_MAP.get(sensor_id, {})
    crit_high = s.get("critical_threshold") or s.get("critical_high")
    crit_low  = s.get("critical_low")
    warn_high = s.get("warn_threshold") or s.get("warn_high")
    warn_low  = s.get("warn_low")
    if (crit_high is not None and value >= crit_high) or \
       (crit_low  is not None and value <= crit_low):
        return _T_CRIT
    if (warn_high is not None and value >= warn_high) or \
       (warn_low  is not None and value <= warn_low):
        return _T_WARN
    return _T_OK


def _section_title(text: str) -> QLabel:
    return theme.label(text, "section")


def _panel(layout) -> QFrame:
    """Panel mit runden Ecken wie im Prüfprogramm."""
    frame = theme.frame("panel")
    layout.setContentsMargins(14, 8, 14, 10)
    frame.setLayout(layout)
    return frame


def _header_row(grid: QGridLayout, headers: list[str]) -> None:
    for col, text in enumerate(headers):
        grid.addWidget(theme.label(text, "caption"), 0, col)


# ── Dialog ────────────────────────────────────────────────────────────────────

class DaqMonitorDialog(QDialog):
    """`hardware` wird aus Kompatibilität zu main_window.py akzeptiert, aber nicht
    benutzt – der Monitor liest die Karte immer direkt aus."""

    def __init__(self, hardware=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("DEBUG – DAQ Live Monitor (alle Ports)")
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        # Optik wie im Prüfprogramm: zentrales Stylesheet aus ui/theme.py (theme.apply)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

        self._build_ui()
        self._set_banner("Verbinde mit USB-4711A …", "active")
        self._fitted = False

        self._worker = _PollWorker()
        self._worker.connected.connect(self._on_connected)
        self._worker.connection_failed.connect(self._on_connection_failed)
        self._worker.data_ready.connect(self._on_data)
        self._worker.motor_state.connect(self._on_motor_state)
        self._worker.valve_message.connect(self._on_valve_message)
        self._worker.leak_state.connect(self._on_leak_state)
        self._worker.start()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(12, 10, 12, 8)

        # Kopfzeile wie im Prüfprogramm: Titel links, Verbindungsstatus + Schließen rechts
        header = theme.frame("panel")
        header.setFixedHeight(52)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(18, 0, 12, 0)
        hl.setSpacing(10)
        logo = theme.label("", "logo")
        logo.setPixmap(icons.pixmap("wrench", theme.MUTED, 20))
        title = theme.label("DAQ-Monitor", "apptitle")
        subtitle = theme.label("alle Ports USB-4711A  ·  Debug-Werkzeug", "pill")
        subtitle.setToolTip(
            f"Aktualisierung: {int(_POLL_INTERVAL_S * 1000)} ms\n"
            "Ausgänge nur per Knopf: Motor (AO0 + DO0), Zylinder-Ventile V1/V2 (DO1–DO4), "
            "Leckage-Ventile V3/V4 (DO5/DO6) einzeln oder als Ablauf")
        self._banner = theme.label("", "badge")
        self._banner_text = ""
        close_btn = theme.button("Schließen", "ghost", "x", height=34)
        close_btn.clicked.connect(self.close)
        hl.addWidget(logo)
        hl.addWidget(title)
        hl.addSpacing(4)
        hl.addWidget(subtitle)
        hl.addStretch()
        hl.addWidget(self._banner)
        hl.addSpacing(16)
        hl.addWidget(close_btn)
        root.addWidget(header)

        # Drei Spalten (Panels) nebeneinander, damit das Fenster auch auf Laptop-Bildschirmen
        # (z. B. 1536×816 bei 125 %) in der Höhe passt; Scrollbalken als Reserve.
        content = QWidget()
        columns = QHBoxLayout(content)
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(10)
        columns.addWidget(_panel(self._build_ai()), stretch=3)
        columns.addWidget(_panel(self._build_digital()), stretch=2)
        columns.addWidget(_panel(self._build_outputs()), stretch=2)

        scroll = QScrollArea()
        scroll.setWidget(content)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(scroll, stretch=1)

        self._error_label = theme.label("", None, _T_CRIT)
        root.addWidget(self._error_label)

    def _build_ai(self) -> QVBoxLayout:
        box = QVBoxLayout()
        box.addWidget(_section_title("Analog-Eingänge  AI0–AI15"))

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(3)
        _header_row(grid, ["Kanal", "Pinplan", "Spannung", "Balken (±10 V)",
                           "Code-Zuordnung", "Wert"])

        font_val = theme.font(11)
        self._ai_rows: list[dict] = []
        for ch in range(AI_COUNT):
            sid = _CODE_AI.get(ch)
            unit = SENSOR_MAP.get(sid, {}).get("unit", "") if sid else ""
            pin = PINPLAN_AI.get(ch, "frei")

            ch_lbl   = QLabel(f"AI{ch}")
            pin_lbl  = QLabel(pin)
            volt_lbl = QLabel("–")
            bar_lbl  = _make_bar()
            code_lbl = QLabel(sid or "–")
            val_lbl  = QLabel("–")
            volt_lbl.setFont(font_val)
            volt_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            theme.set_tone(pin_lbl, _T_TEXT if ch in PINPLAN_AI else _T_DIM)
            theme.set_tone(code_lbl, _T_TEXT if sid else _T_DIM)

            for col, lbl in enumerate((ch_lbl, pin_lbl, volt_lbl, bar_lbl, code_lbl, val_lbl)):
                grid.addWidget(lbl, ch + 1, col)

            self._ai_rows.append({"sid": sid, "unit": unit, "volt": volt_lbl,
                                  "bar": bar_lbl, "val": val_lbl})
        box.addLayout(grid)
        # Unter der AI-Tabelle ist Platz – Spalte 3 ist mit dem Motor-Test schon voll
        box.addLayout(self._build_pressure())
        box.addStretch()
        return box

    def _build_bit_section(self, box: QVBoxLayout, title: str, prefix: str,
                           count: int, labels: dict,
                           required: dict[int, int] | None = None,
                           extra: dict[int, QWidget] | None = None,
                           extra_header: str = "") -> list[QLabel]:
        box.addWidget(_section_title(title))
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(3)
        headers = ["Kanal", "Pinplan", "Zustand"]
        if required is not None:
            headers.append("Soll für Start")
        if extra:
            headers.append(extra_header)
            for ch, widget in extra.items():
                grid.addWidget(widget, ch + 1, len(headers) - 1)
        _header_row(grid, headers)
        leds = []
        for ch in range(count):
            pin = labels.get(ch, "frei")
            pin_lbl = QLabel(pin)
            theme.set_tone(pin_lbl, _T_TEXT if ch in labels else _T_DIM)
            led = QLabel("–")
            led.setFont(theme.font(11))
            grid.addWidget(QLabel(f"{prefix}{ch}"), ch + 1, 0)
            grid.addWidget(pin_lbl, ch + 1, 1)
            grid.addWidget(led, ch + 1, 2)
            if required is not None:
                soll = QLabel(str(required[ch]) if ch in required else "–")
                soll.setAlignment(Qt.AlignmentFlag.AlignCenter)
                theme.set_tone(soll, _T_TEXT if ch in required else _T_DIM)
                grid.addWidget(soll, ch + 1, 3)
            leds.append(led)
        box.addLayout(grid)
        return leds

    def _build_digital(self) -> QVBoxLayout:
        box = QVBoxLayout()
        self._di_leds = self._build_bit_section(
            box, "Digital-Eingänge  DI0–DI7", "DI", DI_COUNT, PINPLAN_DI,
            required=MOTOR_START_REQUIRED_DI)
        # Schalt-Buttons direkt in der DO-Zeile (spart Höhe). Zylinder DO1–DO4 hier manuell
        # ohne Reihenfolge-Regel (Wunsch Nutzer); geführter Ablauf im Feld „Druck & Kraft“.
        self._valve_buttons: dict[int, QPushButton] = {}
        for name, ch, role in _CYL_VALVES + _LEAK_VALVES:
            btn = theme.button("einschalten", size="sm")
            btn.setToolTip(f"{name} – {role} (DO{ch}) umschalten"
                           + ("\nManuell: keine Reihenfolge-Sperre, Gegenspule wird abgeschaltet"
                              if ch in _CYL_VALVE_CHANNELS else ""))
            btn.setEnabled(False)
            btn.clicked.connect(lambda _checked, c=ch: self._on_valve_toggle(c))
            self._valve_buttons[ch] = btn
        self._cyl_confirmed = False
        self._do_state: list = [None] * DO_COUNT
        self._do_leds = self._build_bit_section(
            box, "Digital-Ausgänge  DO0–DO7", "DO", DO_COUNT, PINPLAN_DO,
            extra=self._valve_buttons, extra_header="Ventil")

        self._valve_status = theme.label("", "caption", _T_DIM)
        box.addWidget(self._valve_status)
        box.addStretch()
        return box

    def _build_leak(self) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(4)
        box.addWidget(_section_title("Leckageprüfung  (DO5 / DO6, Druck DS2)"))

        row = QHBoxLayout()
        self._leak_spins: list[QDoubleSpinBox] = []
        for label, default, maximum in (("Befüllen", _settings.LEAK_FILL_S, 600.0),
                                        ("Halten", LEAK_HOLD_S, 3600.0),
                                        ("Entlüften", LEAK_VENT_STEP_S, 30.0)):
            row.addWidget(QLabel(label))
            spin = QDoubleSpinBox()
            spin.setRange(0.2, maximum)
            spin.setDecimals(1)
            spin.setSingleStep(1.0 if maximum > 30 else 0.5)
            spin.setSuffix(" s")
            spin.setValue(default)
            spin.setFixedWidth(94)   # Spalte 3 schmal halten (Fensterbreite!)
            spin.setProperty("size", "sm")
            row.addWidget(spin)
            self._leak_spins.append(spin)
        self._leak_spins[2].setToolTip("Dauer Entlüften (1/0), danach 0/0")
        row.addStretch()
        box.addLayout(row)

        buttons = QHBoxLayout()
        self._leak_start_btn = theme.button("Leckageprüfung starten", "primary", "play")
        self._leak_start_btn.clicked.connect(self._on_leak_start)
        self._leak_abort_btn = theme.button("Abbrechen / Entlüften", "danger", "square")
        self._leak_abort_btn.setToolTip(
            "Läuft ein Ablauf: sofort entlüften. Sonst: nur Entlüft-Folge fahren "
            "(1/0 → 0/0), z. B. nach manuellem Befüllen.")
        self._leak_abort_btn.clicked.connect(self._on_leak_abort)
        buttons.addWidget(self._leak_start_btn)
        buttons.addWidget(self._leak_abort_btn)
        buttons.addStretch()
        box.addLayout(buttons)

        self._leak_phase = QLabel("Bereit")
        theme.set_tone(self._leak_phase, _T_DIM)
        box.addWidget(self._leak_phase)
        self._leak_result = QLabel("DS2 Start – · Ende – · Abfall –")
        self._leak_result.setToolTip(
            f"Abfall während Halten · Warnung ab {LEAK_WARN_DROP_BAR} bar, "
            f"kritisch ab {LEAK_CRITICAL_DROP_BAR} bar (Platzhalter, config/settings.py → STEPS)")
        theme.set_tone(self._leak_result, _T_DIM)
        box.addWidget(self._leak_result)

        self._leak_running = False
        self._leak_start_btn.setEnabled(False)
        self._leak_abort_btn.setEnabled(False)
        return box

    def _build_pressure(self) -> QVBoxLayout:
        """Druck DS1/DS2 + Kraftmessung in EINEM Abschnitt (Fensterhöhe!)."""
        box = QVBoxLayout()
        box.setSpacing(4)
        title = _section_title(
            f"Druck & Kraft  (Zylinder ⌀{CYLINDER_BORE_MM:g} mm, r = {LEVER_ARM_MM:g} mm)")

        def fit(key: str) -> str:
            v_min, v_max, p_min, p_max = SENSOR_SCALE[key]
            slope = (p_max - p_min) / (v_max - v_min)
            return f"{slope:.4f}·U {p_min - v_min * slope:+.4f}"

        title.setToolTip(
            f"Abgleich (Referenz Display): DS1 p = {fit('pressure_cyl')} bar · "
            f"DS2 p = {fit('pressure')} bar\n"
            f"M = p · π/4·d² · r ≈ {_NM_PER_BAR:.1f} Nm/bar (ohne Reibung), "
            f"Mittel über {_FORCE_AVG_N * _POLL_INTERVAL_S:.0f} s\n"
            "NM1-Skalierung ist noch Platzhalter (SENSOR_SCALE['torque_nm1'])")
        box.addWidget(title)
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(3)
        self._pressure_rows: list[dict] = []
        for row, (name, ch, strang, scale_key) in enumerate(_PRESSURE_AI):
            desc = QLabel(f"{name}  AI{ch}  {strang}")
            val_lbl = QLabel("–")
            val_lbl.setFont(theme.font(13, QFont.Weight.DemiBold))
            val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            volt_lbl = QLabel("")
            theme.set_tone(volt_lbl, _T_DIM)
            grid.addWidget(desc, row, 0)
            grid.addWidget(val_lbl, row, 1)
            grid.addWidget(volt_lbl, row, 2)
            self._pressure_rows.append({"ch": ch, "scale": scale_key,
                                        "val": val_lbl, "volt": volt_lbl})
        big = theme.font(13, QFont.Weight.DemiBold)
        self._force_calc = QLabel("–")
        self._force_nm1 = QLabel("–")
        self._force_diff = QLabel("")
        theme.set_tone(self._force_diff, _T_DIM)
        base = len(_PRESSURE_AI)
        for row, (text, val, extra) in enumerate((
                ("M rechnerisch (DS1)", self._force_calc, None),
                ("M Sensor NM1 (AI4)", self._force_nm1, self._force_diff))):
            val.setFont(big)
            val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(QLabel(text), base + row, 0)
            grid.addWidget(val, base + row, 1)
            if extra is not None:
                grid.addWidget(extra, base + row, 2)
        self._force_calc_detail = QLabel("")
        theme.set_tone(self._force_calc_detail, _T_DIM)
        grid.addWidget(self._force_calc_detail, base, 2)
        box.addLayout(grid)

        # Ablauf: Grundstellung (unten aus, oben ein) → Sperrbolzen rein → oben aus/ein
        # messen → oben ein → unten entlasten → Sperrbolzen raus → unten aus
        buttons = QHBoxLayout()
        self._cyl_buttons: dict[int, QPushButton] = {}
        self._cyl_tips: dict[int, str] = {}
        for caption, text, ch, variant, icon_name in (
                ("Unten:", "ausfahren", _LO_EXT, "caution", "up"),
                (None, "entlasten", _LO_RET, "secondary", "down"),
                ("   Oben (Messung):", "ausfahren", _UP_EXT, "caution", "up"),
                (None, "einfahren", _UP_RET, "secondary", "down")):
            if caption:
                buttons.addWidget(QLabel(caption))
            btn = theme.button(text, variant, icon_name, size="sm")
            btn.setEnabled(False)
            btn.clicked.connect(lambda _checked, c=ch: self._on_cylinder(c))
            self._cyl_tips[ch] = f"{PINPLAN_DO[ch]} (DO{ch})"
            btn.setToolTip(self._cyl_tips[ch])
            self._cyl_buttons[ch] = btn
            buttons.addWidget(btn)
        buttons.addStretch()
        box.addLayout(buttons)
        self._cyl_state = QLabel("Lage unbekannt")
        theme.set_tone(self._cyl_state, _T_DIM)
        box.addWidget(self._cyl_state)
        self._valves_ok = False
        self._bolt_confirmed = False   # „Sperrbolzen eingeschoben?“ – einmal pro Messzyklus

        self._ds1_hist: list[float] = []
        self._nm1_hist: list[float] = []
        return box

    def _build_outputs(self) -> QVBoxLayout:
        box = QVBoxLayout()
        # AO und Zähler in einem Abschnitt (Fensterhöhe!)
        box.addWidget(_section_title("Analog-Ausgänge AO0–AO1 · Zähler CNT0"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        for ch in range(AO_COUNT):
            pin_lbl = QLabel(PINPLAN_AO.get(ch, "frei"))
            theme.set_tone(pin_lbl, _T_TEXT if ch in PINPLAN_AO else _T_DIM)
            hint = QLabel("nicht rücklesbar")
            theme.set_tone(hint, _T_DIM)
            grid.addWidget(QLabel(f"AO{ch}"), ch, 0)
            grid.addWidget(pin_lbl, ch, 1)
            grid.addWidget(hint, ch, 2)
        self._cnt_labels = []
        for ch in range(CNT_COUNT):
            row = AO_COUNT + ch
            pin_lbl = QLabel(PINPLAN_CNT.get(ch, "RPM1?"))
            pin_lbl.setToolTip("RPM1 liegt laut Pinplan am Zähler-/Trigger-Bereich, Kanal noch offen")
            theme.set_tone(pin_lbl, _T_DIM)
            val = QLabel("–")
            val.setFont(theme.font(11))
            grid.addWidget(QLabel(f"CNT{ch}"), row, 0)
            grid.addWidget(pin_lbl, row, 1)
            grid.addWidget(val, row, 2)
            self._cnt_labels.append(val)
        box.addLayout(grid)

        box.addLayout(self._build_motor())
        box.addLayout(self._build_leak())
        box.addStretch()
        return box

    def _build_motor(self) -> QVBoxLayout:
        box = QVBoxLayout()
        title = _section_title("Motor-Test  (AO0 + DO0)")
        title.setToolTip(f"AO0 Sollwert + DO0 Motor on\nSkalierung Annahme: "
                         f"0–{MOTOR_AO_MAX_V:.0f} V ≙ 0–{MOTOR_AO_MAX_HZ:.0f} Hz")
        box.addWidget(title)

        row = QHBoxLayout()
        row.addWidget(QLabel("Sollwert:"))
        self._motor_spin = QDoubleSpinBox()
        self._motor_spin.setRange(0.5, MOTOR_TEST_MAX_V)
        self._motor_spin.setSingleStep(0.5)
        self._motor_spin.setDecimals(1)
        self._motor_spin.setSuffix(" V")
        self._motor_spin.setValue(MOTOR_TEST_DEFAULT_V)
        self._motor_spin.setProperty("size", "sm")
        self._motor_spin.valueChanged.connect(self._update_motor_estimate)
        row.addWidget(self._motor_spin)
        self._motor_estimate = QLabel()
        theme.set_tone(self._motor_estimate, _T_DIM)
        row.addWidget(self._motor_estimate)
        # Gemessene Drehzahl aus RPM1 (CNT0) direkt neben dem Soll-Schätzwert
        self._rpm1_label = QLabel("· RPM1: –")
        self._rpm1_label.setFont(theme.font(11))
        self._rpm1_label.setToolTip(f"RPM1 gemessen: CNT0-Frequenz [Hz] × {_settings.RPM1_FACTOR:g}"
                                    " (Einstellungen → RPM1: Faktor)")
        row.addWidget(self._rpm1_label)
        row.addStretch()
        box.addLayout(row)
        self._update_motor_estimate()

        buttons = QHBoxLayout()
        self._motor_start_btn = theme.button("Motor starten", "primary", "play")
        self._motor_start_btn.clicked.connect(self._on_motor_start)
        self._motor_stop_btn = theme.button("Motor stoppen", "danger", "square")
        self._motor_stop_btn.clicked.connect(self._on_motor_stop)
        buttons.addWidget(self._motor_start_btn)
        buttons.addWidget(self._motor_stop_btn)
        buttons.addStretch()
        box.addLayout(buttons)

        self._release_label = QLabel("Startfreigabe: –")
        theme.set_tone(self._release_label, _T_DIM)
        box.addWidget(self._release_label)

        self._motor_status = QLabel("Motor aus")
        theme.set_tone(self._motor_status, _T_DIM)
        self._motor_status.setWordWrap(True)
        box.addWidget(self._motor_status)

        self._motor_start_btn.setEnabled(False)
        self._motor_stop_btn.setEnabled(False)
        return box

    def _update_motor_estimate(self):
        hz = _volt_to_hz(self._motor_spin.value())
        self._motor_estimate.setText(
            f"≈ {hz:.1f} Hz ≈ {hz / 50.0 * MOTOR_NOMINAL_RPM_AT_50HZ:.0f} RPM")
        self._motor_estimate.setToolTip(
            f"Annahme: 0–{MOTOR_AO_MAX_V:.0f} V ≙ 0–{MOTOR_AO_MAX_HZ:.0f} Hz "
            "(config/settings.py → MOTOR_AO_MAX_V / MOTOR_AO_MAX_HZ)")

    def _on_motor_start(self):
        voltage = self._motor_spin.value()
        hz = _volt_to_hz(voltage)
        answer = QMessageBox.warning(
            self, "Motor starten?",
            f"Motor wird mit AO0 = {voltage:.1f} V gestartet\n"
            f"(≈ {hz:.1f} Hz ≈ {hz / 50.0 * MOTOR_NOMINAL_RPM_AT_50HZ:.0f} RPM, "
            "Skalierung ist eine Annahme).\n\n"
            "• Prüfstand frei, niemand an drehenden Teilen?\n"
            "• Schutzabdeckungen geschlossen?\n"
            "• Sperrbolzen NICHT eingeschoben?\n\n"
            "Stopp jederzeit über „Motor stoppen“, Not-Aus oder Schließen des Fensters.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._motor_start_btn.setEnabled(False)
        self._motor_status.setText("Starte …")
        self._worker.request_motor_start(voltage)

    def _on_motor_stop(self):
        self._worker.request_motor_stop()

    def _on_valve_toggle(self, channel: int):
        # Umschalten anhand des zurückgelesenen Zustands; unbekannt → einschalten
        on = not self._do_state[channel]
        if channel in _CYL_VALVE_CHANNELS:
            if on and not self._confirm_cylinders():
                return
            self._worker.request_valve(channel, on, sequence=False)   # manuell, frei
        else:
            self._worker.request_valve(channel, on)

    def _on_cylinder(self, channel: int):
        """Eine Zylinderbewegung (Spule an, Gegenspule schaltet set_valve ab). Reihenfolge
        prüft _cylinder_violation im Backend; hier nur die Abfragen zum Sperrbolzen."""
        if not self._confirm_cylinders():
            return
        do = self._do_state
        if channel == _UP_EXT and not self._bolt_confirmed:
            if not self._ask("Sperrbolzen eingeschoben?",
                             "Oberen Zylinder gegen das Getriebe fahren.\n\n"
                             "Ist der Sperrbolzen eingeschoben und das Getriebe blockiert?"):
                return
            self._bolt_confirmed = True
        elif channel == _LO_EXT and do[_LO_RET] == 1:
            if not self._ask("Sperrbolzen gezogen?",
                             "Unteren Zylinder wieder ausfahren (zurück in die Grundstellung).\n\n"
                             "Ist der Sperrbolzen gezogen?"):
                return
        elif channel == _LO_RET:
            self._bolt_confirmed = False   # Entlasten beendet den Messzyklus
        self._worker.request_valve(channel, True)

    def _ask(self, title: str, text: str) -> bool:
        return QMessageBox.question(
            self, title, text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        ) == QMessageBox.StandardButton.Yes

    def _confirm_cylinders(self) -> bool:
        """Einmalige Sicherheitsabfrage pro Sitzung vor der ersten Zylinderbewegung."""
        if not self._cyl_confirmed:
            answer = QMessageBox.warning(
                self, "Zylinder-Ventil schalten?",
                "DO1–DO4 steuern die Zylinder am Drehmomenthebel "
                "(DO1/DO2 oben aus/ein, DO3/DO4 unten aus/ein).\n\n"
                "• Motor steht?\n"
                "• Druckregler oberer Strang auf passenden Druck gestellt?\n\n"
                "Ablauf: Grundstellung (unten aus, oben ein) → Sperrbolzen rein → oben "
                "aus/ein messen → oben ein → unten entlasten → Sperrbolzen raus → unten aus.\n\n"
                "Diese Abfrage kommt nur einmal pro Sitzung.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
            self._cyl_confirmed = True
        return True

    def _on_leak_start(self):
        fill_s, hold_s, vent_s = (s.value() for s in self._leak_spins)
        answer = QMessageBox.question(
            self, "Leckageprüfung starten?",
            f"Befüllen {fill_s:g} s (DO5+DO6) → Halten {hold_s:g} s (DO5=0, DO6={LEAK_HOLD_DO6}) → "
            f"Entlüften {vent_s:g} s (DO5=1, DO6=0).\n\n"
            "Getriebe angeschlossen und Pneumatik bereit?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._leak_start_btn.setEnabled(False)
        self._leak_result.setText("DS2 Start – · Ende – · Abfall –")
        theme.set_tone(self._leak_result, _T_DIM)
        self._worker.request_leak_start(fill_s, hold_s, vent_s)

    def _on_leak_abort(self):
        if self._leak_running:
            self._worker.request_leak_abort()
        else:
            self._worker.request_vent(self._leak_spins[2].value())

    def _set_leak_running(self, running: bool):
        self._leak_running = running
        self._leak_start_btn.setEnabled(not running)
        for spin in self._leak_spins:
            spin.setEnabled(not running)
        for ch in _LEAK_VALVE_CHANNELS:
            self._valve_buttons[ch].setEnabled(not running)

    @pyqtSlot(dict)
    def _on_leak_state(self, st: dict):
        if "rejected" in st:
            self._leak_start_btn.setEnabled(not self._leak_running)
            self._leak_phase.setText(st["rejected"])
            theme.set_tone(self._leak_phase, _T_CRIT)
            return
        self._set_leak_running(st["running"])
        name = phase_name(st["phase"])
        if st["running"]:
            text = f"{name} – noch {st['remaining_s']:.1f} s"
            color = _T_WARN if st["phase"].startswith("vent") else _T_OK
            if st["aborted"] and st["phase"].startswith("vent"):
                text += "  (Abbruch)"
        elif st["aborted"]:
            text, color = "Entlüftet – Ablauf abgebrochen, keine Bewertung", _T_DIM
        else:
            text, color = "Fertig – Ventile 0/0", _T_DIM
        if st["errors"]:
            text += "  ·  FEHLER: " + "; ".join(st["errors"])
            color = _T_CRIT
        if st["message"]:
            text += f"  ·  {st['message']}"
        self._leak_phase.setText(text)
        theme.set_tone(self._leak_phase, color)

        def fmt(p: float) -> str:
            return "–" if math.isnan(p) else f"{p:.3f} bar"

        end = st["p_end"] if not math.isnan(st["p_end"]) else (
            st["p_now"] if st["phase"] == "hold" else math.nan)
        drop = st["drop"]
        text = f"DS2 Start {fmt(st['p_start'])} · Ende {fmt(end)} · Abfall {fmt(drop)}"
        color = _T_DIM
        if not math.isnan(drop):
            color = {"ok": _T_OK, "warn": _T_WARN, "crit": _T_CRIT}[rate_drop(drop)]
            if not st["running"] and not st["aborted"]:
                text += "  → " + {"ok": "OK", "warn": "WARNUNG", "crit": "KRITISCH"}[rate_drop(drop)]
        self._leak_result.setText(text)
        theme.set_tone(self._leak_result, color)

    @pyqtSlot(bool, str)
    def _on_valve_message(self, is_error: bool, message: str):
        self._valve_status.setText(message)
        theme.set_tone(self._valve_status, _T_CRIT if is_error else _T_DIM)

    def _set_valves_enabled(self, enabled: bool):
        for btn in self._valve_buttons.values():
            btn.setEnabled(enabled)
        self._leak_start_btn.setEnabled(enabled)
        self._leak_abort_btn.setEnabled(enabled)
        self._valves_ok = enabled
        self._update_cyl_state(self._do_state)

    @pyqtSlot(bool, str)
    def _on_motor_state(self, running: bool, message: str):
        self._motor_status.setText(message)
        # Regulärer Stopp grau, jeder andere Stopp/Fehler rot
        if running:
            color = _T_OK
        elif message in ("Motor gestoppt.", "Motor gestoppt (Monitor geschlossen)."):
            color = _T_DIM
        else:
            color = _T_CRIT
        theme.set_tone(self._motor_status, color)
        self._motor_start_btn.setEnabled(not running)
        self._motor_spin.setEnabled(not running)
        # Stopp-Button bleibt immer aktiv – Stoppen ist nie falsch
        self._motor_stop_btn.setEnabled(True)

    def showEvent(self, event):
        super().showEvent(event)
        # Erst beim Anzeigen sind Schriften/Stylesheets angewendet und die Größen stimmen
        if not self._fitted:
            self._fitted = True
            self._fit_to_screen()

    def _fit_to_screen(self):
        """Wunschgröße des Inhalts, aber nie größer als der freie Bildschirmbereich."""
        avail = self.screen().availableGeometry()
        scroll = self.findChild(QScrollArea)
        content = scroll.widget().sizeHint()
        chrome_h = self.height() - scroll.viewport().height()   # Titel, Banner, Fußzeile
        # Live-Werte sind breiter als die Platzhalter beim Aufbau → Mindestbreite 1480 px
        width = min(max(content.width() + 60, 1480), avail.width() - 20)
        height = min(content.height() + chrome_h + 10, avail.height() - 40)
        self.resize(width, height)
        self.move(avail.x() + (avail.width() - width) // 2,
                  avail.y() + (avail.height() - height) // 2)

    def _set_banner(self, text: str, tone: str):
        """Verbindungsstatus in der Kopfzeile – wie „● Sicherheit OK“ im Prüfprogramm."""
        self._banner_text = text
        self._banner.setText(f"●  {text}")
        theme.set_tone(self._banner, tone)

    # ── Signale vom Worker ────────────────────────────────────────────────────

    @pyqtSlot(str)
    def _on_connection_failed(self, error: str):
        self._set_banner("KEINE VERBINDUNG ZUR KARTE – keine Messwerte", _T_CRIT)
        self._error_label.setText(error)
        self._motor_status.setText("Motor-Test nicht möglich: keine Verbindung zur Karte")
        self._release_label.setText("Startfreigabe: unbekannt")
        theme.set_tone(self._release_label, _T_CRIT)
        self._valve_status.setText("Ventile nicht schaltbar: keine Verbindung")

    @pyqtSlot(bool, bool, bool, str)
    def _on_connected(self, real: bool, motor_ok: bool, valves_ok: bool, error: str):
        self._motor_start_btn.setEnabled(motor_ok)
        self._motor_stop_btn.setEnabled(motor_ok)
        self._set_valves_enabled(valves_ok)
        if not valves_ok:
            self._on_valve_message(True, "Ventile nicht schaltbar: DO nicht verfügbar")
        if real and not motor_ok:
            self._motor_status.setText("Motor-Test nicht möglich: AO/DO/DI nicht verfügbar")
        elif not real:
            self._motor_status.setText("Motor-Test nur mit echter Hardware")
        if real:
            self._set_banner(f"ECHTE HARDWARE – {DEVICE_DESCRIPTION}", _T_OK)
        else:
            self._set_banner("SIMULATION – DAQNavi-SDK nicht installiert", _T_WARN)
            self._error_label.setText(f"Verbindungsfehler: {error}")

    @pyqtSlot(dict)
    def _on_data(self, snap: dict):
        if snap.get("error"):
            self._error_label.setText(snap["error"])
        elif self._banner_text.startswith("ECHTE"):
            self._error_label.setText("")

        for row, voltage in zip(self._ai_rows, snap.get("ai", [])):
            if math.isnan(voltage):
                for key in ("volt", "val"):
                    row[key].setText("ERR")
                    theme.set_tone(row[key], _T_DIM)
                row["bar"].setValue(0)
                continue

            row["volt"].setText(f"{voltage:+7.3f} V")
            row["bar"].setValue(_bar(voltage))
            sid = row["sid"]
            if sid and sid in SENSOR_SCALE:
                value = _scale(voltage, *SENSOR_SCALE[sid])
                color = _status_color(sid, value)
                row["val"].setText(f"{value:8.2f} {row['unit']}")
                theme.set_tone(row["val"], color)
            else:
                color = _T_TEXT
            theme.set_tone(row["volt"], color)
            theme.set_tone(row["bar"], color or _T_DIM)

        ai = snap.get("ai", [])
        for row in self._pressure_rows:
            voltage = ai[row["ch"]] if row["ch"] < len(ai) else math.nan
            if math.isnan(voltage):
                row["val"].setText("ERR")
                theme.set_tone(row["val"], _T_DIM)
                row["volt"].setText("")
                continue
            value = _scale(voltage, *SENSOR_SCALE[row["scale"]])
            row["val"].setText(f"{value:7.3f} bar")
            # Grenzwerte in SENSOR_MAP gelten nur für den Leckage-Druck (DS2)
            color = _status_color("pressure", value) if row["scale"] == "pressure" else _T_TEXT
            theme.set_tone(row["val"], color)
            row["volt"].setText(f"({voltage:+.3f} V)")

        self._update_force(ai)

        di = snap.get("di", [])
        self._update_leds(self._di_leds, di, MOTOR_START_REQUIRED_DI)
        do = snap.get("do", [])
        self._update_leds(self._do_leds, do)
        if do:
            self._do_state = list(do)
            for ch, btn in self._valve_buttons.items():
                btn.setText("ausschalten" if do[ch] else "einschalten")
            self._update_cyl_state(do)
        if di:
            violations = _start_violations(di)
            if violations:
                # Einzeilig halten (Fensterhöhe!), Details im Tooltip + rote DI-Einträge
                channels = ", ".join(v.split()[0] for v in violations)
                self._release_label.setText(f"Startfreigabe FEHLT: {channels}")
                self._release_label.setToolTip("\n".join(violations))
                theme.set_tone(self._release_label, _T_CRIT)
            else:
                self._release_label.setText("Startfreigabe OK (Induktiv A–E + Not-Aus)")
                self._release_label.setToolTip("")
                theme.set_tone(self._release_label, _T_OK)

        for lbl, freq in zip(self._cnt_labels, snap.get("cnt", [])):
            if math.isnan(freq):
                lbl.setText("ERR")
                theme.set_tone(lbl, _T_DIM)
            else:
                lbl.setText(f"{freq:10.1f} Hz")
                theme.set_tone(lbl, _T_OK if freq > 0 else _T_TEXT)
        cnt = snap.get("cnt", [])
        freq = cnt[0] if cnt else math.nan
        if math.isnan(freq):
            self._rpm1_label.setText("· RPM1: –")
            theme.set_tone(self._rpm1_label, _T_DIM)
        else:
            self._rpm1_label.setText(f"· RPM1 gemessen: {freq * _settings.RPM1_FACTOR:.0f} RPM")
            theme.set_tone(self._rpm1_label, _T_OK if freq > 0 else _T_TEXT)

    def _update_force(self, ai: list):
        """Drehmoment rechnerisch aus DS1 vs. NM1, beide gleitend gemittelt."""
        for hist, ch in ((self._ds1_hist, _DS1_CH), (self._nm1_hist, _NM1_CH)):
            voltage = ai[ch] if ch < len(ai) else math.nan
            if math.isnan(voltage):
                hist.clear()
            else:
                hist.append(voltage)
                del hist[:-_FORCE_AVG_N]
        if not self._ds1_hist or not self._nm1_hist:
            for lbl in (self._force_calc, self._force_nm1, self._force_diff):
                lbl.setText("ERR")
            return
        u_ds1 = sum(self._ds1_hist) / len(self._ds1_hist)
        u_nm1 = sum(self._nm1_hist) / len(self._nm1_hist)
        p = _scale(u_ds1, *SENSOR_SCALE["pressure_cyl"])
        m_calc = p * _NM_PER_BAR
        m_nm1 = _scale(u_nm1, *SENSOR_SCALE["torque_nm1"])
        self._force_calc.setText(f"{m_calc:7.1f} Nm")
        self._force_calc_detail.setText(f"(F {m_calc / LEVER_ARM_MM * 1000:.0f} N)")
        self._force_nm1.setText(f"{m_nm1:7.1f} Nm")
        self._force_diff.setText(f"({u_nm1:+.3f} V · Δ {m_nm1 - m_calc:+.1f} Nm)")

    def _update_cyl_state(self, do: list):
        """Lage laut letztem Befehl (DO-Rücklesen; bistabil: 0/0 = Lage unbekannt) plus
        nächster Schritt; Knöpfe, die _cylinder_violation sperrt, werden ausgegraut."""
        upper_in, lower_out = _upper_retracted(do), _lower_extended(do)
        if any(do[ch] is None for ch in _CYL_VALVE_CHANNELS):
            text, color = "DO nicht lesbar – Lage unbekannt", _T_CRIT
        elif upper_in and lower_out:
            text, color = ("Grundstellung – Motorstart möglich · Messen: Sperrbolzen rein, "
                           "dann oben ausfahren"), _T_OK
        elif do[_UP_EXT] == 1:
            text, color = "Messung – oben ausgefahren · danach oben einfahren", _T_WARN
        elif upper_in and do[_LO_RET] == 1:
            text, color = "Entlastet – Sperrbolzen ziehen, dann unten ausfahren", _T_WARN
        else:
            text, color = "Lage unbekannt – oben einfahren, dann unten ausfahren", _T_DIM
        self._cyl_state.setText(text)
        theme.set_tone(self._cyl_state, color)

        for ch, btn in self._cyl_buttons.items():
            reason = _cylinder_violation(ch, True, do) if None not in do[:DO_COUNT] else "DO nicht lesbar"
            btn.setEnabled(self._valves_ok and not reason)
            btn.setToolTip(self._cyl_tips[ch] + (f"\nGesperrt: {reason}" if reason else ""))

    @staticmethod
    def _update_leds(leds: list[QLabel], bits: list, required: dict[int, int] | None = None):
        """Kanäle mit Soll-Zustand: grün = passt, rot = passt nicht (Start gesperrt)."""
        required = required or {}
        for ch, (led, bit) in enumerate(zip(leds, bits)):
            if bit is None:
                led.setText("ERR")
                theme.set_tone(led, _T_DIM)
                continue
            led.setText("● 1" if bit else "○ 0")
            if ch in required:
                color = _T_OK if bit == required[ch] else _T_CRIT
            else:
                color = _T_OK if bit else _T_OFF
            theme.set_tone(led, color)

    def closeEvent(self, event):
        if self._worker is not None:
            self._worker.stop()
            self._worker = None
        super().closeEvent(event)


# ── Standalone ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = QApplication(sys.argv)
    theme.apply(app)
    from ui.settings_dialog import apply_grenzwerte_to_settings
    apply_grenzwerte_to_settings()   # gespeicherten RPM1-Faktor auch im Standalone-Monitor nutzen
    win = DaqMonitorDialog()
    win.show()
    sys.exit(app.exec())
