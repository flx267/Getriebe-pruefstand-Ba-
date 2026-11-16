from pathlib import Path
import os
import sys

OUTPUT_DIR = Path(os.path.expanduser("~")) / "Desktop" / "Prüfungsberichte"

# Auf False setzen um CSV-Speicherung zu deaktivieren
SAVE_CSV = True

# Messzeiten – Standardwerte (im Startdialog pro Prüfung änderbar)
STEP1_DURATION_MINUTES = 15    # Lastlauf (Vibration / Temperatur)
STEP2_DURATION_SECONDS = 120   # Leckage: Haltezeit (Druckabfall wird gemessen)
STEP3_DURATION_SECONDS = 120   # Kraftprüfung: Haltezeit oben ausgefahren

# Maximale Messzeiten (veränderbar über GrenzwerteDialog)
MAX_STEP1_DURATION_MINUTES = 2000
MAX_STEP2_DURATION_SECONDS = 3600
MAX_STEP3_DURATION_SECONDS = 3600

# Speicherort für Sitzungsdaten (letzter Prüfer, letzte Prüfnummer)
# Als .exe neben der .exe, sonst im Projektordner
if getattr(sys, "frozen", False):
    SESSION_FILE = Path(sys.executable).parent / "last_session.json"
else:
    SESSION_FILE = Path(__file__).parent.parent / "last_session.json"

# Live bewertete Sensoren haben warn_threshold/critical_threshold. Druck, Drehmoment
# werden NICHT live bewertet, sondern am Schrittende (Druckabfall / Soll-Moment).
SENSORS = [
    {
        "id": "vibration",
        "name": "Vibration",
        "unit": "mm/s",
        "warn_threshold": 5.0,
        "critical_threshold": 8.0,
        "critical_debounce": 4,    # 4 × 100 ms = 400 ms – Spikes durch Fremdvibrationen ignorieren
        "sim_min": 0.5,
        "sim_max": 4.0,
        "sim_noise": 0.3,
    },
    {
        "id": "temperature",
        "name": "Temperatur T1",
        "unit": "°C",
        "chart_group": "temperature",
        # Claas-Diagramm: Normalbetrieb bis ≈ 85 °C (Nutzer 30.09.2026: 90 / 100)
        "warn_threshold": 90.0,
        "critical_threshold": 100.0,
        "sim_min": 22.0,
        "sim_max": 48.0,
        "sim_noise": 0.5,
    },
    {
        "id": "temperature2",
        "name": "Temperatur T2",
        "unit": "°C",
        "chart_group": "temperature",
        "warn_threshold": 90.0,
        "critical_threshold": 100.0,
        "sim_min": 18.0,
        "sim_max": 44.0,
        "sim_noise": 0.6,
    },
    {
        "id": "pressure",
        "name": "Druck Leckage (DS2)",
        "unit": "bar",
        "sim_min": 0.95,
        "sim_max": 1.0,
        "sim_noise": 0.003,
    },
    {
        "id": "pressure_cyl",
        "name": "Druck Zylinder (DS1)",
        "unit": "bar",
        "sim_min": 5.98,
        "sim_max": 6.04,
        "sim_noise": 0.01,
    },
    {
        "id": "torque",
        "name": "Moment berechnet",
        "unit": "Nm",
        "sim_min": 497.0,
        "sim_max": 503.0,
        "sim_noise": 1.0,
    },
    {
        "id": "torque_nm1",
        "name": "Moment NM1",
        "unit": "Nm",
        "sim_min": 470.0,
        "sim_max": 480.0,
        "sim_noise": 3.0,
    },
    {
        # Rohspannung NM1 (AI4) neben dem Moment – für den späteren Abgleich (Nutzer 27.10.2026).
        # Nur Kachel + Bericht, kein eigenes Diagramm (Fensterhöhe)
        "id": "torque_nm1_v",
        "name": "Spannung NM1",
        "unit": "V",
        "no_chart": True,
        "sim_min": 0.73,
        "sim_max": 0.75,
        "sim_noise": 0.005,
    },
    {
        # RPM1 = Drehzahlsensor im Getriebe (CNT0-Frequenz × RPM1_FACTOR, wie DAQ-Monitor).
        # Keine Live-Grenzwerte: bewertet wird am Ende des Lastlaufs die Abweichung des
        # Mittelwerts von MOTOR_RUN_RPM (RPM1_WARN_PCT / RPM1_CRITICAL_PCT)
        "id": "speed",
        "name": "Drehzahl RPM1",
        "unit": "RPM",
        "target_setting": "MOTOR_RUN_RPM",   # Soll-Linie im Diagramm
        "sim_min": 990.0,
        "sim_max": 1010.0,
        "sim_noise": 3.0,
    },
]

