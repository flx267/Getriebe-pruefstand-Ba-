"""
Schnelltest für den Advantech USB-4711A.

Verwendung (Windows, DAQNavi SDK installiert):
  cd SWE/SWE_3_Construction/Pruefstand_Software
  python hardware/daq_test.py

Netzteil anschließen:
  Plus  → AI0 (Klemme 1)
  Minus → AGND (Klemme 17 oder 18)
  Spannung: 0–10 V
"""

import sys
import time

sys.path.insert(0, ".")  # Projekt-Root als Python-Pfad


def test_raw_voltage(channel: int = 0, samples: int = 5) -> None:
    """Liest Rohspannung direkt via DAQNavi, ohne Skalierung."""
    try:
        from Automation.BDaq import ErrorCode
        from Automation.BDaq.InstantAiCtrl import InstantAiCtrl
    except ImportError:
        print("FEHLER: DAQNavi SDK nicht gefunden.")
        print("  1. DAQNavi von Advantech-Website installieren")
        print("  2. pip install advantech-daq")
        return

    from Automation.BDaq.BDaqApi import BioFailed

    print(f"Verbinde mit USB-4711A...")
    ai = InstantAiCtrl("USB-4711A,BID#0")
    ai.loadProfile = ""

    print(f"Verbunden. Lese Kanal AI{channel} ({samples} Messungen, 1 s Abstand):\n")
    print(f"  {'Nr':>3}  {'Spannung [V]':>14}")
    print("  " + "-" * 20)

    for i in range(samples):
        ret, data_list = ai.readData(channel, 1)
        if not BioFailed(ret):
            print(f"  {i+1:>3}  {data_list[0]:>12.4f} V")
        else:
            print(f"  {i+1:>3}  Lesefehler: {ret}")
        time.sleep(1.0)

    ai.dispose()
    print("\nTest abgeschlossen.")


def test_all_sensors() -> None:
    """Liest alle 5 Sensorkanäle über RealHardware (mit Skalierung)."""
    from hardware.real_hardware import RealHardware, SENSOR_CHANNEL_MAP

    hw = RealHardware()
    if not hw.connect():
        print("Verbindung fehlgeschlagen – abgebrochen.")
        return

    sensor_ids = list(SENSOR_CHANNEL_MAP.keys())
    print(f"\n{'Sensor':<15} {'Kanal':>5}  {'Wert':>10}")
    print("-" * 35)

    for sid in sensor_ids:
        val = hw.read(sid)
        ch = SENSOR_CHANNEL_MAP[sid]
        print(f"{sid:<15} {'AI'+str(ch):>5}  {val if val is not None else 'N/A':>10}")

    hw.disconnect()


if __name__ == "__main__":
    print("=== Advantech USB-4711A Schnelltest ===\n")
    print("1) Rohspannung Kanal AI0 messen")
    print("2) Alle 5 Sensorkanäle (mit Skalierung)")
    choice = input("\nAuswahl [1/2]: ").strip()

    if choice == "2":
        test_all_sensors()
    else:
        ch_input = input("Kanal-Nummer (Enter = 0): ").strip()
        ch = int(ch_input) if ch_input.isdigit() else 0
        test_raw_voltage(channel=ch)
