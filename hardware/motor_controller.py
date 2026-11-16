"""
Hitachi WJ-C1 Frequenzumrichter – Modbus RTU Steuerung

Verbindung: USB-RS485-Adapter → Klemmen SP (+) / SN (-) am FU

WICHTIG: Register-Adressen und Befehlswerte aus dem WJ-C1 Instruction Manual
(nicht der Broschüre!) verifizieren. Die Werte unten basieren auf dem
WJ200-Vorgänger (Basic Mode, der im WJ-C1 vollständig kompatibel ist).

Voraussetzungen:
    pip install minimalmodbus

FU-Parameter (vor Erstbetrieb am JOG Dial oder via proDRiVE einstellen):
    Slave-Adresse : P-7-5 (oder C071 im WJ200-Modus) → Wert: 1
    Baudrate      : P-7-6 (oder C074)                 → Wert: 3 (= 9600 Bd)
    Stoppbit      : P-7-7 (oder C075)                 → Wert: 0 (= 1 Stoppbit)
    Befehlsquelle : A002                              → Wert: 3 (= Modbus)
    Sollwertquelle: A001                              → Wert: 3 (= Modbus)
"""

from typing import Optional

import minimalmodbus

# ── Modbus-Register-Adressen ──────────────────────────────────────────────────
# Basis: Hitachi WJ200 Instruction Manual, Modbus-Kapitel (WJ-C1 Basic Mode)
# !! Vor Inbetriebnahme aus WJ-C1 Instruction Manual verifizieren !!
REG_RUN_CMD    = 0x0001   # Steuerbefehl (FC 06 schreiben)
REG_FREQ_SET   = 0x0002   # Frequenz-Sollwert in 0,01 Hz (FC 06 schreiben)
REG_FREQ_OUT   = 0x0003   # Ist-Ausgangsfrequenz in 0,01 Hz (FC 03 lesen)
REG_CURRENT    = 0x0004   # Ausgangsstrom in 0,01 A (FC 03 lesen)
REG_FAULT_CODE = 0x0006   # Störungscode, 0 = kein Fehler (FC 03 lesen)
REG_STATUS     = 0x0007   # Statuswort (FC 03 lesen)

# Befehlswerte für REG_RUN_CMD
CMD_NOP          = 0x0000
CMD_STOP         = 0x0001
CMD_RUN_FORWARD  = 0x0002
CMD_RUN_REVERSE  = 0x0003
CMD_FAULT_RESET  = 0x0006


class MotorController:
    """Steuert den Hitachi WJ-C1 Frequenzumrichter über Modbus RTU (RS485)."""

    def __init__(self, port: str, baudrate: int = 9600, slave_address: int = 1):
        self._port = port
        self._baudrate = baudrate
        self._slave_address = slave_address
        self._instrument: Optional[minimalmodbus.Instrument] = None
        self._connected = False

    def connect(self) -> bool:
        try:
            inst = minimalmodbus.Instrument(self._port, self._slave_address)
            inst.serial.baudrate = self._baudrate
            inst.serial.bytesize = 8
            inst.serial.parity   = minimalmodbus.serial.PARITY_NONE
            inst.serial.stopbits = 1
            inst.serial.timeout  = 0.5
            inst.mode  = minimalmodbus.MODE_RTU
            inst.debug = False
            self._instrument = inst
            self._connected = True
            print(f"[MotorController] WJ-C1 verbunden: {self._port}, Slave {self._slave_address}")
            return True
        except Exception as exc:
            print(f"[MotorController] Verbindungsfehler: {exc}")
            return False

    def disconnect(self) -> None:
        if self._instrument is not None:
            try:
                self.stop()
            except Exception:
                pass
            try:
                self._instrument.serial.close()
            except Exception:
                pass
        self._instrument = None
        self._connected = False

    # ── Steuerbefehle ─────────────────────────────────────────────────────────

    def start(self, freq_hz: float = 50.0) -> bool:
        """Startet den Motor mit Vorwärtslauf bei gegebener Frequenz."""
        if not self._connected or self._instrument is None:
            return False
        try:
            freq_val = int(round(freq_hz * 100))   # 0,01 Hz Auflösung
            self._instrument.write_register(REG_FREQ_SET, freq_val, functioncode=6)
            self._instrument.write_register(REG_RUN_CMD, CMD_RUN_FORWARD, functioncode=6)
            print(f"[MotorController] Motor gestartet: {freq_hz:.2f} Hz "
                  f"(→ {freq_hz / 50.0 * 1500:.0f} RPM nominal)")
            return True
        except Exception as exc:
            print(f"[MotorController] Startfehler: {exc}")
            return False

    def stop(self) -> bool:
        """Stoppt den Motor mit konfigurierter Ablaufzeit (Rampen-Stopp)."""
        if not self._connected or self._instrument is None:
            return False
        try:
            self._instrument.write_register(REG_RUN_CMD, CMD_STOP, functioncode=6)
            print("[MotorController] Motor gestoppt (Rampe)")
            return True
        except Exception as exc:
            print(f"[MotorController] Stoppfehler: {exc}")
            return False

    def reset_fault(self) -> bool:
        """Setzt eine aktive Störung zurück."""
        if not self._connected or self._instrument is None:
            return False
        try:
            self._instrument.write_register(REG_RUN_CMD, CMD_FAULT_RESET, functioncode=6)
            print("[MotorController] Störung zurückgesetzt")
            return True
        except Exception as exc:
            print(f"[MotorController] Fault-Reset-Fehler: {exc}")
            return False

    # ── Statusabfragen ────────────────────────────────────────────────────────

    def read_output_freq(self) -> Optional[float]:
        """Gibt die aktuelle Ausgangsfrequenz in Hz zurück, oder None bei Fehler."""
        if not self._connected or self._instrument is None:
            return None
        try:
            raw = self._instrument.read_register(REG_FREQ_OUT, functioncode=3)
            return raw / 100.0
        except Exception:
            return None

    def read_output_current(self) -> Optional[float]:
        """Gibt den aktuellen Ausgangsstrom in A zurück, oder None bei Fehler."""
        if not self._connected or self._instrument is None:
            return None
        try:
            raw = self._instrument.read_register(REG_CURRENT, functioncode=3)
            return raw / 100.0
        except Exception:
            return None

    def read_fault_code(self) -> Optional[int]:
        """Gibt den aktuellen Störungscode zurück (0 = kein Fehler)."""
        if not self._connected or self._instrument is None:
            return None
        try:
            return self._instrument.read_register(REG_FAULT_CODE, functioncode=3)
        except Exception:
            return None

    @property
    def is_connected(self) -> bool:
        return self._connected
