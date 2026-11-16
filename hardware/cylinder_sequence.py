"""
Zylinder am Drehmomenthebel (V1 = DO1/DO2 oben, V2 = DO3/DO4 unten) – reine Regeln
ohne Qt/DAQ, genutzt vom Prüfablauf (core/test_runner.py) und vom DAQ-Monitor.

Die 5/2-Ventile sind bistabil: beide Signale 0 → Zylinder bleibt, wo er ist. Die Lage
ergibt sich deshalb nur aus dem zuletzt gegebenen Befehl (DO-Rücklesen).

Ablauf (CYLINDER_HOME):
    Grundstellung  unten aus, oben ein  (DO1=0, DO2=1, DO3=1, DO4=0)
    Messung        Sperrbolzen rein → oben aus/ein
    Entlasten      oben ein → unten ein → Sperrbolzen raus → unten aus
"""

import math
from typing import Callable

from config.settings import (
    CYLINDER_BORE_MM, CYLINDER_HOME, CYLINDER_VALVES, LEVER_ARM_MM, VALVE_CHANNEL_MAP,
)

UP_EXT = VALVE_CHANNEL_MAP[CYLINDER_VALVES["oben"]["extend"]]      # DO1
UP_RET = VALVE_CHANNEL_MAP[CYLINDER_VALVES["oben"]["retract"]]     # DO2
LO_EXT = VALVE_CHANNEL_MAP[CYLINDER_VALVES["unten"]["extend"]]     # DO3
LO_RET = VALVE_CHANNEL_MAP[CYLINDER_VALVES["unten"]["retract"]]    # DO4
CYL_VALVE_CHANNELS = {UP_EXT, UP_RET, LO_EXT, LO_RET}

# Gegenspule je Kanal: Ausfahren ↔ Einfahren desselben Zylinders nie gleichzeitig an
CYL_PARTNER: dict[int, int] = {}
# Grundstellung: DO-Kanal → Soll-Bit
CYL_HOME_DO: dict[int, int] = {}
for _cyl, _sig in CYLINDER_VALVES.items():
    _ext, _ret = VALVE_CHANNEL_MAP[_sig["extend"]], VALVE_CHANNEL_MAP[_sig["retract"]]
    CYL_PARTNER[_ext], CYL_PARTNER[_ret] = _ret, _ext
    CYL_HOME_DO[_ext] = 1 if CYLINDER_HOME[_cyl] == "extend" else 0
    CYL_HOME_DO[_ret] = 1 if CYLINDER_HOME[_cyl] == "retract" else 0

# Drehmoment am Hebel aus dem Zylinderdruck DS1: M = p · A · r  (0,1 N/mm² je bar)
NM_PER_BAR = 0.1 * math.pi / 4 * CYLINDER_BORE_MM ** 2 * LEVER_ARM_MM / 1000.0


def torque_from_pressure(p_bar: float) -> float:
    return p_bar * NM_PER_BAR


def upper_retracted(do: list) -> bool:
    return do[UP_RET] == 1 and do[UP_EXT] == 0


def lower_extended(do: list) -> bool:
    return do[LO_EXT] == 1 and do[LO_RET] == 0


def at_home(do: list) -> bool:
    return all(do[ch] == bit for ch, bit in CYL_HOME_DO.items())


def home_deviations(do: list) -> list[str]:
    return [f"DO{ch}={do[ch]}" for ch, bit in CYL_HOME_DO.items() if do[ch] != bit]


def cylinder_violation(channel: int, on: bool, do: list) -> str:
    """Reihenfolge Grundstellung → Messung → Entlasten; "" = erlaubt.
    Ausschalten eines Signals ist immer erlaubt (bistabil: Zylinder bleibt stehen)."""
    if not on or channel == UP_RET:
        return ""
    if channel == UP_EXT and not lower_extended(do):
        return "oben ausfahren nur, wenn unten ausgefahren ist"
    if channel in (LO_EXT, LO_RET) and not upper_retracted(do):
        return "unten nur bewegen, wenn oben eingefahren ist"
    return ""


def move(channel: int, do: list, write_bit: Callable[[int, int], str]) -> str:
    """Eine Zylinderbewegung: Regel prüfen, Gegenspule aus, Spule an.
    `write_bit(ch, bit)` gibt Fehlertext oder "" zurück. Rückgabe: Fehlertext oder ""."""
    if any(do[ch] is None for ch in CYL_VALVE_CHANNELS):
        return "DO nicht lesbar"
    reason = cylinder_violation(channel, True, do)
    if reason:
        return f"DO{channel} verweigert: {reason}"
    error = write_bit(CYL_PARTNER[channel], 0)
    if error:
        return f"DO{CYL_PARTNER[channel]} (Gegenspule) aus fehlgeschlagen: {error}"
    return write_bit(channel, 1)
