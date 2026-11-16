"""
Real Hardware Interface – Getriebeprüfstand

Ein Gerät: Advantech USB-4711A (DAQNavi SDK)
  AI  Sensoren
  DI  Sicherheit (Induktiv A–E, Not-Aus-Kreis/Schrank), Sperrbolzen (DI3)
  DO  DO0 Motor on (Frequenzumrichter), DO1–DO6 Pneumatikventile
  AO  AO0 Drehzahl-Sollwert Frequenzumrichter Hitachi WJ-C1
Der FU wird analog über AO0/DO0 angesteuert – die frühere Modbus-Anbindung
(hardware/motor_controller.py) wird nicht mehr benutzt (Pinplan, TODO C3).

Kanalzuordnung Sensoren:
  AI0 → T1 Temperatur      (PT1000 via TxRail, Rohspannung → °C)
  AI1 → T2 Temperatur      (PT1000 via TxRail, Rohspannung → °C)
  AI2 → DS1 Zylinderdruck  (oberer Pneumatik-Strang, Kraftprüfung)
  AI3 → DS2 Leckage-Druck  (Rohspannung → bar, unterer Strang V4 → V3 → Getriebe)
  AI4 → NM1 Drehmoment     (Rohspannung → Nm, Skalierung noch Platzhalter)
  AI7 → Vibrationssensor   (Rohspannung → mm/s)
  Drehzahl RPM1: kein AI-Kanal, Zähler CNT0 als Frequenzmessung, RPM = Hz × RPM1_FACTOR
  (gleiche Umrechnung wie im DAQ-Monitor)
  "torque" = Moment am Hebel, je nach TORQUE_SOURCE aus DS1 berechnet oder NM1

Voraussetzungen (Windows):
  1. DAQNavi SDK von Advantech installiert
  2. pip install advantech-daq
"""

import threading
from typing import Optional

import config.settings as _settings
from config.settings import (
    MOTOR_AO_MAX_HZ, MOTOR_AO_MAX_V, MOTOR_NOMINAL_RPM_AT_50HZ, MOTOR_ON_DO_CHANNEL,
    MOTOR_SPEED_AO_CHANNEL, VALVE_CHANNEL_MAP,
)
from hardware.base import SensorInterface
from hardware.cylinder_sequence import at_home, home_deviations, torque_from_pressure
from hardware.rpm_filter import RpmSpikeFilter
from hardware.safety import di_violations

# Kanalzuordnung: sensor_id → AI-Kanal-Index
# T1/T2/Vibration laut Pinplan, am Prüfstand bestätigt (Nutzer, 28.09.2026).
SENSOR_CHANNEL_MAP: dict[str, int] = {
    "temperature":  0,   # T1 – PT1000 über TxRail-USB (0–10 V)
    "temperature2": 1,   # T2 – PT1000 über TxRail-USB (0–10 V)
    "pressure_cyl": 2,   # DS1 – Zylinderstrang (Angabe Nutzer, 25.09.2026)
    "pressure":     3,   # DS2 – Getriebe / Leckage-Prüfung (Angabe Nutzer, 25.09.2026)
    "torque_nm1":   4,   # NM1 – Drehmomentsensor im Getriebe (Angabe Nutzer, 30.09.2026)
    "vibration":    7,
    # "speed" hat keinen AI-Kanal: RPM1 über Zähler CNT0 (siehe RealHardware._read_rpm1)
    # "torque" ist abgeleitet (siehe RealHardware.read)
}

