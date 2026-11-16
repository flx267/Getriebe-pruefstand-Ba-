"""Getriebeprüfstand – Startpunkt.

    python main.py          echte Hardware (USB-4711A), ohne Karte keine Prüfung
    python main.py --sim    Simulation, nur für Entwicklertests
"""

import sys

from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox

from ui import theme
from ui.main_window import MainWindow
from ui.start_dialog import StartDialog


def _make_hardware(simulated: bool):
    if simulated:
        from hardware.simulation import SimulatedHardware
        return SimulatedHardware()
    from hardware.real_hardware import RealHardware
    return RealHardware()


def main() -> None:
    simulated = "--sim" in sys.argv
    app = QApplication(sys.argv)
    app.setApplicationName("Getriebeprüfstand")
    theme.apply(app)
    app.setQuitOnLastWindowClosed(False)

    hardware = _make_hardware(simulated)
    try:
        while True:
            dialog = StartDialog(simulated)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                break
            if not hardware.is_connected and not hardware.connect():
                QMessageBox.critical(
                    None, "Keine Verbindung zur Messkarte",
                    f"{hardware.connect_error}\n\n"
                    "Bitte prüfen:\n"
                    "• USB-Kabel der USB-4711A gesteckt?\n"
                    "• DAQ-Monitor / Advantech Navigator geschlossen?\n\n"
                    "Danach erneut „Test starten“.",
                )
                continue
            dialog.commit()   # Prüfnummer erst jetzt verbrauchen

            outcome = {"new_test": False}

            def on_end(new_test: bool) -> None:
                outcome["new_test"] = new_test
                app.quit()

            window = MainWindow(
                hardware,
                simulated,
                dialog.prufer,
                dialog.pruefnummer,
                auftragsnummer=dialog.auftragsnummer,
                bass_artikel_nr=dialog.bass_artikel_nr,
                getriebetyp=dialog.getriebetyp,
                kunden_artikel_nr=dialog.kunden_artikel_nr,
                getriebeseriennummer=dialog.getriebeseriennummer,
                kraftmessbolzen_seriennummer=dialog.kraftmessbolzen_seriennummer,
                kommentar=dialog.kommentar,
            )
            window.session_ended.connect(on_end)
            window.show()
            app.exec()
            window.deleteLater()
            if not outcome["new_test"]:
                break
    finally:
        hardware.disconnect()


if __name__ == "__main__":
    main()
