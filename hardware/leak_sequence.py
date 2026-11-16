"""
Leckage-Prüfablauf (Ventile V3 = DO5, V4 = DO6) – reine Ablauflogik ohne Qt/DAQ.

Genutzt vom Prüfablauf (core/test_runner.py), vom DAQ-Monitor (ui/debug_daq_monitor.py)
und vom Konsolen-Test (test_leak.py), damit alle garantiert dieselbe Schaltfolge fahren:

    Phase            DO5  DO6   Ende
    Befüllen          1    1    nach fill_s
    Halten            0    0*   nach hold_s  (Druckabfall wird gemessen; *LEAK_HOLD_DO6)
    Entlüften         1    0    nach vent_s
    Fertig            0    0

Abbruch springt immer in „Entlüften“. Früher stand davor ein Schritt 1/1 – der ist
identisch mit Befüllen und hat nach dem Halten kurz Luft nachgefüllt (Nutzer 10.10.2026).
Beim Phasenwechsel wird immer zuerst abgeschaltet, dann eingeschaltet (valves_for),
damit 0/1 → 1/0 nicht kurz über 1/1 läuft.
"""

import math
import time
from typing import Callable, Optional

import config.settings as _settings
from config.settings import VALVE_CHANNEL_MAP

DO5 = VALVE_CHANNEL_MAP["V3_5"]
DO6 = VALVE_CHANNEL_MAP["V4_6"]

# (key, Anzeigename, DO5, DO6)
PHASES: list[tuple[str, str, int, int]] = [
    ("fill",  "Befüllen",    1, 1),
    # DO6 beim Halten je nach Verschlauchung von V3, siehe config/settings.py → LEAK_HOLD_DO6
    ("hold",  "Halten",      0, _settings.LEAK_HOLD_DO6),
    ("vent",  "Entlüften",   1, 0),
    ("done",  "Fertig",      0, 0),
]
_INDEX = {key: i for i, (key, *_rest) in enumerate(PHASES)}

# Standardwerte beim Import (Anzeige im DAQ-Monitor); rate_drop() liest zur Laufzeit,
# damit Änderungen aus dem Grenzwerte-Dialog (apply_grenzwerte_to_settings) greifen.
LEAK_WARN_DROP_BAR = _settings.LEAK_WARN_DROP_BAR
LEAK_CRITICAL_DROP_BAR = _settings.LEAK_CRITICAL_DROP_BAR


def valves_for(key: str) -> dict[int, int]:
    """Ventilzustände der Phase – Reihenfolge: erst Abschalten (0), dann Einschalten (1),
    weil alle Aufrufer die Kanäle nacheinander in dieser Reihenfolge schreiben."""
    _, _, do5, do6 = PHASES[_INDEX[key]]
    return dict(sorted({DO5: do5, DO6: do6}.items(), key=lambda item: item[1]))


def phase_name(key: str) -> str:
    return PHASES[_INDEX[key]][1]


def rate_drop(drop_bar: float) -> str:
    """Bewertung des Druckabfalls: "ok" | "warn" | "crit"."""
    if drop_bar >= _settings.LEAK_CRITICAL_DROP_BAR:
        return "crit"
    if drop_bar >= _settings.LEAK_WARN_DROP_BAR:
        return "warn"
    return "ok"


class LeakSequence:
    """Nicht blockierender Zustandsautomat. Der Aufrufer liefert die Zeit (`now`,
    z. B. time.monotonic()) und den aktuellen Druck; zurückgegeben werden die
    Ventilzustände {DO-Kanal: Bit}, die beim Phasenwechsel zu schreiben sind."""

    def __init__(self, fill_s: float, hold_s: float, vent_s: float):
        self._durations = {"fill": fill_s, "hold": hold_s, "vent": vent_s}
        self.phase: Optional[str] = None
        self._phase_end = 0.0
        self.p_start = math.nan
        self.p_end = math.nan
        self.p_last = math.nan
        self.aborted = False   # True → kein vollständiger Durchlauf, keine Bewertung

    def _enter(self, key: str, now: float) -> dict[int, int]:
        self.phase = key
        self._phase_end = now + self._durations.get(key, 0.0)
        return valves_for(key)

    def start(self, now: float, vent_only: bool = False) -> dict[int, int]:
        """vent_only=True: nur die Entlüft-Folge fahren (z. B. nach manuellem Befüllen)."""
        self.aborted = vent_only
        return self._enter("vent" if vent_only else "fill", now)

    def update(self, now: float, pressure_bar: float) -> Optional[dict[int, int]]:
        if self.phase is None or self.done:
            return None
        if not math.isnan(pressure_bar):
            self.p_last = pressure_bar
        if now < self._phase_end:
            return None
        nxt = PHASES[_INDEX[self.phase] + 1][0]
        if nxt == "hold":
            self.p_start = self.p_last
        elif self.phase == "hold":
            self.p_end = self.p_last
        return self._enter(nxt, now)

    def abort(self, now: float) -> Optional[dict[int, int]]:
        """Springt in die Entlüft-Folge. Bereits beim Entlüften → nichts ändern."""
        if self.phase in (None, "vent", "done"):
            return None
        self.aborted = True
        return self._enter("vent", now)

    @property
    def done(self) -> bool:
        return self.phase == "done"

    @property
    def running(self) -> bool:
        return self.phase is not None and not self.done

    def remaining_s(self, now: float) -> float:
        return 0.0 if self.done else max(0.0, self._phase_end - now)

    def drop_bar(self) -> float:
        """Druckabfall während Halten; läuft Halten noch, bis zum aktuellen Wert."""
        end = self.p_end if not math.isnan(self.p_end) else (
            self.p_last if self.phase == "hold" else math.nan)
        return self.p_start - end


def vent_blocking(write_bit: Callable[[int, int], object], vent_s: float) -> list[str]:
    """Entlüft-Folge 1/0 → 0/0 blockierend (Fenster schließen, Strg+C).
    Fehler beim Schreiben werden gesammelt, die restlichen Schritte trotzdem versucht."""
    errors = []
    steps = ["vent", "done"]
    for i, key in enumerate(steps):
        for ch, bit in valves_for(key).items():
            try:
                write_bit(ch, bit)
            except Exception as exc:
                errors.append(f"DO{ch}={bit}: {exc}")
        if i < len(steps) - 1:
            time.sleep(vent_s)
    return errors
