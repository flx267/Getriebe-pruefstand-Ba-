"""
Standalone-Testskript: fährt den kompletten Leckage-Ablauf (V3 = DO5, V4 = DO6) an der
USB-4711A und zeigt Phase, Ventilzustände und den Druck DS2 live in der Konsole an.

Ablauf (hardware/leak_sequence.py, DO5/DO6):
  Befüllen 1/1 → Beruhigen/Halten 0/LEAK_HOLD_DO6 → Entlüften 1/0 → Fertig 0/0

Aufruf:
    cd Pruefstand_Software
    python test_leak.py [--fill 10] [--hold 60] [--vent 1]

DAQ-Monitor vorher schließen (Karte kann nur von einem Programm benutzt werden).
Strg+C bricht ab – es wird dabei immer korrekt entlüftet.
"""

import argparse
import math
import time
from datetime import datetime

from Automation.BDaq import ValueRange
from Automation.BDaq.BDaqApi import BioFailed
from Automation.BDaq.InstantAiCtrl import InstantAiCtrl
from Automation.BDaq.InstantDoCtrl import InstantDoCtrl

from config.settings import LEAK_FILL_S, LEAK_HOLD_S, LEAK_SETTLE_S, LEAK_VENT_STEP_S
from hardware.leak_sequence import (
    DO5, DO6, LEAK_CRITICAL_DROP_BAR, LEAK_WARN_DROP_BAR,
    LeakSequence, phase_name, rate_drop, vent_blocking,
)
from hardware.real_hardware import SENSOR_CHANNEL_MAP, SENSOR_SCALE, _scale

DEVICE_DESCRIPTION = "USB-4711A,BID#0"
PRESSURE_CHANNEL = SENSOR_CHANNEL_MAP["pressure"]   # DS2
POLL_S = 0.2
BAR_WIDTH = 20
_RATING_TEXT = {"ok": "OK", "warn": "WARNUNG", "crit": "KRITISCH"}


def _stamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _fmt_bar(value: float) -> str:
    return "–" if math.isnan(value) else f"{value:.3f} bar"


def main() -> None:
    parser = argparse.ArgumentParser(description="Leckage-Ablauf DO5/DO6 testen")
    parser.add_argument("--fill", type=float, default=LEAK_FILL_S, help="Befüllen [s]")
    parser.add_argument("--hold", type=float, default=LEAK_HOLD_S, help="Halten [s]")
    parser.add_argument("--vent", type=float, default=LEAK_VENT_STEP_S, help="Entlüften [s]")
    args = parser.parse_args()

    print(f"Leckage-Test: Befüllen {args.fill:g} s · Halten {args.hold:g} s · "
          f"Entlüften {args.vent:g} s")
    print(f"Druck: DS2 an AI{PRESSURE_CHANNEL} · Ventile: V3 = DO{DO5}, V4 = DO{DO6}")
    if input("Prüfstand bereit, Getriebe angeschlossen? [j/N] ").strip().lower() != "j":
        print("Abgebrochen.")
        return

    try:
        ai = InstantAiCtrl(DEVICE_DESCRIPTION)
        do = InstantDoCtrl(DEVICE_DESCRIPTION)
    except Exception as exc:
        msg = str(exc)
        if "0xE0000010" in msg:
            msg = ("Karte wird von einem anderen Programm benutzt "
                   "(z. B. DAQ-Monitor oder Advantech Navigator offen)")
        print(f"Keine Verbindung zur Karte: {msg}")
        return
    # Ohne explizit gesetzten Messbereich liefert die Karte nur 0 V
    ai.channels[PRESSURE_CHANNEL].valueRange = ValueRange.V_Neg5To5
    ai.channels[PRESSURE_CHANNEL].valueRange = ValueRange.V_Neg10To10

    state = {DO5: 0, DO6: 0}

    def write_bit(ch: int, bit: int) -> None:
        ret = do.writeBit(0, ch, bit)
        if BioFailed(ret):
            raise RuntimeError(f"DO{ch} schreiben fehlgeschlagen: {ret.name}")
        state[ch] = bit

    def apply(valves: dict[int, int]) -> None:
        for ch, bit in valves.items():
            write_bit(ch, bit)

    def read_pressure() -> tuple[float, float]:
        ret, data = ai.readData(PRESSURE_CHANNEL, 1)
        if BioFailed(ret) or not data:
            return math.nan, math.nan
        return data[0], _scale(data[0], *SENSOR_SCALE["pressure"])

    seq = LeakSequence(args.fill, args.hold, args.vent, settle_s=LEAK_SETTLE_S)
    completed = False
    try:
        apply(seq.start(time.monotonic()))
        print(f"\n{_stamp()}  ► {phase_name(seq.phase)}  (DO5={state[DO5]} DO6={state[DO6]})")
        while not seq.done:
            voltage, pressure = read_pressure()
            valves = seq.update(time.monotonic(), pressure)
            if valves is not None:
                apply(valves)
                print(f"\n{_stamp()}  ► {phase_name(seq.phase)}  (DO5={state[DO5]} DO6={state[DO6]})")
                if seq.phase == "hold":
                    print(f"          Druck Beginn Halten: {_fmt_bar(seq.p_start)}")
                continue

            if math.isnan(voltage):
                p_txt = "Lesefehler"
                bar = ""
            else:
                p_txt = f"{voltage:+6.3f} V → {pressure:6.3f} bar"
                p_max = SENSOR_SCALE["pressure"][3]
                bar = "#" * max(0, min(BAR_WIDTH, round(pressure / p_max * BAR_WIDTH)))
            drop = seq.drop_bar()
            drop_txt = "" if math.isnan(drop) else f"  Abfall {drop:+.3f} bar"
            print(f"[{phase_name(seq.phase):<11}] noch {seq.remaining_s(time.monotonic()):5.1f} s  "
                  f"DO5={state[DO5]} DO6={state[DO6]}  DS2 AI{PRESSURE_CHANNEL}: {p_txt}  "
                  f"[{bar:<{BAR_WIDTH}}]{drop_txt}")
            time.sleep(POLL_S)
        completed = True
    except KeyboardInterrupt:
        print(f"\n{_stamp()}  Abbruch durch Strg+C")
    except Exception as exc:
        print(f"\n{_stamp()}  FEHLER: {exc}")
    finally:
        if not completed:
            print(f"{_stamp()}  Entlüfte: DO5/DO6 1/0 → 0/0 …")
            for err in vent_blocking(write_bit, args.vent):
                print(f"          {err}")
        # Absicherung: beide Ventile zu, egal was vorher passiert ist
        for ch in (DO5, DO6):
            try:
                do.writeBit(0, ch, 0)
            except Exception as exc:
                print(f"          DO{ch} aus fehlgeschlagen: {exc}")
        ai.dispose()
        do.dispose()

    print("\n── Ergebnis ──────────────────────────────")
    print(f"  Druck Beginn Halten : {_fmt_bar(seq.p_start)}")
    print(f"  Druck Ende Halten   : {_fmt_bar(seq.p_end)}")
    drop = seq.p_start - seq.p_end
    if completed and not math.isnan(drop):
        print(f"  Druckabfall         : {drop:.3f} bar  → {_RATING_TEXT[rate_drop(drop)]}")
        print(f"  (Grenzen: Warnung ab {LEAK_WARN_DROP_BAR} bar, kritisch ab "
              f"{LEAK_CRITICAL_DROP_BAR} bar – Platzhalter)")
    else:
        print("  Keine Bewertung (Ablauf nicht vollständig)")


if __name__ == "__main__":
    main()