SENSOR_MAP = {s["id"]: s for s in SENSORS}

# Checkliste zu Beginn (Nutzer 30.09.2026)
PREPARE_CHECKLIST = [
    "Temperatursensor T1 mit Magnet am Getriebe",
    "Temperatursensor T2 mit Magnet am Getriebe",
    "Vibrationssensor mit Magnet am Getriebe",
    "Stecker Drehmomentsensor NM1 gesteckt",
    "Stecker Drehzahlsensor RPM1 gesteckt",
    "Leckage-Schlauch am Getriebe angeschlossen",
    "Haupthahn Druckluft auf mindestens 6 bar",
]

# Prüfablauf. "action" bestimmt, was core/test_runner.py im Schritt tut; "ids" sind die
# Sensoren, die live angezeigt und ins CSV geschrieben werden.
#   prepare  – Checkliste, dann Zylinder in Grundstellung (oben ein, unten aus)
#   leak     – Befüllen → Halten → Entlüften (hardware/leak_sequence.py), Druckabfall
#   run      – Motor mit MOTOR_RUN_RPM, Vibration/Temperatur live bewertet
#   bolt_in  – warten, bis der Sperrbolzen steckt (DI3)
#   torque   – oberer Zylinder aus → halten/messen → ein → unten entlasten
#   bolt_out – warten, bis der Sperrbolzen gezogen ist (DI3), dann unten aus
#   visual   – Sichtprüfung bestätigen
# Optional "ignore_di": Sicherheits-Eingänge, die in diesem Schritt nicht geprüft werden.
STEPS = [
    {
        "action": "prepare",
        "name": "Vorbereitung",
        "ids": [],
        "button": "Alles angeschlossen – Grundstellung anfahren",
        "instruction": (
            "Getriebe aufspannen und die Punkte rechts kurz prüfen.\n\n"
            "Danach fahren die Zylinder automatisch in die Grundstellung "
            "(oben ein, unten aus)."
        ),
    },
    {
        "action": "leak",
        "name": "Leckageprüfung",
        "ids": ["pressure"],
        "hold_seconds": STEP2_DURATION_SECONDS,
        "button": "Leckageprüfung starten",
        "instruction": (
            "Das Getriebe wird automatisch mit Druckluft befüllt, abgesperrt und der "
            "Druckabfall über die Haltezeit gemessen. Danach wird entlüftet.\n\n"
            "Motor steht. Nichts zu tun außer Starten."
        ),
    },
    {
        "action": "run",
        "name": "Lastlauf",
        "ids": ["vibration", "temperature", "temperature2", "speed"],
        "duration_seconds": STEP1_DURATION_MINUTES * 60,
        "button": "Lastlauf starten",
        "instruction": (
            "Der Motor läuft mit der eingestellten Drehzahl. Vibration, Temperaturen "
            "und Drehzahlsensor RPM1 werden live überwacht.\n\n"
            "Der Sperrbolzen muss gezogen sein. Schutzabdeckungen geschlossen?"
        ),
    },
    {
        "action": "bolt_in",
        "name": "Sperrbolzen einschieben",
        "ids": [],
        "button": "Weiter",
        "instruction": (
            "Motor steht.\n\n"
            "Bitte den Sperrbolzen am Abtrieb einschieben. Das Programm erkennt den "
            "Bolzen selbst (Induktiv-Sensor DI3)."
        ),
    },
    {
        "action": "torque",
        "name": "Kraftprüfung",
        "ids": ["torque", "pressure_cyl", "torque_nm1", "torque_nm1_v"],
        "hold_seconds": STEP3_DURATION_SECONDS,
        "button": "Kraftprüfung starten",
        "instruction": (
            "Der obere Zylinder drückt über den Hebel gegen das blockierte Getriebe, "
            "das Moment wird über die Haltezeit gemessen. Danach fährt er ein und der "
            "untere Zylinder entlastet das Getriebe."
        ),
    },
    {
        "action": "bolt_out",
        "name": "Sperrbolzen ziehen",
        "ids": [],
        # Motor muss hier nicht mehr am Getriebe befestigt sein (Nutzer 30.09.2026)
        "ignore_di": [1],
        "button": "Weiter – Grundstellung anfahren",
        "instruction": (
            "Das Getriebe ist entlastet.\n\n"
            "Bitte den Sperrbolzen ziehen. Danach fährt der untere Zylinder wieder "
            "aus (Grundstellung)."
        ),
    },
    {
        "action": "visual",
        "name": "Sichtprüfung",
        "ids": [],
        "button": "Sichtprüfung OK – Prüfung abschließen",
        "instruction": (
            "Bitte eine abschließende optische Prüfung des Getriebes durchführen.\n\n"
            "Auf sichtbare Schäden, Leckagen oder sonstige Auffälligkeiten prüfen."
        ),
    },
]


