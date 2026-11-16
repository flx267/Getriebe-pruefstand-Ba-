from abc import ABC, abstractmethod
from typing import Optional


class SensorInterface(ABC):
    """Hardware des Prüfstands: USB-4711A (AI Sensoren, DI Sicherheit/Sperrbolzen,
    DO Ventile + Motor on, AO Drehzahl-Sollwert). Alle Schreibmethoden geben einen
    Fehlertext zurück, "" = in Ordnung."""

    @abstractmethod
    def connect(self) -> bool:
        pass

    @abstractmethod
    def disconnect(self) -> None:
        pass

    @property
    def connect_error(self) -> str:
        """Grund, warum connect() fehlgeschlagen ist (für die Fehlermeldung)."""
        return ""

    @abstractmethod
    def read(self, sensor_id: str) -> Optional[float]:
        """Read a single sensor value. Returns None if unavailable."""
        pass

    @abstractmethod
    def read_di(self) -> Optional[list[int]]:
        """DI0–DI7 als Bits, None bei Lesefehler (Aufrufer behandelt das fail-safe)."""
        pass

    @abstractmethod
    def read_do(self) -> Optional[list[int]]:
        """Zurückgelesener Zustand DO0–DO7, None bei Lesefehler."""
        pass

    @abstractmethod
    def write_do(self, channel: int, bit: int) -> str:
        """Setzt einen Digitalausgang (Ventile DO1–DO6). DO0 nur über start/stop_motor."""
        pass

    @abstractmethod
    def start_motor(self, rpm: float) -> str:
        """Sollwert auf AO0, dann Motor on (DO0)."""
        pass

    @abstractmethod
    def stop_motor(self) -> None:
        """Motor on weg (DO0), Sollwert 0 V. Fehler werden nur geloggt.
        NOT-AUS erfolgt hardwareseitig über den Not-Aus-Kreis."""
        pass

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        pass
