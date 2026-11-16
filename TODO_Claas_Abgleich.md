# Abgleich Software ↔ Beschreibung_Pruefstand_STG189.docx

Stand: 14.09.2026. Quelle: `Beschreibung_Pruefstand_STG189.docx` (inkl. eingebetteter Bilder
"EOL-Test" und Temperaturverlauf-Diagramm unter Punkt 2 „Kundenanforderung Claas").

Status-Spalte bitte pflegen: `[ ]` offen · `[x]` erledigt · `[~]` bewusst anders gelöst (Begründung dahinter notieren)

---

## A) Prüfablauf (Punkt 8 im Dokument)

Soll-Reihenfolge laut Claas:
1. Leckage-Prüfung (5 min Druckabfall messen, Stillstand)
2. Drucklosschaltung
3. Lastfreier Prüflauf 15 min (Vibration/Temp/Drehzahl)
4. Sperrbolzen manuell einschieben
5. Kraftmessprüfung im Stillstand (Motor AUS)
6. Manuelle optische Prüfung (Bestätigung im Display)

- [x] **A1** – Reihenfolge der Schritte angepasst (14.09.2026): `STEPS` in
  `config/settings.py` ist jetzt `[Druck] → [Vibration/Temp/Drehzahl] → [Drehmoment]`.
  Reine Reihenfolgeänderung, keine neue Logik. `ui/start_dialog.py` Spinbox→STEPS-Zuordnung
  entsprechend angepasst.
- [x] **A2** – Druck-Schritt auf Druckabfall-Messung umgestellt (14.09.2026): Neues Flag
  `"leak_test": True` + Platzhalter-Grenzwerte `leak_warn_drop_bar`/`leak_critical_drop_bar`
  am Druck-Schritt in `config/settings.py`. `core/test_runner.py`: Live-Anzeige bleibt während
  der Messung neutral (Status immer „OK", wie mit Nutzer abgestimmt); erster/letzter Messwert
  werden mitgeschrieben, am Schrittende wird der Druckabfall über `evaluator.evaluate_drop()`
  (neu in `core/evaluator.py`) bewertet und als eigene Ergebniszeile „Leckage (Druckabfall)"
  eingetragen (ersetzt die bisherige Momentanwert-Zeile für diesen Schritt).
  **Mitgelöst:** Motor-Synchronisation vereinheitlicht (`_sync_motor()`-Helper) — Motor ist
  jetzt korrekt AUS während des Druck-Schritts und startet automatisch beim Übergang in den
  Vibration/Temp/Drehzahl-Schritt (vorher: Motor lief durchgehend ab Testbeginn, siehe A3).
  Dabei auch einen Bug in `resume_after_critical()` behoben: nach „Fortfahren" bei einem
  kritischen Wert während eines Stillstand-Schritts (z. B. Drehmoment) wurde der Motor bisher
  fälschlich wieder gestartet — startet jetzt nur noch, wenn der aktuelle Schritt
  `motor_running: True` hat. Getestet per Offline-Skript: Leckrate-Berechnung, Motor-Ablauf
  über alle 5 Schritte, und beide `resume_after_critical()`-Fälle (Stillstand vs. Normalbetrieb).
  Kein Eingriff in Pneumatik-Ansteuerung (C1/C2, weiterhin manuell durch Werker) oder
  CSV-Spaltenstruktur (D2 separat).
- [x] **A3** – Motor bei Kraftmessprüfung stoppen (14.09.2026): Drehmoment-Schritt in
  `config/settings.py` hat jetzt `"motor_running": False`; `core/test_runner.py →
  complete_step()` stoppt den Motor beim Übergang in einen Schritt mit diesem Flag, vor
  `step_changed.emit(...)`. Getestet per Offline-Skript (Simulation): Motor stoppt exakt
  beim Übergang in den Drehmoment-Schritt. Initialer Motorstart in `start_test()` bewusst
  unverändert gelassen (Motor läuft weiter während des Druck-Schritts) — das gehört zu A2.
- [x] **A4** – Schritt „Sperrbolzen einschieben" ergänzt (14.09.2026): Neuer STEPS-Eintrag
  in `config/settings.py` (`ids: []`, `manual: True`, `confirm_label`, `motor_running: False`)
  zwischen Vibration/Temp/Drehzahl und Drehmoment. `ui/step_widget.py` erkennt `manual`-Flag:
  eigener Button-Text, kein Timer/Fortschrittsbalken, Klick bestätigt sofort und schließt den
  Schritt ab (kein Messwert nötig). `core/test_runner.py → start_measurement()` loggt für
  Schritte ohne Sensoren „{Name} bestätigt." statt einer leeren Messwert-Liste.
  **Wichtig:** Der `motor_running: False`-Flag aus A3 wurde zusätzlich auf diesen Schritt
  gesetzt (nicht nur auf Drehmoment) — sonst wäre der Motor beim Einschieben des Sperrbolzens
  noch gelaufen. `ui/start_dialog.py`-Indexzuordnung für die Messzeiten-Spinboxen angepasst
  (Drehmoment ist jetzt Index 3 statt 2, wegen des neu eingefügten Schritts).
  Getestet per Offline-Skript (Simulation): korrekte Reihenfolge, Motor stoppt beim
  Sperrbolzen-Schritt, Button/Timer-Verhalten wie erwartet.
- [x] **A5** – Abschließenden Schritt „Sichtprüfung" ergänzt (14.09.2026): neuer STEPS-Eintrag
  am Ende von `config/settings.py` (`manual: True`, kein Sensor, `confirm_label`). Nutzt den
  in A4 gebauten generischen Mechanismus für manuelle Bestätigungsschritte — keine
  Codeänderung in `ui/step_widget.py`/`core/test_runner.py` nötig. Auf Wunsch des Nutzers
  **kein** eigenes Bestanden/Nicht-bestanden-Ergebnis (nur ein einzelner „OK"-Bestätigungs-
  Button, rein protokollarisch, kein Einfluss auf Gesamtergebnis). Getestet per
  Offline-Skript: alle 5 Schritte laufen durch, Test schließt normal mit BESTANDEN ab.

---

## B) Sensorik (Punkt 3 im Dokument)

- [ ] **B1** – Zweiten Drehmoment-/Kraftmesswert ergänzen: Dokument unterscheidet
  „Eingangsdrehmoment zur Lastprüfung" (kontinuierlich, während Lastlauf) und
  „Kraftmessbolzen" (Claas-Vorgabe, Stillstandsmessung, **eigene Seriennummer**).
  Aktuell existiert nur ein einzelner `torque`-Sensor in `config/settings.py`.
  **Update 14.09.2026 (bestätigt durch Claas-Rückfrage-Antwort):** Es gibt **keinen
  direkten Drehmomentsensor**. Gemessen wird nur Luftdruck; das Drehmoment wird rechnerisch
  abgeleitet: Das Getriebe wird am Abtrieb per Sperrbolzen fixiert (Stillstand), ein
  Pneumatikzylinder drückt über einen Hebelarm bekannter Länge dagegen:
  - F = p · A (Kraft = Druck × Kolbenfläche)
  - M = F · r (Drehmoment = Kraft × Hebelarmlänge)

  Beispielrechnung aus den Konstruktionsunterlagen (6 bar, ⌀80 mm Zylinder, Ziel 500 Nm):
  F = 6 bar × A(⌀80mm) ≈ 3015,9 N → nötiger Hebelarm r = 500 Nm / 3015,9 N ≈ 165,8 mm.

  Ventil-Zuordnung im Pneumatik-Schaltbild jetzt geklärt: **5/2-Ventile + Zylinder
  (50 mm/30 mm) → Drehmomentmessung/Kraftaufbringung**, **3/2-Ventile → Leckage-Prüfung**
  (bestätigt C2).

  **Noch offen (Rückfrage an den Konstrukteur, Tobias Klingler):** Die reale Anlage hat zwei
  Zylinder (⌀50 mm und ⌀30 mm), nicht den in der Beispielrechnung angenommenen ⌀80 mm. Unklar,
  welcher der beiden für die Kraft-/Drehmomentmessung zuständig ist und welcher nur der
  Kraftaufbringung dient — ohne diese Zuordnung plus den tatsächlichen Hebelarm r lässt sich
  die Umrechnungsformel in `hardware/real_hardware.py → SENSOR_SCALE` nicht mit echten
  Konstanten befüllen (aktuell TBD, siehe CLAUDE.md).
  **Geklärt:** Der Sperrbolzen (A4) wird weiterhin rein manuell eingeschoben, nicht
  pneumatisch — die Umsetzung in A4 als reiner Bestätigungsschritt bleibt also korrekt.
  **Update 14.09.2026 (aus `Pin-Portbelegung-DAC-advantech.pdf`):** Der zweite, bisher
  fehlende Messwert ist gefunden — Kanal **NM1 auf AI4** ist ein direktes Drehmoment-Signal
  **an der anderen (Eingangs-)Welle des Getriebes**, unabhängig vom Hebel/Kraftmessbolzen-
  Mechanismus. Das entspricht genau der im Claas-Dokument geforderten „Eingangsdrehmoment
  zur Lastprüfung" (kontinuierlich) — vermutlich ein regulärer Inline-Drehmomentsensor mit
  direktem Nm-Ausgang, keine Druck-Umrechnung nötig. Damit ergibt sich: `config/settings.py`
  braucht einen **zweiten Sensor-Eintrag** (z. B. `input_torque`) für NM1, zusätzlich zum
  bestehenden `torque` (Kraftmessbolzen, Hebel/Druck, Stillstand). ~~Noch offen: welcher der
  beiden `DS1`/`DS2`-Drucksensoren (AI2/AI3) zur Kraftmessbolzen-Berechnung gehört und welcher
  zur Leckage-Prüfung.~~
  **Geklärt 25.09.2026 (Nutzer, handgezeichnetes Schaltbild):** `DS1` = AI2 = oberer Strang
  (Zylinder/Hebel), `DS2` = AI3 = unterer Strang (Getriebe/Leckage). Die beiden Zylinder sitzen
  hintereinander und drücken in dieselbe Richtung auf den Drehmomenthebel.
  ~~ihre Kräfte addieren sich also (M = p · (A₁ + A₂) · r)~~ **Korrektur 30.09.2026:** Zwei
  eigenständige Zylinder in Reihe addieren nur den Hub, nicht die Kraft (am Hebel wirkt die
  Kraft des stärkeren). Addition nur bei Tandemzylinder (gemeinsame Kolbenstange) oder
  parallel angreifenden Zylindern – Bauart am Prüfstand noch bestätigen. Nutzer hat
  gemessen: Kolben ⌀80 mm, Hebelarm r = 165,78 mm, rechtwinklig → je Zylinder
  F = p · 5026,5 mm², M ≈ 83,3 Nm/bar (6 bar ≙ 500 Nm). **Code-Fix:**
  `SENSOR_CHANNEL_MAP["pressure"]` 2 → 3 (Leckage-Prüfung las vorher den Zylinderdruck).
  **Update 30.09.2026:** `torque` liest jetzt AI4 (NM1, Drehmomentsensor im Getriebe);
  `speed` hat keinen AI-Kanal mehr (kommt über Zähler, C3). Skalierung NM1 noch Platzhalter,
  Live-Abgleich gegen Zylinderkraft geplant.
  ~~**Offen:** `torque` liest vorerst ebenfalls AI3 (Platzhalter).~~ Ein eigener Eintrag für DS1
  plus Drehmoment-Berechnung fehlt noch (Kolbendurchmesser 50/30 mm bestätigen, Hebelarm r,
  fahren immer beide Zylinder aus?). Zylinder-Themen laut Nutzer vorerst zurückgestellt.
  ~~**Offen:** Ausgangssignal der Scaleo-Drucksensoren unbekannt.~~ **Geklärt 28.09.2026
  (Datenblatt, Symbol 995410):** Analogausgang 1–5 V ≙ 0–1,0 MPa (0–10 bar), Genauigkeit
  ±1,5 % FS, Wiederholgenauigkeit ±0,3 % FS. **Aber:** Messung am Prüfstand (0 bar ≈ 0,2 V,
  1,55 bar ≈ 1,52 V) passt nicht zu 1–5 V. **Abgleich DS2** (Referenz Sensor-Display):
  6 Punkte zwischen 1,04 und 1,53 bar → p = 0,9933·U + 0,0640 (Rest ≤ 0,003 bar, linear),
  `SENSOR_SCALE["pressure"]` = (-0.0645, 10.0032, 0, 10). Drucklos bleibt der Ausgang bei ≈ 0,136 V
  stehen (Anzeige ≈ 0,2 bar). Offen: Punkte < 1 bar und > 1,5 bar über Druckregler aufnehmen,
  DS1 separat abgleichen.
- [x] **B2** – Erledigt (14.09.2026, Nutzer hat realen Sensor getestet): Der eingesetzte
  Beschleunigungsaufnehmer ist zwar intern 3-achsig (X/Y/Z), verarbeitet die Rohdaten aber
  bereits selbst und liefert nach außen **einen einzigen, nutzbaren Gesamtwert**. Kein
  Software-Änderungsbedarf — der aktuelle skalare `vibration`-Wert in `config/settings.py`
  passt damit genau zur realen Sensorausgabe.
- [x] **B3** – Erledigt (14.09.2026): Drucksensor-Konfiguration in `config/settings.py` an
  Claas-Vorgabe (0,5–1 bar, Genauigkeit 0,02 bar) angepasst:
  `warn_low=0.55 / warn_high=0.95 / critical_low=0.5 / critical_high=1.0` (physische
  Sensorgrenzen als Plausibilitäts-Schwellen — weiterhin Platzhalter, echte Werte vom Kunden
  TBD), `sim_min=0.6 / sim_max=0.9 / sim_noise=0.02` (Simulation jetzt im echten Messbereich,
  Rauschen entspricht Datenblatt-Genauigkeit). Getestet: Simulationswerte liegen plausibel im
  0,5–1 bar-Fenster. Die separaten Leckrate-Grenzwerte aus A2
  (`leak_warn_drop_bar`/`leak_critical_drop_bar`) bleiben unverändert, da diese eine andere
  Größe (Druckabfall über Zeit, nicht Absolutwert) betreffen.
- [x] **B4** – Beantwortet (14.09.2026) aus `Pin-Portbelegung-DAC-advantech.pdf`
  (Revision 0, Phileas Schwarz, 11.09.2026 — **dieses Dokument ist aktuell, CLAUDE.md zur
  Motoransteuerung ist es nicht mehr, siehe C3**). Reale Kanalbelegung der USB-4711A:
  - Analog-Eingänge: T1(AI0), T2(AI1), DS1(AI2), DS2(AI3), NM1(AI4), Vibrationssensor(AI7)
    belegt — **AI5, AI6, AI8–AI15 frei (10 Kanäle Reserve)**.
  - Digital-Ausgänge: DO0=Freq.Umw. Motor on, DO1–DO6=Ventile V1–V4 belegt —
    **DO7 frei (1 Kanal)**.
  - Digital-Eingänge: DI0–DI4=Induktiv A–E, DI7=Not-Aus Kreis belegt —
    **DI5, DI6 frei (2 Kanäle)**.
  - Analog-Ausgänge: AO0=Freq.Umw. Drehzahl belegt — **AO1 frei (1 Kanal)**.

  Fazit: bei den digitalen Kanälen weniger Reserve als die im Claas-Dokument gewünschten
  4×/4×, bei analogen Eingängen deutlich mehr als genug. Software-seitige Reserve-I/O-
  Struktur in `hardware/base.py` (generische read/write-Methoden für freie Kanäle) ist noch
  nicht umgesetzt — separat zu entscheiden, ob das jetzt schon gebraucht wird oder erst bei
  konkretem Bedarf.
  **Rückfrage geklärt (18.09.2026):** Der Schaltschrank-Türschalter hängt NICHT an einem
  eigenen AI-Kanal, sondern ist in Reihe im **Not-Aus-Kreis** verdrahtet – also derselbe
  Signalpfad wie `DI7 = Not-Aus Kreis` (siehe Kanalbelegung oben). AI5 bleibt tatsächlich frei/
  unbenutzt für diesen Zweck.
  **Software-Konsequenz:** `hardware/real_hardware.py → read_cabinet_switch()` liest aktuell
  einen analogen Spannungswert mit Hysterese-Schwellen (`CABINET_SWITCH_CHANNEL`,
  `CABINET_SWITCH_LOW_V`/`HIGH_V`) – das ist mit dieser Information hinfällig, da es sich um
  ein digitales Signal (DI7) handelt, nicht um einen analogen Kanal. Es existiert aktuell noch
  **keine** generische Digital-Input-Lese-Funktion in `hardware/real_hardware.py`/`base.py`
  (betrifft auch die 5 Induktiv-Sensoren DI0–DI4, siehe Reserve-I/O-Hinweis oben) – muss neu
  implementiert werden: `_di_ctrl`/`readBit(7)`-Analogon zu `_read_channel()`, plus Anpassung
  von `config/settings.py` (`CABINET_SWITCH_CHANNEL` → DI-Kanal statt AI-Kanal,
  Hysterese-Schwellen entfallen). Fail-Safe-Verhalten (keine Verbindung/Lesefehler → Schrank
  gilt als offen) muss bei der Umstellung erhalten bleiben.
  **Umgesetzt 30.09.2026:** `read_cabinet_switch()`/`CABINET_*` entfernt. Neu `read_di()` in
  `hardware/base.py`/`real_hardware.py`; Schrank + Not-Aus = DI7 in `SAFETY_REQUIRED_DI`,
  geprüft von `hardware/safety.py → di_violations()` alle 200 ms im Prüfablauf. Fail-safe:
  DI nicht lesbar → Abbruch.

---

## C) Aktorik / Ansteuerung (Punkt 4 im Dokument)

- [~] **C1** – Pneumatik-Zylinder (Krafthebel) für Kraftaufbringung ansteuerbar machen.
  Pneumatik-Schaltbild eines Mitarbeiters liegt vor (nicht im Repo, vom Nutzer als Bild
  geteilt). Oberer Strang: Wartungseinheit → Druckregler → Drucksensor (Scaleo) → 2× Ventil
  5/2 (Festo VUVS-L25-B52-D-G14-F8-1C1 + KMEB-1-24-5-LED) → je ein Zylinder (50 mm / 30 mm).
  Siehe auch B1 — einer der beiden Zylinder hängt vermutlich mit der Drehmomentmessung über
  einen Hebelarm zusammen, nicht nur mit der Kraftaufbringung; noch zu klären, welcher.
  **Rohsignal-Ebene umgesetzt (14.09.2026):** `hardware/base.py → set_valve_signal(signal_id,
  energized)` neu (abstrakt), `hardware/simulation.py` implementiert es mit Logging,
  `hardware/real_hardware.py` mit einem DAQNavi-`InstantDoCtrl`/`writeBit()`-Ansatz (**⚠
  ungetestet, SDK-Methode gegen echte DAQNavi-Version verifizieren** — Windows-only, hier
  nicht testbar). Kanalzuordnung in `config/settings.py → VALVE_CHANNEL_MAP`
  (V1_1=DO1, V1_2=DO2, V2_3=DO3, V2_4=DO4, V3_5=DO5, V4_6=DO6, aus `Pin-Portbelegung-DAC-
  advantech.pdf`). Bewusst auf Rohsignal-Ebene gehalten (nur einzelne Signale schalten),
  **keine** semantischen Methoden wie „Zylinder ausfahren" — das erfordert erst die Klärung
  mit Tobias Klingler, welcher Zylinder/welches Ventil wofür zuständig ist (siehe B1). Per
  Offline-Skript in Simulation getestet.
  **Update 30.09.2026:** DO1–DO4 im DAQ-Monitor einzeln schaltbar (orange Knöpfe), um die
  Zuordnung Signal → Zylinder/Richtung am Prüfstand zu ermitteln. Nur bei stehendem Motor,
  Motorstart gesperrt solange DO1–DO4 ≠ 0, Schließen setzt alles auf 0.
  **Ermittelt (Nutzer, 30.09.2026):** DO1 = oberer Zylinder ausfahren, DO2 = oberer einfahren,
  DO3 = unterer ausfahren, DO4 = unterer einfahren. Ventile **bistabil**: beide Signale 0 →
  Zylinder bleibt in seiner Position. Hinterlegt in `config/settings.py → CYLINDER_VALVES`;
  Monitor schaltet beim Einschalten einer Spule die Gegenspule vorher ab.
  ~~Offen: welcher Zylinder (oben/unten) hat ⌀50 bzw. ⌀30 mm, Hebelarm r.~~ Gemessen: ⌀80 mm,
  r = 165,78 mm (siehe B1). **DS1 abgeglichen** (4 Punkte 0,72–3,03 bar, eigener Eintrag
  `SENSOR_SCALE["pressure_cyl"]`). DAQ-Monitor: Abschnitt „Druck & Kraft“ mit M rechnerisch
  (DS1) vs. NM1 (AI4).
  **Ablauf laut Nutzer (30.09.2026):** Ein Zylinder hat genug Hub (6 bar gegen blockiertes
  Getriebe ≈ 3 von 5 cm). Grundstellung = **unten ausgefahren** (hält den Leerlauf von der Achse
  fern, auch bei laufendem Motor), oben eingefahren. Messung: Sperrbolzen rein → nur **oben**
  aus/ein. Entlasten: oben ein → unten ein → Sperrbolzen raus → unten wieder aus.
  `config/settings.py → CYLINDER_HOME`. Im Monitor erzwungen (`_cylinder_violation`), Abfragen
  „Sperrbolzen eingeschoben?/gezogen?“; Motorstart nur in Grundstellung (DO1=0, DO2=1, DO3=1,
  DO4=0). Einzelknöpfe DO1–DO4 in der DO-Tabelle entfernt.
  ~~Integration in den Prüfablauf~~ **Umgesetzt 30.09.2026** (siehe G).
  **Offen:** NM1-Skalierung per Abgleich gegen M rechnerisch, danach `TORQUE_SOURCE = "nm1"`.
- [~] **C2** – Druckluftventil für Leckage-Prüfung ansteuerbar machen.
  Laut selbem Schaltbild, unterer Strang: Druckregler → 2× Ventil 3/2 (Festo VUVS-L20-M32C-
  AD-G18-F7-1C1, beim zweiten Ventil Anschluss 3 verschlossen/verklebt) → Drucksensor
  (Scaleo) → M16x1,5-Verschraubung ins Getriebe. Das ist vermutlich der physische Aufbau
  hinter der in A2 implementierten Druckabfall-Logik. **Rohsignal-Ebene mit erledigt** (siehe
  C1-Update, DO5/DO6 über dieselbe `set_valve_signal()`-Methode ansteuerbar) — die eigentliche
  Verknüpfung mit dem Prüfablauf (z. B. automatisches Öffnen/Schließen zur richtigen Zeit im
  Leckage-Test) ist noch **nicht** angebunden, da die Reihenfolge/Timing dafür noch nicht
  spezifiziert wurde.
  **Update 25.09.2026:** Reihenfolge im Strang laut Nutzer: Regler → V4 (DO6) → V3 (DO5) →
  DS2 → Getriebe. Vermutetes Prinzip „Block and Bleed“: V4 = Befüllen/Entlüften (normales
  3/2), V3 = reines Absperren (Anschluss 3 verschlossen). Befüllen: V4+V3 an. Halten/Messen:
  beide aus (Getriebe abgeschlossen, Zwischenraum über V4 entlüftet). Drucklos: nur V3 an.
  **Annahme** (Ventile NC, V3 ist das Ventil mit verschlossenem Anschluss), am Ventil prüfen.
  V3/V4 sind jetzt im Debug-Monitor (`ui/debug_daq_monitor.py`) per Knopf schaltbar, DS1/DS2
  werden dort in bar angezeigt. Beim Schließen des Monitors gehen DO5/DO6 auf 0.
  Zylinder-Ventile V1/V2 bleiben dort bewusst gesperrt.
  **Umgesetzt 30.09.2026:** Leckage im Prüfablauf vollautomatisch (Befüllen → Halten →
  Entlüften über `hardware/leak_sequence.py`), zusätzlich Mindest-Befülldruck
  `LEAK_MIN_FILL_BAR` (0,4 bar) gegen „Schlauch nicht angeschlossen“. Siehe G.
  **01.10.2026:** Halten 0/0 ausprobiert (Ziel: Leitung V4–V3 ohne Zuluft) – entlüftet das
  Getriebe sofort nach dem Befüllen → zurück auf **0/1**. Offen: Mit 0/1 bläst ein gezogener
  Schlauch zwischen V4 und V3 weiter (V4 speist nach), die Leitung V4–V3 wird so nicht auf
  Dichtheit geprüft – ggf. mit Pneumatik-Planer klären.
  **Umbau 01.10.2026 (Nutzer):** V3 umgesteckt auf I = Getriebe/DS2, II = von V4, III = Schraube
  → Halten jetzt 0/0 (`config/settings.py → LEAK_HOLD_DO6 = 0`, bei alter Belegung 1). DAQ-Monitor
  entlüftet beim Schließen zusätzlich, wenn DS2 > 0,35 bar zeigt.
  **Kundenrückmeldung 16.11.2026:** (1) Druck fällt in den ersten 2–3 s nach dem Befüllen um
  0,1–0,15 bar → neue Phase „Beruhigen“ (`LEAK_SETTLE_S`, 5 s) zwischen Befüllen und Halten,
  Startdruck erst danach. (2) Getriebe blieb nach der Prüfung unter Druck (Verschlusskappen
  flogen im Lastlauf weg) → Entlüften 5 s statt 1 s (`LEAK_VENT_STEP_S`), beide Zeiten im
  Einstellungsdialog. Nach dem Entlüften steht der DS2-Wert im Protokoll (drucklos ≈ 0,2 bar).
  **Offen:** Ob 1/0 physisch entlüftet, ist am Prüfstand nicht bestätigt – die Angaben oben
  (Halten 0/0) und in `config/settings.py` (`LEAK_HOLD_DO6 = 1`) widersprechen sich. Fällt DS2
  nicht ab: im DAQ-Monitor 1/0 und 0/0 gegen DS2 testen, Mindest-Schaltdruck der Ventile prüfen.
  Außerdem `CYL_MAX_PRESSURE_BAR` 6,0 → 6,5 bar ohne Toleranz (Kraftprüfung brach bei knapp 6 bar ab).
- [ ] **C3** – Motordrehzahlregelung: Claas fordert „FU-geregelt (±20 rpm)" — d.h.
  geschlossene Regelschleife mit Drehzahl-Istwert-Rückführung, nicht nur feste
  Sollfrequenz. Aktuell sendet `test_runner.py` nur `FU_TARGET_FREQ_HZ = 50.0 Hz` ohne
  Rückführung (`config/settings.py`).
  **⚠ Update 14.09.2026 — WICHTIGE ARCHITEKTUR-KORREKTUR:** `Pin-Portbelegung-DAC-
  advantech.pdf` (aktuell, 11.09.2026) zeigt `AO0` = „Freq. Umw. Drehzahl" (analoger
  Sollwert an den FU) und `DO0` = „Freq. Umw. Motor on" (digitales Start-Signal). Vom
  Nutzer bestätigt: **Die Motoransteuerung läuft real über die DAQ-Karte (Analog-/
  Digital-I/O), nicht über Modbus RTU/RS485.** Der komplette Modbus-Ansatz in
  `hardware/motor_controller.py` sowie die entsprechende Beschreibung in CLAUDE.md
  (Abschnitt „Antrieb: Motor & Frequenzumrichter") sind damit **veraltet** und müssen
  überarbeitet werden — `hardware/real_hardware.py` müsste den Motor stattdessen über
  DAQ-Analogausgang (Sollwert, vermutlich 0–10V → 0–50Hz o.ä., Skalierung TBD) und
  Digitalausgang (Start/Stopp) ansteuern. `FU_SERIAL_PORT`/`FU_BAUDRATE`/
  `FU_SLAVE_ADDRESS` in `config/settings.py` sowie die Modbus-Register-Konstanten sind
  damit obsolet. Zusätzlich deutet ein `RPM1`-Hinweis am Zähler-/Trigger-Bereich der
  DAQ-Karte (`EXT_TRG`/`EVT_IN`) darauf hin, dass die Drehzahl-Istwert-Rückführung für die
  geforderte Regelung über einen Pulszähler-Eingang erfolgt, nicht über einen einfachen
  Analogwert — ebenfalls noch zu verifizieren.
  **Noch nicht umgesetzt** — nur dokumentiert, da Umfang und genaue Skalierungswerte noch
  zu klären sind, bevor `hardware/real_hardware.py`/`motor_controller.py` umgebaut werden.
  **Update 30.09.2026:** Ansteuerung umgebaut – `real_hardware.py` steuert den FU über AO0/DO0
  (wie im DAQ-Monitor erprobt), Modbus/`motor_controller.py`/`FU_*` werden nicht mehr benutzt.
  Lastlauf mit `MOTOR_RUN_RPM = 1000` (Grenzwerte-Dialog). **Offen:** Skala AO0 → rpm
  (Annahme 0–10 V ≙ 0–50 Hz, 1000 rpm ≈ 6,7 V) am Prüfstand gegen FU-Anzeige prüfen;
  geschlossene Regelung ±20 rpm braucht RPM1 (Zähler, noch nicht in Betrieb).
- [ ] **C4** – Zieldrehzahl klären: Bild „EOL-Test" nennt „Input speed: 1110 rpm",
  aktuell ausgelegt auf 50 Hz → 1500 RPM (Motor-Nenndrehzahl). Zusammenhang zur
  Getriebeübersetzung mit Kunde/Mechanik klären.
- [ ] **C5** – Prüfzyklus frei programmierbar (Dauer, Drehzahl, Rampe). Aktuell sind
  Dauer und Grenzwerte über `GrenzwerteDialog` einstellbar — Drehzahl/Rampe bisher nicht.

---

## D) Ausgabe / Datenhaltung (Punkt 5 im Dokument)

- [x] **D1** – Entschieden (14.09.2026, Nutzer): **Keine Datenbank.** Zielsystem ist ein
  Windows-PC mit Standardinstallation + der Prüfstand-Software, sonst nichts. Bewusst
  einfache Lösung: Das Programm legt einen Ordner an und speichert dort die Prüfberichte
  (bereits der Fall — `OUTPUT_DIR` in `config/settings.py`, CSV pro Prüfung). Anbindung ans
  Firmennetzwerk/Freigabe ist explizit **nicht** Aufgabe der Software, sondern Sache der
  IT/Netzwerk-Infrastruktur beim Kunden. Damit weicht die Umsetzung bewusst von der
  „Speicherung in Datenbank"-Vorgabe im Claas-Dokument ab.
- [x] **D2** – Erledigt (14.09.2026): Fehlende Stammdaten-Felder ergänzt.
  `ui/start_dialog.py`: neue optionale Eingabefelder Getriebetyp, Getriebeseriennummer,
  Seriennummer Kraftmessbolzen, Kommentar/Bemerkung (analog zu Auftragsnummer — optional,
  nicht Pflicht wie Prüfer/Prüfnummer; werden bewusst **nicht** aus der letzten Sitzung
  vorausgefüllt, damit z. B. keine alte Seriennummer versehentlich übernommen wird).
  Durchgereicht durch die komplette Kette: `main.py` → `ui/main_window.py` →
  `core/test_runner.py → start_test()` → `core/csv_writer.py → open()`, dort als vier
  zusätzliche Header-Zeilen im CSV-Prüfbericht. Getestet: StartDialog-Properties, End-to-End
  bis zum geschriebenen CSV-Header (inkl. Umlaute) — beides korrekt.

---

## E) Konstruktive Sicherheitsthemen (Punkt 6 im Dokument)

- [ ] **E1** – „Abfrage der Befestigung über Sensoren" — Aufspann-/Kopplungsüberwachung.
  Aktuell ist nur der Schaltschrank-Sicherheitsschalter (`CABINET_SWITCH_*` in
  `config/settings.py`) implementiert, keine Sensorik für Getriebe-/Antriebs-Befestigung.
  **Update 14.09.2026:** `Pin-Portbelegung-DAC-advantech.pdf` zeigt 5 digitale Eingänge
  „Induktiv A–E" (DI0–DI4) — das könnten genau diese Befestigungs-/Positionssensoren sein
  (induktive Näherungsschalter für Aufspannung/Kopplung/Zylinder-Endlagen). Noch zu klären,
  welcher Induktiv-Sensor welche Funktion/Position genau überwacht — **Nutzer weiß es noch
  nicht, muss nachfragen (siehe offene Rückfragen unten).**
  **Verhalten geklärt:** Soll wie der Schaltschrank-Schalter **blockierend** funktionieren
  (`core/test_runner.py → _check_cabinet`-Muster: verhindert Teststart bzw. bricht
  laufenden Test ab), sobald die Sensor-Zuordnung feststeht — nicht nur informativ.
  Blockiert bis zur Rückfrage-Antwort, da ohne Kanal-Bedeutung nichts sinnvoll verdrahtet
  werden kann.
  **Update 24.09.2026 (Angabe Nutzer):** Startbedingung für den Motor ist bekannt:
  DI0=0, DI1=0, DI2=0, DI3=1, DI4=0 (vom Nutzer im betriebsbereiten Zustand am Prüfstand
  bestätigt; erste mündliche Angabe 1/0/1/0/1 war falsch), zusätzlich DI7=0 (Not-Aus-Kreis
  in Ordnung = **0**, low-aktiv — vom Nutzer bestätigt; wichtig auch für die Schaltschrank-
  Abfrage aus B4, die über denselben Kreis läuft). Hinterlegt in `config/settings.py → MOTOR_START_REQUIRED_DI`. Im
  DEBUG-Monitor (`ui/debug_daq_monitor.py`) bereits umgesetzt: Start gesperrt + sofortiger
  Stopp bei Wegfall. **Noch offen:** gleiche Sperre im Hauptprogramm
  (`core/test_runner.py`, `_check_cabinet`-Muster) — braucht erst eine DI-Lesefunktion in
  `hardware/real_hardware.py` (siehe B4). Welcher Sensor physisch was überwacht, ist
  weiterhin unbekannt, für die Logik aber nicht nötig.
  **Umgesetzt 30.09.2026:** DI3 (Induktiv D) = **Sperrbolzen** (Nutzer: arbeitet umgekehrt;
  gezogen = 1, eingeschoben = 0 – „eingeschoben = 0“ am Prüfstand bestätigen). Im Prüfablauf
  gilt DI0/1/2/4 = 0 und DI7 = 0 während der **ganzen** Prüfung (Nutzer), DI3 je Schritt
  (Motorlauf: gezogen, Kraftprüfung: eingeschoben). Bolzen-Schritte warten auf DI3.

---

## F) Grenzwerte — dringender Datenabgleich nötig

- [ ] **F1** – Temperatur-Grenzwerte gegen reale Messdaten prüfen. Das Diagramm im
  Dokument zeigt reale Betriebstemperaturen bis **~85 °C** im Normalbetrieb — aktueller
  `critical_threshold = 75.0 °C` in `config/settings.py` ist ein Platzhalter und würde
  bei solchen Werten ständig auslösen. Mit Kunde/Messdaten abgleichen, bevor reale
  Tests laufen.
  **Update 30.09.2026 (Nutzer):** Standard jetzt Warnung 90 °C / kritisch 100 °C, einstellbar.
- [ ] **F2** – Alle übrigen Grenzwerte (Vibration, Druck, Drehmoment, Drehzahl) sind
  laut CLAUDE.md ebenfalls Platzhalter — noch keine Kundenfreigabe.

---

## G) Prüfablauf im Hauptprogramm (umgesetzt 30.09.2026)

`python main.py` arbeitet jetzt **immer mit der echten USB-4711A** (ohne Karte Fehlermeldung,
keine Prüfung); `python main.py --sim` nur für Entwicklertests. Jeder Schritt per Klick,
Automatik innerhalb des Schritts, große „Jetzt: …“-Zeile, Startknopf nur aktiv, wenn die
Voraussetzung erfüllt ist (Grund steht darunter).

1. Vorbereitung – Checkliste (T1/T2/Vibration Magnet, Stecker NM1/RPM1, Leckage-Schlauch,
   Haupthahn ≥ 6 bar), dann automatisch Grundstellung (oben ein, unten aus)
2. Leckage – Befüllen → Halten („Leckage – Haltezeit“) → Entlüften, Druckabfall + Mindest-Befülldruck
3. Lastlauf – Motor 1000 rpm, T1/T2/Vibration live, kritischer Dialog wie bisher
4. Sperrbolzen einschieben – „Weiter“ erst bei DI3 = eingeschoben
5. Kraftprüfung – DS1 < 5,9 bar → Warnung (fortfahren möglich), oben aus → 3 s → Haltezeit
   mitteln → oben ein → unten entlasten; bestanden ab Ø 495 Nm (aus DS1, `TORQUE_SOURCE`)
6. Sperrbolzen ziehen – „Weiter“ erst bei DI3 = gezogen, dann unten aus (Grundstellung)
7. Sichtprüfung

**Sicherheitspause (Nutzerwunsch 30.09.2026):** Fehlt eine DI-Bedingung (Induktiv A–E,
Not-Aus-Kreis/Schrank, Sperrbolzen passend zum Schritt), wird die Prüfung NICHT mehr
abgebrochen: ein laufender Schritt wird sicher unterbrochen (wie unten), ein Hinweisfeld
zeigt live, was fehlt, „⟳ Erneut prüfen“ macht an derselben Stelle weiter (unterbrochener
Schritt startet neu), Eingaben/Ergebnisse bleiben erhalten. Gilt auch beim Start. Hinweis
zur Unterbrechung landet im CSV.

Abbruch (NOT-AUS-Knopf, kritischer Wert, Fenster schließen) fährt sicher ab: Motor
aus, Leckage entlüften, oberen Zylinder einfahren, unteren stehen lassen. Ergebnisseite mit
„Neue Prüfung“ / „Programm beenden“. CSV: Spalten T1, T2, Vibration, DS2, DS1, M berechnet,
M NM1, Drehzahl + Ergebniszeile je Schritt am Ende. Gemeinsame Logik mit dem DAQ-Monitor:
`hardware/cylinder_sequence.py`, `hardware/safety.py`, `hardware/leak_sequence.py`.
Getestet in Simulation (4 Szenarien: bestanden, NOT-AUS in Kraftprüfung, Druckwarnung,
Not-Aus-Kreis offen) und Render-Test auf dem Laptop-Bildschirm. **Am Prüfstand noch zu
testen:** kompletter Lauf, AO0-Skala, DI3 = 0 bei eingeschobenem Bolzen.

---

## Offene Rückfragen an Claas / intern zu klären

- Genauer Zusammenhang Motordrehzahl (1500 RPM Nenn) ↔ geforderte 1110 RPM Prüfdrehzahl
  ↔ 127 RPM Output (Getriebeübersetzung?)
- Schleppmoment max. 20 Nm — noch ungeprüft/geschätzt, Info steht laut Dokument noch aus
- Datenblatt Kraftmessbolzen — laut Dokument "folgt"
- Datenblatt Drehzahlsensor (Claas-Vorgabe) — laut Dokument "folgt"
- Welche Punkte wurden bewusst anders gelöst als im Dokument beschrieben? (Bitte oben je
  Punkt mit `[~]` markieren und kurz begründen, dann als Referenz für spätere Reviews.)
- ~~Ist der „Drucksensor Scaleo" derselbe Sensor, der das Drehmoment liefert?~~ **Erledigt
  14.09.2026:** Es gibt keinen direkten Drehmomentsensor, Drehmoment wird aus dem Druck am
  Hebel-/Zylinder-Mechanismus errechnet (F = p·A, M = F·r) — von Claas ausdrücklich so
  vorgegeben. Siehe B1.
- **Offen — an Tobias Klingler (Konstrukteur):** Welcher der beiden real verbauten Zylinder
  (⌀50 mm / ⌀30 mm) ist für die Kraft-/Drehmomentmessung zuständig (Gegenstück zum Hebelarm)
  und welcher dient nur der Kraftaufbringung? Zusätzlich wird der tatsächliche Hebelarm r
  benötigt, um `hardware/real_hardware.py → SENSOR_SCALE` mit echten Werten zu befüllen
  (Beispielrechnung in den Unterlagen ging von ⌀80 mm aus, das passt zu keinem der beiden
  realen Zylinder).
- **Neu 14.09.2026, an den Ersteller des Pinplans (Phileas Schwarz) bzw. Elektroplaner:**
  Wo sitzt der Schaltschrank-Sicherheitsschalter wirklich? `config/settings.py →
  CABINET_SWITCH_CHANNEL = 5` nimmt AI5 (analog) an, aber `Pin-Portbelegung-DAC-
  advantech.pdf` zeigt AI5 als unbeschriftet/frei — kein erkennbarer „Schrank"-Kanal.
  Siehe B4.
- ~~Welcher der beiden `DS1`/`DS2`-Drucksensoren (AI2/AI3) gehört zur Kraftmessbolzen-
  Berechnung (Hebel/Zylinder) und welcher zur Leckage-Prüfung?~~ **Erledigt 25.09.2026:**
  DS1 (AI2) = Zylinder, DS2 (AI3) = Leckage. Siehe B1.
- **Wichtig, an den Elektro-/Steuerungsplaner:** Motoransteuerung läuft laut aktuellem
  Pinplan über die DAQ-Karte (AO0 Sollwert, DO0 Start), nicht über Modbus RTU wie in
  CLAUDE.md beschrieben. Genaue Skalierung des Analog-Sollwerts (z. B. 0–10V → 0–50Hz?)
  und ob die Drehzahl-Istwert-Rückführung über einen Pulszähler-Eingang läuft, muss geklärt
  werden, bevor `hardware/real_hardware.py`/`motor_controller.py` umgebaut werden. Siehe C3.
  **CLAUDE.md muss in diesem Abschnitt aktualisiert werden, sobald das geklärt ist.**
- **Neu 14.09.2026, an Konstrukteur/Elektroplaner:** Wofür stehen die 5 Induktiv-Sensoren
  A–E (DI0–DI4) einzeln (Getriebe-Aufspannung? Antriebskopplung? Sperrbolzen-Position?
  Zylinder-Endlagen?) — Nutzer weiß es noch nicht. Siehe E1. Sobald geklärt: Sicherheitslogik
  soll blockierend funktionieren (analog Schaltschrank-Schalter, `_check_cabinet`-Muster).
