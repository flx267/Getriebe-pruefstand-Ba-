"""
Standalone-Testskript: liest den Vibrationssensor (autosen AV003, 4-20mA)
am USB-4711A Kanal AI7 aus und zeigt den Wert live in der Konsole an.

Verkabelung: 4-20mA Signal × 500Ω Bürde = 2,00–10,00 V an AI7.
  Sensor weiß (L+) → Netzteil +24V
  Sensor braun (Out) → AI7+
  500Ω (2× 1kΩ parallel) zwischen AI7+ und AGND
  AGND → Netzteil GND

Strg+C zum Beenden.
"""

import time

from Automation.BDaq.BDaqApi import BioFailed
from Automation.BDaq.InstantAiCtrl import InstantAiCtrl

DEVICE_DESCRIPTION = "USB-4711A,BID#0"
CHANNEL = 7   # Pinplan, am Prüfstand bestätigt 28.09.2026
RESISTANCE_OHM = 500.0

# AV003: 4mA × 500Ω = 2,00V (0 mm/s)  /  20mA × 500Ω = 10,00V (25 mm/s)
V_MIN, V_MAX = 2.00, 10.00
VIB_MIN, VIB_MAX = 0.0, 25.0


def voltage_to_vibration(voltage: float) -> float:
    ratio = (voltage - V_MIN) / (V_MAX - V_MIN)
    return VIB_MIN + ratio * (VIB_MAX - VIB_MIN)


def main() -> None:
    ai_ctrl = InstantAiCtrl(DEVICE_DESCRIPTION)
    try:
        print(f"Verbunden mit {DEVICE_DESCRIPTION}, lese Kanal AI{CHANNEL}...")
        print("Sensor ruhig auf dem Tisch: ~2,00 V → ~4,00 mA → ~0,0 mm/s\n")
        while True:
            ret, data = ai_ctrl.readData(CHANNEL, 1)
            if BioFailed(ret) or not data:
                print(f"Lesefehler (Code {ret})")
            else:
                voltage = data[0]
                current_ma = (voltage / RESISTANCE_OHM) * 1000
                vibration = voltage_to_vibration(voltage)
                bar = "#" * int(max(0, vibration) / 25 * 30)
                print(f"AI{CHANNEL}: {voltage:6.3f} V  {current_ma:5.2f} mA  ->  {vibration:6.2f} mm/s  [{bar:<30}]")
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\nBeendet.")
    finally:
        ai_ctrl.dispose()


if __name__ == "__main__":
    main()
