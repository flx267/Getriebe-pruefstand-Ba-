"""Simulation für Entwicklertests (python main.py --sim) – ersetzt die USB-4711A.

Druck, Moment und Sperrbolzen folgen den geschalteten Ausgängen, damit der komplette
Prüfablauf durchläuft: Leckage-Druck nur bei befülltem Strang, Moment nur bei
ausgefahrenem oberem Zylinder, DI3 wechselt ≈ 3 s nach simulate_bolt()."""

import math
import random
import time
from typing import Optional

import config.settings as _settings
from config.settings import BOLT_DI, BOLT_OUT_VALUE, SENSORS, SAFETY_REQUIRED_DI
from hardware.base import SensorInterface
from hardware.cylinder_sequence import UP_EXT, torque_from_pressure
from hardware.leak_sequence import DO5, DO6

_BOLT_DELAY_S = 3.0


class SimulatedHardware(SensorInterface):

    def __init__(self):
        self._connected = False
        self._start_time: float = 0.0
        self._sensor_map = {s["id"]: s for s in SENSORS}
        self._do = [0] * 8
        self._motor_on = False
        self._bolt_in = False
        self._bolt_target: Optional[tuple[bool, float]] = None   # (Soll, Zeitpunkt)
        self._hold_since: Optional[float] = None

    def connect(self) -> bool:
        self._connected = True
        self._start_time = time.time()
        return True

    def disconnect(self) -> None:
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def simulate_bolt(self, inserted: bool) -> None:
        """Werker schiebt den Bolzen ein/zieht ihn – DI3 folgt nach _BOLT_DELAY_S."""
        self._bolt_target = (inserted, time.monotonic() + _BOLT_DELAY_S)

    def _noise(self, sensor_id: str) -> float:
        sensor = self._sensor_map[sensor_id]
        elapsed = time.time() - self._start_time
        mid = (sensor["sim_min"] + sensor["sim_max"]) / 2
        amplitude = (sensor["sim_max"] - sensor["sim_min"]) / 2
        return (mid + amplitude * 0.4 * math.sin(elapsed * 0.3 + hash(sensor_id) % 10)
                + random.gauss(0, sensor["sim_noise"]))

    def read(self, sensor_id: str) -> Optional[float]:
        if not self._connected or sensor_id not in self._sensor_map:
            return None
        if sensor_id == "pressure":
            if self._do[DO6] and self._do[DO5]:              # Befüllen
                self._filled = True
                self._hold_since = None
                return round(0.98 + random.gauss(0, 0.003), 3)
            if self._do[DO5] and not self._do[DO6]:          # Entlüften → drucklos
                self._filled = False
            if getattr(self, "_filled", False):              # Halten (0/0 oder 0/1)
                self._hold_since = self._hold_since or time.monotonic()
                return round(0.98 - 0.0002 * (time.monotonic() - self._hold_since)
                             + random.gauss(0, 0.002), 3)
            return round(0.2 + random.gauss(0, 0.003), 3)    # drucklos
        if sensor_id == "torque":
            p = self.read("pressure_cyl")
            return round(torque_from_pressure(p), 1) if self._do[UP_EXT] else round(
                random.gauss(0, 1.0), 1)
        if sensor_id == "speed":   # RPM1 folgt der Soll-Drehzahl, solange der Motor läuft
            if not self._motor_on:
                return 0.0
            return round(_settings.MOTOR_RUN_RPM * (1 + random.gauss(0, 0.005)), 1)
        if sensor_id == "torque_nm1":
            return round(self._noise(sensor_id), 1) if self._do[UP_EXT] else round(
                random.gauss(0, 2.0), 1)
        if sensor_id == "torque_nm1_v":
            return round(self._noise(sensor_id), 4) if self._do[UP_EXT] else round(
                random.gauss(0, 0.003), 4)
        return round(self._noise(sensor_id), 3)

    def read_di(self) -> Optional[list[int]]:
        if not self._connected:
            return None
        if self._bolt_target and time.monotonic() >= self._bolt_target[1]:
            self._bolt_in = self._bolt_target[0]
            self._bolt_target = None
        di = [1] * 8
        for ch, bit in SAFETY_REQUIRED_DI.items():
            di[ch] = bit
        di[BOLT_DI] = (1 - BOLT_OUT_VALUE) if self._bolt_in else BOLT_OUT_VALUE
        return di

    def read_do(self) -> Optional[list[int]]:
        return list(self._do) if self._connected else None

    def write_do(self, channel: int, bit: int) -> str:
        if not 1 <= channel <= 6:
            return f"DO{channel} ist kein Ventil – verweigert"
        self._do[channel] = 1 if bit else 0
        print(f"[SimulatedHardware] DO{channel} → {self._do[channel]}")
        return ""

    def start_motor(self, rpm: float) -> str:
        if self._bolt_in:
            return "Motorstart verweigert: Sperrbolzen steckt (Simulation)"
        self._motor_on = True
        self._do[0] = 1
        print(f"[SimulatedHardware] Motor gestartet (simuliert): {rpm:.0f} rpm")
        return ""

    def stop_motor(self) -> None:
        self._motor_on = False
        self._do[0] = 0
        print("[SimulatedHardware] Motor gestoppt (simuliert)")