# Lineare Skalierung: Rohspannung [V] → physikalische Einheit
# Format: (v_min, v_max, unit_min, unit_max)
SENSOR_SCALE: dict[str, tuple[float, float, float, float]] = {
    "vibration":   (2.00, 10.00,  0.0,   25.0),   # V → mm/s  (AV003, 4-20mA × 500Ω)
    # TxRail-Bereich 0–100 °C (Angabe Nutzer, 28.09.2026) – passt zur Messung
    # 2,3–2,4 V bei Raumtemperatur ≈ 23–24 °C
    "temperature":  (0.0, 10.0,    0.0,  100.0),  # V → °C (T1, TxRail-USB PT1000)
    "temperature2": (0.0, 10.0,    0.0,  100.0),  # V → °C (T2, TxRail-USB PT1000)
    # Drucksensor 995410 – Abgleich DS2 am Prüfstand (28.09.2026, Referenz = Sensor-Display):
    #   0,984 V ≙ 1,04 · 1,070 V ≙ 1,13 · 1,085 V ≙ 1,14 · 1,254 V ≙ 1,31 · 1,455 V ≙ 1,51 ·
    #   1,477 V ≙ 1,53 bar → Ausgleichsgerade p = 0,9933·U + 0,0640 (Rest ≤ 0,003 bar),
    #   also ≈ 0–10 V ≙ 0–10 bar.
    # Drucklos gibt der Sensor ≈ 0,136 V aus statt der rechnerischen −0,06 V (Ausgang kann nicht
    # negativ) → Anzeige dann ≈ 0,2 bar. Wo die Kennlinie unten abknickt, ist noch offen
    # (Punkte < 1 bar fehlen).
    "pressure":    (-0.0645, 10.0032, 0.0, 10.0),  # V → bar (DS2)
    # DS1 (AI2, Zylinderstrang) – eigener Abgleich am Prüfstand (30.09.2026, Referenz = Display):
    #   0,6915 V ≙ 0,72 · 0,9868 V ≙ 1,02 · 1,9654 V ≙ 1,99 · 2,9980 V ≙ 3,03 bar
    #   → p = 1,0001·U + 0,0294 (Rest ≤ 0,005 bar).
    "pressure_cyl": (-0.0294, 9.9696, 0.0, 10.0),  # V → bar (DS1)
    # NM1: Ausgangssignal/Messbereich unbekannt. Nutzer 19.10.2026: Anzeige 35 Nm soll ≈ 450 Nm
    # sein → bisherige Steigung (50 Nm/V) × 450/35 ≈ 642,86 Nm/V, Nullpunkt 0 V ≙ 0 Nm
    # angenommen (Ein-Punkt-Abgleich). Abgleich über mehrere Punkte gegen
    # Zylinderkraft (M ≈ 83,3 Nm/bar · p(DS1), ⌀80 mm, r = 165,78 mm) steht noch aus.
    "torque_nm1":  (0.0, 10.0,    0.0, 500.0 * 450.0 / 35.0),   # V → Nm (≈ 6428,6 Nm bei 10 V)
    "speed":       (0.0, 10.0,    0.0, 3000.0),   # V → RPM (ungenutzt, kein AI-Kanal)
}


def _scale(voltage: float, v_min: float, v_max: float,
           u_min: float, u_max: float) -> float:
    """Lineare Interpolation von Spannung auf physikalische Einheit."""
    if v_max == v_min:
        return u_min
    ratio = (voltage - v_min) / (v_max - v_min)
    return u_min + ratio * (u_max - u_min)


def rpm_to_ao_volt(rpm: float) -> float:
    """Drehzahl → AO0-Sollwert. ANNAHME 0–10 V ≙ 0–50 Hz, 50 Hz ≙ 1500 rpm (TODO C3)."""
    hz = rpm / MOTOR_NOMINAL_RPM_AT_50HZ * 50.0
    return max(0.0, min(MOTOR_AO_MAX_V, hz / MOTOR_AO_MAX_HZ * MOTOR_AO_MAX_V))


_VALVE_CHANNELS = set(VALVE_CHANNEL_MAP.values())


