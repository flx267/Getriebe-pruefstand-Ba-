"""Prüfbericht als Excel-Datei (.xlsx).

Während der Prüfung werden die Rohdaten laufend in eine CSV-Zwischendatei geschrieben
(geht bei einem Absturz nicht verloren). Beim Abschließen wird daraus die Excel-Datei
erzeugt – Blatt „Prüfbericht“ (Kopfdaten, Ergebnisse, Hinweise) und Blatt „Rohdaten“ –
und die Zwischendatei gelöscht. Klappt das nicht, bleibt die CSV-Datei als Bericht stehen.
"""

import csv
import re
from datetime import datetime
from pathlib import Path

import config.settings as _settings
from config.settings import OUTPUT_DIR, APP_VERSION, SAVE_CSV

# (Spalte, sensor_id)
_COLUMNS = [
    ("T1_C", "temperature"),
    ("T2_C", "temperature2"),
    ("Vibration_mm_s", "vibration"),
    ("Druck_DS2_bar", "pressure"),
    ("Druck_DS1_bar", "pressure_cyl"),
    ("M_berechnet_Nm", "torque"),
    ("M_NM1_Nm", "torque_nm1"),
    ("U_NM1_V", "torque_nm1_v"),
    ("Drehzahl_RPM", "speed"),
]

_TS_FORMAT = "%Y-%m-%d %H:%M:%S.%f"
_STATUS_FILL = {"OK": "C6EFCE", "WARNUNG": "FFEB9C", "KRITISCH": "FFC7CE"}


def _safe_name(text: str) -> str:
    """Eingabe für den Dateinamen: unter Windows verbotene Zeichen (/ \\ : * ? " < > |)
    und Leerzeichen durch '-' ersetzen."""
    return re.sub(r'[\\/:*?"<>|\s]+', "-", text.strip())


def _current_settings() -> list[tuple]:
    """Werte aus dem Einstellungen-Dialog, wie sie für diesen Durchlauf gelten
    (stehen nach apply_grenzwerte_to_settings() in config.settings)."""
    from ui.settings_dialog import _CSV_ROWS, _PARAM_ROWS, _SENSOR_ROWS

    rows: list[tuple] = []
    sensors = {s["id"]: s for s in _settings.SENSORS}
    for sid, display, unit in _SENSOR_ROWS:
        if sid in sensors:
            rows.append(("Sensoren", f"{display} – Warnung", sensors[sid]["warn_threshold"], unit))
            rows.append(("Sensoren", f"{display} – Kritisch", sensors[sid]["critical_threshold"], unit))
    for section, defs in (("Prüfparameter", _PARAM_ROWS), ("Prüfbericht", _CSV_ROWS)):
        for key, display, unit, decimals in defs:
            value = round(getattr(_settings, key), decimals)
            rows.append((section, display, int(value) if decimals == 0 else value, unit))
    rows += [
        ("Messzeit-Maximum", "Lastlauf", _settings.MAX_STEP1_DURATION_MINUTES, "min"),
        ("Messzeit-Maximum", "Leckage – Haltezeit", _settings.MAX_STEP2_DURATION_SECONDS, "s"),
        ("Messzeit-Maximum", "Kraftprüfung – Haltezeit", _settings.MAX_STEP3_DURATION_SECONDS, "s"),
    ]
    return rows


