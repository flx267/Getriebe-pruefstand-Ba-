"""
Standalone-Testskript: liest nur den Temperatursensor (PT1000 via TxRail-USB)
am USB-4711A Kanal AI0 (T1) aus und zeigt den Wert live in der Konsole an.
T2 liegt auf AI1 – dafür CHANNEL = 1 setzen.

TxRail-USB Konfiguration: 0-10V Ausgang, Messbereich 0 bis 100 °C.

Strg+C zum Beenden.
"""

import time

from Automation.BDaq.BDaqApi import BioFailed
from Automation.BDaq.InstantAiCtrl import InstantAiCtrl

DEVICE_DESCRIPTION = "USB-4711A,BID#0"
CHANNEL = 0   # T1 (Pinplan, am Prüfstand bestätigt 28.09.2026)

# TxRail-USB: 0V -> 0 °C, 10V -> 100 °C (Angabe Nutzer, 28.09.2026)
V_MIN, V_MAX = 0.0, 10.0
T_MIN, T_MAX = 0.0, 100.0


def voltage_to_celsius(voltage: float) -> float:
    ratio = (voltage - V_MIN) / (V_MAX - V_MIN)
    return T_MIN + ratio * (T_MAX - T_MIN)


def main() -> None:
    ai_ctrl = InstantAiCtrl(DEVICE_DESCRIPTION)
    try:
        print(f"Verbunden mit {DEVICE_DESCRIPTION}, lese Kanal AI{CHANNEL}...")
        while True:
            ret, data = ai_ctrl.readData(CHANNEL, 1)
            if BioFailed(ret) or not data:
                print(f"Lesefehler (Code {ret})")
            else:
                voltage = data[0]
                temp = voltage_to_celsius(voltage)
                print(f"AI{CHANNEL}: {voltage:6.3f} V  ->  {temp:7.2f} °C")
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nBeendet.")
    finally:
        ai_ctrl.dispose()


if __name__ == "__main__":
    main()
