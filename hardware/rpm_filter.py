"""Ausreißer-Filter für den Drehzahlsensor RPM1 (CNT0).

Der Zähler springt gelegentlich für etwa eine Sekunde auf unplausible Werte (Millionen Hz).
Solche Werte werden verworfen (None), damit Anzeige, Diagramm, Prüfbericht und Bewertung
nicht verfälscht werden – gezählt werden sie trotzdem, damit der Prüfer davon erfährt.

Verworfen wird
  1. alles über RPM1_MAX_RPM (bzw. negativ) – harte Plausibilitätsgrenze,
  2. ein Sprung um mehr als RPM1_JUMP_PCT % (mind. RPM1_JUMP_MIN_RPM) gegenüber den letzten gültigen
     Werte. Bleibt der neue Wert aber RPM1_JUMP_CONFIRM Messungen in Folge stabil, ist
     es eine echte Drehzahländerung (z. B. Hochlauf) und wird übernommen.
"""

import statistics
from typing import Optional

import config.settings as _settings

_HISTORY = 3   # letzte gültige Werte, deren Median ist die Referenz


class RpmSpikeFilter:

    def __init__(self):
        self._history: list[float] = []
        self._pending: list[float] = []   # Kandidaten nach einem Sprung
        self.rejected = 0                 # verworfene Werte seit Programmstart

    def reset(self, expected: Optional[float] = None) -> None:
        """Beim Motorstart: Verlauf vergessen und die Soll-Drehzahl als erste Referenz
        nehmen – sonst könnte gleich der erste Wert ein Ausreißer sein. Zeigt der Sensor
        dauerhaft etwas anderes, wird das nach RPM1_JUMP_CONFIRM Messungen übernommen."""
        self._history = [expected] if expected else []
        self._pending.clear()

    @staticmethod
    def _jump(a: float, b: float) -> bool:
        limit = max(abs(b) * _settings.RPM1_JUMP_PCT / 100.0, _settings.RPM1_JUMP_MIN_RPM)
        return abs(a - b) > limit

    def filter(self, rpm: float) -> Optional[float]:
        if rpm < 0 or rpm > _settings.RPM1_MAX_RPM:
            self.rejected += 1
            return None
        # Referenz = Median der letzten gültigen Werte (folgt einem Hochlauf)
        if self._history and self._jump(rpm, statistics.median(self._history)):
            if self._pending and self._jump(rpm, statistics.median(self._pending)):
                self._pending.clear()   # Kandidaten uneinheitlich → neu sammeln
            self._pending.append(rpm)
            if len(self._pending) < _settings.RPM1_JUMP_CONFIRM:
                self.rejected += 1
                return None
            # stabil auf neuem Niveau → echte Änderung, Verlauf neu aufbauen
            self._history = self._pending[-_HISTORY:]
            self._pending = []
            return rpm
        self._pending.clear()
        self._history.append(rpm)
        del self._history[:-_HISTORY]
        return rpm