def step_by_action(action: str) -> dict:
    return next(s for s in STEPS if s["action"] == action)


MEASUREMENT_INTERVAL_MS = 100   # Abtastung für Live-Anzeige/Bewertung
CSV_INTERVAL_S = 1.0            # Abstand der Rohdaten-Zeilen im Bericht (Einstellungen, 0 = jeder Messwert)
CHART_MAX_POINTS = 200

APP_NAME = "Getriebeprüfstand"
APP_VERSION = "1.1.0"

# ── Motor über DAQ-Karte (Pinplan: AO0 = Drehzahl-Sollwert, DO0 = Motor on) ────────
# Frequenzumrichter Hitachi WJ-C1, analog angesteuert (NICHT Modbus, siehe TODO C3).
# Skalierung ist ANNAHME (0–10 V ≙ 0–50 Hz) – am Prüfstand mit FU-Anzeige abgleichen!
MOTOR_ON_DO_CHANNEL      = 0      # DO0 – Freq. Umw. Motor on
MOTOR_SPEED_AO_CHANNEL   = 0      # AO0 – Freq. Umw. Drehzahl
MOTOR_AO_MAX_V           = 10.0   # Sollwert-Spannung bei FU-Maximalfrequenz (TBD)
MOTOR_AO_MAX_HZ          = 50.0   # FU-Frequenz bei MOTOR_AO_MAX_V (TBD)
MOTOR_NOMINAL_RPM_AT_50HZ = 1500.0  # IE3-T3A 100 LX4, 4-polig
RPM1_FACTOR              = 3.5137 # RPM1 (CNT0): Drehzahl [RPM] = Frequenz [Hz] × Faktor, einstellbar im Grenzwerte-Dialog
                                  # (Nutzer 19.10.2026: 4.285 − 18 %, Anzeige war zu hoch; vorher 4.285 vom 30.09.2026)
# Lastlauf: Ø RPM1 gegen MOTOR_RUN_RPM, Abweichung in % (Einstellungen) – Platzhalter
RPM1_WARN_PCT     = 5.0
RPM1_CRITICAL_PCT = 10.0
# Ausreißer-Filter RPM1 (hardware/rpm_filter.py): CNT0 springt kurz auf Millionen Hz
RPM1_MAX_RPM       = 3000.0  # darüber unplausibel → verworfen (Motor 1500 rpm bei 50 Hz)
RPM1_JUMP_PCT      = 20.0    # Sprung gegenüber Median der letzten Werte → Ausreißer … (Nutzer 01.10.2026: ±20 % ist schon Ausreißer)
RPM1_JUMP_MIN_RPM  = 10.0    # … mindestens aber so viele rpm (nahe 0 rpm)
RPM1_JUMP_CONFIRM  = 20      # … außer der neue Wert hält so viele Messungen (≈ 2 s)
MOTOR_TEST_DEFAULT_V     = 2.0    # DAQ-Monitor: "entspannte" Testdrehzahl ≈ 300 RPM
MOTOR_TEST_MAX_V         = 4.0    # DAQ-Monitor: Obergrenze ≈ 600 RPM
MOTOR_RUN_RPM            = 1000.0 # Lastlauf (Nutzer 30.09.2026), einstellbar im Grenzwerte-Dialog
MOTOR_RAMP_S             = 5.0    # Hochlauf abwarten, bevor bewertet wird (FU-Rampe F202)
RUN_SETTLE_S             = 5.0    # Lastlauf: erste Sekunden der Messung nicht bewerten – RPM1 springt
                                  # dort kurz hoch (Nutzer 27.10.2026), einstellbar im Grenzwerte-Dialog