class RealHardware(SensorInterface):
    """Advantech USB-4711A. Alle Kartenzugriffe laufen über eine Sperre, weil die
    Sensor-Threads des Prüfablaufs parallel lesen."""

    DEVICE_DESCRIPTION = "USB-4711A,BID#0"

    def __init__(self):
        self._connected = False
        self._error = ""
        self._lock = threading.RLock()
        self._ai = None
        self._di = None
        self._do = None
        self._ao = None
        self._fm = None
        self._motor_on = False
        self._rpm_filter = RpmSpikeFilter()   # Ausreißer von CNT0 (RPM1) verwerfen

    # ── Verbindung ────────────────────────────────────────────────────────────

    def connect(self) -> bool:
        self.disconnect()
        try:
            from Automation.BDaq.InstantAiCtrl import InstantAiCtrl
            from Automation.BDaq.InstantAoCtrl import InstantAoCtrl
            from Automation.BDaq.InstantDiCtrl import InstantDiCtrl
            from Automation.BDaq.InstantDoCtrl import InstantDoCtrl
        except ImportError as exc:
            self._error = f"DAQNavi-SDK nicht installiert ({exc})"
            return False
        try:
            with self._lock:
                self._ai = InstantAiCtrl(self.DEVICE_DESCRIPTION)
                self._ai.loadProfile = ""
                self._configure_ai_ranges()
                self._di = InstantDiCtrl(self.DEVICE_DESCRIPTION)
                self._do = InstantDoCtrl(self.DEVICE_DESCRIPTION)
                self._ao = InstantAoCtrl(self.DEVICE_DESCRIPTION)
        except Exception as exc:
            msg = str(exc)
            if "0xE0000010" in msg:
                msg = ("Karte wird von einem anderen Programm benutzt "
                       "(z. B. DAQ-Monitor oder Advantech Navigator offen)")
            self._error = f"USB-4711A nicht verfügbar: {msg}"
            self.disconnect()
            return False
        self._open_freq_meter()
        self._connected = True
        self._error = ""
        print(f"[RealHardware] USB-4711A verbunden ({self.DEVICE_DESCRIPTION})")
        return True

    def _configure_ai_ranges(self) -> None:
        """Schreibt den Messbereich ±10 V aktiv auf alle AI-Kanäle.

        Eine neue/zurückgesetzte Karte meldet zwar ±10 V, hat den Bereich intern aber
        nicht gesetzt → readData() liefert nur 0.0 mit WarningParamOutOfRange. Ein
        Setzen auf den bereits gemeldeten Wert wird vom Treiber ignoriert, daher erst
        kurz auf ±5 V und dann auf ±10 V umschalten."""
        from Automation.BDaq import ValueRange

        for ch in self._ai.channels:
            ch.valueRange = ValueRange.V_Neg5To5
            ch.valueRange = ValueRange.V_Neg10To10

    def disconnect(self) -> None:
        with self._lock:
            if self._connected:
                self.stop_motor()
            for ctrl in (self._ai, self._di, self._do, self._ao, self._fm):
                if ctrl is not None:
                    try:
                        ctrl.dispose()
                    except Exception:
                        pass
            self._ai = self._di = self._do = self._ao = self._fm = None
            self._connected = False

    def _open_freq_meter(self) -> None:
        """CNT0 als Frequenzmessung für RPM1 (wie DAQ-Monitor). Fehlt sie, läuft die
        Prüfung trotzdem – RPM1 liefert dann keine Werte."""
        try:
            from Automation.BDaq.FreqMeterCtrl import FreqMeterCtrl
            with self._lock:
                self._fm = FreqMeterCtrl(self.DEVICE_DESCRIPTION)
                self._fm.channelStart = 0
                self._fm.channelCount = 1
                self._fm.enabled = True
        except Exception as exc:
            print(f"[RealHardware] Frequenzmessung CNT0 (RPM1) nicht verfügbar: {exc}")
            self._fm = None

    def _read_rpm1(self) -> Optional[float]:
        if self._fm is None:
            return None
        try:
            from Automation.BDaq.BDaqApi import BioFailed
            with self._lock:
                ret, data = self._fm.read(1)
            if BioFailed(ret) or not data:
                return None
            return self._rpm_filter.filter(round(data[0] * _settings.RPM1_FACTOR, 1))
        except Exception as exc:
            print(f"[RealHardware] Lesefehler (CNT0/RPM1): {exc}")
            return None

    @property
    def rpm1_rejected(self) -> int:
        """Anzahl verworfener RPM1-Ausreißer seit Programmstart."""
        return self._rpm_filter.rejected

    @property
    def connect_error(self) -> str:
        return self._error

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ── Analog-Eingänge ───────────────────────────────────────────────────────

    def _read_channel(self, channel: int) -> Optional[float]:
        """Liest einen einzelnen AI-Kanal. Gibt Rohspannung zurück oder None."""
        try:
            from Automation.BDaq import ErrorCode
            from Automation.BDaq.BDaqApi import BioFailed
            with self._lock:
                ret, data_list = self._ai.readData(channel, 1)
            # Warnung wird von BioFailed() nicht erkannt, Werte sind dann aber alle 0.0
            if BioFailed(ret) or ret == ErrorCode.WarningParamOutOfRange or not data_list:
                if ret == ErrorCode.WarningParamOutOfRange:
                    print(f"[RealHardware] AI{channel}: Messbereich ungültig (WarningParamOutOfRange)")
                return None
            return data_list[0]
        except Exception as exc:
            print(f"[RealHardware] Lesefehler (AI{channel}): {exc}")
            return None

    def read(self, sensor_id: str) -> Optional[float]:
        if not self._connected or self._ai is None:
            return None
        if sensor_id == "torque":
            if _settings.TORQUE_SOURCE == "nm1":
                return self.read("torque_nm1")
            p = self.read("pressure_cyl")
            return None if p is None else round(torque_from_pressure(p), 1)
        if sensor_id == "speed":
            return self._read_rpm1()
        if sensor_id == "torque_nm1_v":   # Rohspannung NM1, unskaliert
            voltage = self._read_channel(SENSOR_CHANNEL_MAP["torque_nm1"])
            return None if voltage is None else round(voltage, 4)

        channel = SENSOR_CHANNEL_MAP.get(sensor_id)
        if channel is None:
            return None
        voltage = self._read_channel(channel)
        if voltage is None:
            return None
        scale = SENSOR_SCALE.get(sensor_id)
        if scale is None:
            return round(voltage, 4)
        return round(_scale(voltage, *scale), 3)

    # ── Digital-Ein-/Ausgänge ─────────────────────────────────────────────────

    def _read_port(self, ctrl) -> Optional[list[int]]:
        if not self._connected or ctrl is None:
            return None
        try:
            from Automation.BDaq.BDaqApi import BioFailed
            with self._lock:
                ret, data = ctrl.readAny(0, 1)
            if BioFailed(ret) or not data:
                return None
            return [(data[0] >> bit) & 1 for bit in range(8)]
        except Exception as exc:
            print(f"[RealHardware] Port lesen fehlgeschlagen: {exc}")
            return None

    def read_di(self) -> Optional[list[int]]:
        return self._read_port(self._di)

    def read_do(self) -> Optional[list[int]]:
        return self._read_port(self._do)

    def write_do(self, channel: int, bit: int) -> str:
        if channel not in _VALVE_CHANNELS:
            return f"DO{channel} ist kein Ventil – verweigert"
        if not self._connected or self._do is None:
            return "DO nicht verfügbar"
        try:
            from Automation.BDaq.BDaqApi import BioFailed
            with self._lock:
                ret = self._do.writeBit(0, channel, 1 if bit else 0)
            if BioFailed(ret):
                return f"DO{channel} schreiben fehlgeschlagen: {ret.name}"
            return ""
        except Exception as exc:
            return f"DO{channel}: {exc}"

    # ── Motor (AO0 Sollwert + DO0 Motor on) ───────────────────────────────────

    def start_motor(self, rpm: float) -> str:
        """Erst Sollwert (AO0), dann Motor on (DO0) – wie im DAQ-Monitor erprobt.
        Zusätzliche Sperre hier: Sicherheit + Sperrbolzen gezogen + Zylinder in
        Grundstellung (Aufrufer prüft das ebenfalls)."""
        from Automation.BDaq import ValueRange
        from Automation.BDaq.BDaqApi import BioFailed

        if not self._connected or self._ao is None or self._do is None:
            return "Motor nicht ansteuerbar: AO/DO nicht verfügbar"
        violations = di_violations(self.read_di(), bolt="out")
        if violations:
            return "Motorstart verweigert: " + ", ".join(violations)
        do = self.read_do()
        if do is None or not at_home(do):
            detail = "DO nicht lesbar" if do is None else ", ".join(home_deviations(do))
            return f"Motorstart verweigert: Zylinder nicht in Grundstellung ({detail})"
        voltage = rpm_to_ao_volt(rpm)
        try:
            with self._lock:
                # Karte steht ab Werk auf 0–5 V; Sollwert-Skalierung geht von 0–10 V aus
                self._ao.channels[MOTOR_SPEED_AO_CHANNEL].valueRange = ValueRange.V_0To10
                ret = self._ao.writeAny(MOTOR_SPEED_AO_CHANNEL, 1, None, [voltage])
                if BioFailed(ret):
                    return f"AO{MOTOR_SPEED_AO_CHANNEL} schreiben fehlgeschlagen: {ret.name}"
                ret = self._do.writeBit(0, MOTOR_ON_DO_CHANNEL, 1)
                if BioFailed(ret):
                    self.stop_motor()
                    return f"DO{MOTOR_ON_DO_CHANNEL} schreiben fehlgeschlagen: {ret.name}"
        except Exception as exc:
            self.stop_motor()
            return f"Motorstart fehlgeschlagen: {exc}"
        self._motor_on = True
        self._rpm_filter.reset(expected=rpm)
        return ""

    def stop_motor(self) -> None:
        """Erst Motor on weg (DO0), dann Sollwert auf 0 V. Fehler werden nur geloggt,
        damit der zweite Schritt auch bei Fehler im ersten versucht wird."""
        with self._lock:
            if self._do is not None:
                try:
                    self._do.writeBit(0, MOTOR_ON_DO_CHANNEL, 0)
                except Exception as exc:
                    print(f"[RealHardware] DO{MOTOR_ON_DO_CHANNEL} aus fehlgeschlagen: {exc}")
            if self._ao is not None:
                try:
                    self._ao.writeAny(MOTOR_SPEED_AO_CHANNEL, 1, None, [0.0])
                except Exception as exc:
                    print(f"[RealHardware] AO{MOTOR_SPEED_AO_CHANNEL} auf 0 V fehlgeschlagen: {exc}")
        self._motor_on = False