class ReportWriter:

    def __init__(self):
        self._file = None
        self._writer = None
        self._path: Path = None
        self._raw_path: Path = None
        self._header: list[tuple[str, str]] = []
        self._settings: list[tuple] = []   # (Abschnitt, Einstellung, Wert, Einheit)
        self._entries: list[dict] = []   # Ergebnisse und Hinweise in zeitlicher Reihenfolge

    def open(
        self,
        prufer: str,
        pruefnummer: str,
        auftragsnummer: str = "",
        bass_artikel_nr: str = "",
        getriebetyp: str = "",
        kunden_artikel_nr: str = "",
        getriebeseriennummer: str = "",
        kraftmessbolzen_seriennummer: str = "",
        kommentar: str = "",
    ) -> Path:
        if not SAVE_CSV:
            return None

        # Dateiname: Baß-Artikel-Nr_Prüfnummer_EOL_Datum (Nutzer 27.10.2026)
        parts = [bass_artikel_nr, pruefnummer, "EOL", datetime.now().strftime("%Y-%m-%d")]
        base = "_".join(_safe_name(p) for p in parts if p.strip())
        self._raw_path = OUTPUT_DIR / f"{base}.csv"
        n = 2   # gleicher Artikel + Prüfnummer am selben Tag nochmal → _2, _3, … statt überschreiben
        while self._raw_path.exists() or self._raw_path.with_suffix(".xlsx").exists():
            self._raw_path = OUTPUT_DIR / f"{base}_{n}.csv"
            n += 1
        self._path = self._raw_path   # bis die Excel-Datei erzeugt ist
        self._entries = []
        self._header = [
            ("Software Version", APP_VERSION),
            ("Prüfnummer", pruefnummer),
            ("Prüfer", prufer),
            ("Auftragsnummer", auftragsnummer),
            ("Baß Artikel-Nr.", bass_artikel_nr),
            ("Getriebetyp", getriebetyp),
            ("Kunden Artikel-Nr.", kunden_artikel_nr),
            ("Serien-Nr. Getriebe", getriebeseriennummer),
            ("Serien-Nr. Kraftmessbolzen", kraftmessbolzen_seriennummer),
            ("Kommentar", kommentar),
            ("Datum", datetime.now().strftime("%d.%m.%Y %H:%M")),
            ("Messzeit Lastlauf [min]", _settings.step_by_action("run")["duration_seconds"] / 60),
            ("Haltezeit Leckage [s]", _settings.step_by_action("leak")["hold_seconds"]),
            ("Haltezeit Kraftprüfung [s]", _settings.step_by_action("torque")["hold_seconds"]),
        ]
        self._settings = _current_settings()

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        self._file = open(self._raw_path, "w", newline="", encoding="utf-8-sig")
        self._file.write("# Pruefbericht - Getriebepruefstand Landmaschinen (Zwischendatei)\n")
        for key, value in self._header:
            self._file.write(f"# {key}: {value}\n")
        for section, name, value, unit in self._settings:
            self._file.write(f"# Einstellung {section} – {name}: {value} {unit}\n")
        self._writer = csv.writer(self._file)
        self._writer.writerow(["Zeitstempel", "Schritt"] + [c for c, _ in _COLUMNS] + ["Status"])
        self._file.flush()
        return self._path

    def write_row(self, data: dict, step: int, status: str) -> None:
        if self._writer is None:
            return
        self._writer.writerow(
            [datetime.now().strftime(_TS_FORMAT)[:-3], step]
            + [data.get(sid, "") for _, sid in _COLUMNS]
            + [status]
        )
        self._file.flush()

    def add_result(self, step: int, name: str, text: str, status: str) -> None:
        """Ergebniszeile je Schritt."""
        self._entries.append({"kind": "result", "step": step, "name": name,
                              "text": text, "status": status, "note": ""})
        if self._file is not None:
            self._file.write(f"# Ergebnis Schritt {step} {name}: {text} – {status}\n")
            self._file.flush()

    def supersede_last_result(self) -> None:
        """Schritt wird wiederholt: letzte Ergebniszeile bleibt stehen, wird aber markiert."""
        for entry in reversed(self._entries):
            if entry["kind"] == "result":
                entry["note"] = f"wiederholt um {datetime.now().strftime('%H:%M:%S')} – nicht gewertet"
                return

    def add_note(self, text: str) -> None:
        """Hinweiszeile (z. B. Sicherheitsunterbrechung)."""
        self._entries.append({"kind": "note", "text": text})

    def finalize(self, passed: bool, note: str = "") -> None:
        if self._file is None:
            return
        self._file.close()
        self._file = None
        self._writer = None
        if note:
            self.add_note(note)
        xlsx = self._raw_path.with_suffix(".xlsx")
        try:
            self._write_xlsx(xlsx, passed)
        except Exception as exc:
            print(f"[ReportWriter] Excel-Datei nicht erzeugt, CSV bleibt: {exc}")
            self._append_csv_summary(passed)
            return
        self._path = xlsx
        try:
            self._raw_path.unlink()
        except Exception:
            pass

    # ── Excel ─────────────────────────────────────────────────────────────────

    def _read_raw(self) -> tuple[list[str], list[list]]:
        with open(self._raw_path, newline="", encoding="utf-8-sig") as f:
            lines = [line for line in f if not line.startswith("#")]
        rows = list(csv.reader(lines))
        if not rows:
            return [], []
        head, body = rows[0], []
        for r in rows[1:]:
            if not r:
                continue
            out: list = []
            for i, cell in enumerate(r):
                if i == 0:
                    try:
                        out.append(datetime.strptime(cell, _TS_FORMAT))
                    except ValueError:
                        out.append(cell)
                elif cell == "" or i == len(r) - 1:
                    out.append(cell if cell != "" else None)
                else:
                    try:
                        out.append(float(cell) if "." in cell or "e" in cell.lower() else int(cell))
                    except ValueError:
                        out.append(cell)
            body.append(out)
        return head, body

    def _write_xlsx(self, path: Path, passed: bool) -> None:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill

        bold = Font(bold=True)
        head_fill = PatternFill("solid", fgColor="D9D9D9")
        wb = Workbook()

        # ── Blatt Prüfbericht ──
        ws = wb.active
        ws.title = "Prüfbericht"
        ws.append(["Prüfbericht – Getriebeprüfstand Landmaschinen"])
        ws["A1"].font = Font(bold=True, size=14)
        ws.append([])
        for key, value in self._header:
            ws.append([key, value])
            ws.cell(ws.max_row, 1).font = bold
        result_text = "BESTANDEN" if passed else "NICHT BESTANDEN"
        ws.append(["Gesamtergebnis", result_text])
        cell = ws.cell(ws.max_row, 2)
        cell.font = Font(bold=True, size=12)
        cell.fill = PatternFill("solid", fgColor=_STATUS_FILL["OK" if passed else "KRITISCH"])
        ws.cell(ws.max_row, 1).font = bold

        ws.append([])
        ws.append(["Schritt", "Prüfung", "Ergebnis", "Details", "Bemerkung"])
        for c in ws[ws.max_row]:
            c.font, c.fill = bold, head_fill
        for e in self._entries:
            if e["kind"] != "result":
                continue
            ws.append([e["step"], e["name"], e["status"], e["text"], e["note"]])
            fill = _STATUS_FILL.get(e["status"])
            if fill:
                ws.cell(ws.max_row, 3).fill = PatternFill("solid", fgColor=fill)

        notes = [e["text"] for e in self._entries if e["kind"] == "note"]
        if notes:
            ws.append([])
            ws.append(["Hinweise"])
            ws.cell(ws.max_row, 1).font = bold
            for text in notes:
                ws.append(["", text])

        if self._settings:
            ws.append([])
            ws.append(["Einstellungen"])
            ws.cell(ws.max_row, 1).font = bold
            ws.append(["Abschnitt", "Einstellung", "Wert", "Einheit"])
            for c in ws[ws.max_row]:
                c.font, c.fill = bold, head_fill
            for row in self._settings:
                ws.append(list(row))

        for col, width in zip("ABCDE", (30, 34, 12, 80, 40)):
            ws.column_dimensions[col].width = width
        for row in ws.iter_rows():
            for c in row:
                c.alignment = Alignment(vertical="top", wrap_text=c.column in (4, 5))

        # ── Blatt Rohdaten ──
        raw = wb.create_sheet("Rohdaten")
        head, body = self._read_raw()
        if head:
            raw.append(head)
            for c in raw[1]:
                c.font, c.fill = bold, head_fill
            for r in body:
                raw.append(r)
            for row in raw.iter_rows(min_row=2, max_col=1):
                row[0].number_format = "dd.mm.yyyy hh:mm:ss.000"
            raw.column_dimensions["A"].width = 24
            for i in range(2, len(head) + 1):
                raw.column_dimensions[raw.cell(1, i).column_letter].width = 16
            raw.freeze_panes = "A2"

        wb.save(path)

    def _append_csv_summary(self, passed: bool) -> None:
        """Rückfall ohne Excel: Ergebnisse ans Ende der CSV-Datei."""
        try:
            with open(self._raw_path, "a", encoding="utf-8-sig") as f:
                f.write("# =============================================\n")
                f.write(f"# Gesamtergebnis: {'BESTANDEN' if passed else 'NICHT BESTANDEN'}\n")
                for e in self._entries:
                    if e["kind"] == "note":
                        f.write(f"# Hinweis: {e['text']}\n")
                    elif e["note"]:
                        f.write(f"# Ergebnis Schritt {e['step']} {e['name']}: ({e['note']})\n")
        except Exception:
            pass

    @property
    def path(self) -> Path:
        return self._path