# ── Digitaleingänge / Sicherheit ──────────────────────────────────────────────
# Am Prüfstand im betriebsbereiten Zustand gemessen (Nutzer 24.09.2026). Gilt während der
# GANZEN Prüfung (Nutzer 30.09.2026); fällt eine Bedingung weg → sicher abfahren, Abbruch.
# DI7 = Not-Aus-Kreis, darin in Reihe der Schaltschrank-Türschalter (TODO B4).
# 0 = in Ordnung (low-aktiv; offene TTL-Eingänge lesen 1 → Drahtbruch = fail-safe).
SAFETY_REQUIRED_DI: dict[int, int] = {
    0: 0,   # Induktiv A
    1: 0,   # Induktiv B
    2: 0,   # Induktiv C
    4: 0,   # Induktiv E
    7: 0,   # Not-Aus-Kreis / Schaltschrank
}
# Sperrbolzen-Sensor (Induktiv D): arbeitet umgekehrt wie die anderen (Nutzer 30.09.2026).
# Gezogen = 1 (bestätigt: Motor lief im Monitor mit DI3 = 1), eingeschoben = 0 (abgeleitet,
# am Prüfstand bestätigen!).
BOLT_DI = 3
BOLT_OUT_VALUE = 1
# Steckt der Sperrbolzen, verschiebt er den Kraftbolzen → Induktiv A (DI0) liest 1
# (Nutzer 30.09.2026). Diese Eingänge werden dann nicht als Sicherheitsverletzung gewertet.
SAFETY_IGNORED_WHEN_BOLT_IN: set[int] = {0}
DI_LABELS: dict[int, str] = {
    0: "Induktiv A", 1: "Induktiv B", 2: "Induktiv C", 3: "Sperrbolzen (Induktiv D)",
    4: "Induktiv E", 7: "Not-Aus-Kreis / Schrank",
}
# Klartext für den Werker, wenn ein Eingang nicht wie verlangt geschaltet ist (Nutzer 10.10.2026).
# DI5/DI6 sind nicht angeschlossen. DI3 hängt vom Soll ab (BOLT_FAULT_TEXTS).
DI_FAULT_TEXTS: dict[int, str] = {
    0: "Blockierung des Getriebes ist nicht ganz draußen",
    1: "Motor ist nicht ganz im Getriebe drin",
    2: "Getriebe ist nicht richtig an den Prüfstand gepresst",
    4: "Getriebe ist nicht richtig an den Prüfstand gepresst",
    7: "Die Tür ist nicht geschlossen",
}
BOLT_FAULT_TEXTS: dict[str, str] = {
    "out": "Blockierung ist nicht ganz draußen",
    "in":  "Blockierung ist nicht ganz drin im Getriebe",
}
# Startfreigabe Motor = Sicherheit + Sperrbolzen gezogen (auch vom DAQ-Monitor genutzt)
MOTOR_START_REQUIRED_DI: dict[int, int] = {**SAFETY_REQUIRED_DI, BOLT_DI: BOLT_OUT_VALUE}

# ── Pneumatik-Ventile (USB-4711A Digitalausgänge) ─────────────────────────────
# Quelle: Pin-Portbelegung-DAC-advantech.pdf (Rev. 0, Phileas Schwarz, 11.09.2026).
# V1/V2 = Ventil 5/2 bistabil (2 Steuersignale je Ventil) → Zylinder oben / unten.
# V3/V4 = Ventil 3/2 (1 Steuersignal je Ventil) → Leckage-Prüfung.
# Benennung der signal_id entspricht exakt der Beschriftung im Pinplan.
VALVE_CHANNEL_MAP: dict[str, int] = {
    "V1_1": 1,   # DO1 – Ventil 1, oberer Zylinder AUSFAHREN
    "V1_2": 2,   # DO2 – Ventil 1, oberer Zylinder EINFAHREN
    "V2_3": 3,   # DO3 – Ventil 2, unterer Zylinder AUSFAHREN
    "V2_4": 4,   # DO4 – Ventil 2, unterer Zylinder EINFAHREN
    "V3_5": 5,   # DO5 – Ventil 3 (Leckage), Signal
    "V4_6": 6,   # DO6 – Ventil 4 (Leckage), Signal
}

# Zylinder am Drehmomenthebel (am Prüfstand ermittelt, Nutzer 30.09.2026):
# V1/V2 sind BISTABILE 5/2-Ventile – beide Signale 0 → Zylinder bleibt, wo er ist.
# Ausfahren und Einfahren desselben Zylinders nie gleichzeitig ansteuern.
CYLINDER_VALVES: dict[str, dict[str, str]] = {
    "oben":  {"extend": "V1_1", "retract": "V1_2"},   # Messzylinder (Drehmomentmessung)
    "unten": {"extend": "V2_3", "retract": "V2_4"},   # Vorspannung – hält Leerlauf von der Achse
}

# Ablauf laut Nutzer (30.09.2026):
#   Grundstellung: unten ausgefahren, oben eingefahren (auch während des Motorlaufs)
#   Messung:       Sperrbolzen rein → nur oben aus-/einfahren
#   Entlasten:     oben ein → unten ein (Getriebe entspannt) → Sperrbolzen raus → unten aus
CYLINDER_HOME: dict[str, str] = {"oben": "retract", "unten": "extend"}
CYLINDER_MOVE_S = 2.0   # Wartezeit nach einem Zylinder-Befehl (Hub fahren)

# Drehmoment aus Zylinderdruck (Nutzer gemessen, 30.09.2026; rechtwinklig angreifend):
#   M = p · π/4 · d² · r  →  ≈ 83,3 Nm/bar (6 bar ≙ 500 Nm). Kräfte der beiden Zylinder
#   addieren sich NICHT (in Reihe, siehe TODO B1) → Fläche EINES Zylinders.
#   Reibung (≈ 5–10 %) nicht berücksichtigt – Abgleich gegen NM1 steht aus.
CYLINDER_BORE_MM = 80.0
LEVER_ARM_MM     = 165.7846

# ── Kraftprüfung ──────────────────────────────────────────────────────────────
# Bewertet wird vorerst das aus DS1 berechnete Moment (Nutzer 30.09.2026); nach dem
# NM1-Abgleich auf "nm1" umstellbar.
TORQUE_SOURCE = "ds1"            # "ds1" | "nm1"
TORQUE_PASS_NM = 495.0           # bestanden ab (Soll 500 Nm, kleine Toleranz) – Grenzwerte-Dialog
TORQUE_SETTLE_S = 3.0            # nach dem Ausfahren warten, bevor gemittelt wird

# Sicherheit: DS1 darf während der ganzen Prüfung nie über 6 bar (+ Toleranz) gehen
# (Nutzer 01.10.2026) – sonst Sicherheitspause wie bei den Induktiv-Sensoren
CYL_MAX_PRESSURE_BAR = 6.0
CYL_PRESSURE_TOLERANCE_BAR = 0.1

# ── Leckage-Prüfablauf (hardware/leak_sequence.py) ────────────────────────────
# Schaltfolge laut Nutzer (28.09.2026), DO5/DO6:
#   Befüllen 1/1 → Halten 0/LEAK_HOLD_DO6 → Entlüften 1/0 → Fertig 0/0
# Halten = 0/1: nur DO5 aus schließt das System ab, DO6 bleibt an. Mit DO6 = 0 geht die
# Luft über das Ablassventil raus – Getriebe sofort drucklos (Nutzer 01.10.2026, auch
# nach dem Umstecken von V3).
# Der frühere Zwischenschritt „Entlüften 1“ (1/1) vor 1/0 hat nach dem Halten kurz Luft
# nachgefüllt und wurde entfernt (Nutzer 10.10.2026).
LEAK_HOLD_DO6 = 1
# Leckage-Druckregler steht auf 0,5 oder 1 bar (Nutzer 30.09.2026).
LEAK_FILL_S      = 10.0   # Phase Befüllen (DO5+DO6)
LEAK_HOLD_S      = 60.0   # DAQ-Monitor: Phase Halten (im Prüfablauf: STEP2_DURATION_SECONDS)
LEAK_VENT_STEP_S = 1.0    # Dauer Phase Entlüften (1/0), danach 0/0
LEAK_WARN_DROP_BAR     = 0.05   # Platzhalter – TBD vom Kunden (Grenzwerte-Dialog)
LEAK_CRITICAL_DROP_BAR = 0.1    # Platzhalter – TBD vom Kunden (Grenzwerte-Dialog)
LEAK_MIN_FILL_BAR      = 0.4    # darunter am Ende des Befüllens → „kein Prüfdruck“ (KRITISCH)
