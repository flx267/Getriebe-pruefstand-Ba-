from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QHBoxLayout, QHeaderView, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ui import icons, theme


class ResultPage(QWidget):
    """Vollbild-Ergebnisseite – ersetzt den Testinhalt im QStackedWidget."""

    new_test_clicked = pyqtSignal()
    quit_clicked = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Farbiger oberer Banner: Icon-Kachel + Ergebnis
        self._banner = theme.frame("banner", "")
        self._banner.setFixedHeight(110)
        banner_layout = QHBoxLayout(self._banner)
        banner_layout.setContentsMargins(40, 0, 40, 0)
        banner_layout.setSpacing(18)

        self._icon_label = theme.label("", "icontile")
        self._icon_label.setFixedSize(60, 60)
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        texts = QVBoxLayout()
        texts.setSpacing(2)
        self._result_label = theme.label("", "h1")
        self._sub_label = theme.label("", "body", wrap=True)
        texts.addStretch()
        texts.addWidget(self._result_label)
        texts.addWidget(self._sub_label)
        texts.addStretch()

        banner_layout.addStretch()
        banner_layout.addWidget(self._icon_label)
        banner_layout.addLayout(texts)
        banner_layout.addStretch()

        # Unterer Bereich
        bottom = QWidget()
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(40, 20, 40, 20)
        bottom_layout.setSpacing(12)

        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["Schritt", "Prüfung", "Ergebnis", "Details"])
        header = self._table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        self._table.setWordWrap(True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # Automatische Bewertung ersetzt keine Kontrolle durch einen Menschen (Nutzer 01.10.2026)
        review_hint = theme.label(
            "Hinweis: Die automatische Bewertung ist nur eine Hilfe. Bitte alle Ergebnisse, "
            "Diagramme und Rohdaten im Prüfbericht (inkl. Drehzahlsensor RPM1) von einer "
            "fachkundigen Person prüfen lassen, bevor das Getriebe freigegeben wird.",
            "box", "warn", wrap=True)

        self._path_label = theme.label("", "caption", wrap=True)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        btn_quit = theme.button("Programm beenden", "secondary", "power", height=52)
        btn_quit.setFont(theme.font(12))
        btn_quit.clicked.connect(self.quit_clicked.emit)
        btn_new = theme.button("Neue Prüfung  →", "primary", height=52)
        btn_new.setFont(theme.font(13))
        btn_new.clicked.connect(self.new_test_clicked.emit)
        btn_row.addWidget(btn_quit, stretch=1)
        btn_row.addWidget(btn_new, stretch=2)

        bottom_layout.addWidget(self._table, stretch=1)
        bottom_layout.addWidget(review_hint)
        bottom_layout.addWidget(self._path_label)
        bottom_layout.addLayout(btn_row)

        root.addWidget(self._banner)
        root.addWidget(bottom, stretch=1)

    def show_result(self, passed: bool, step_results: list[dict], csv_path=None,
                    aborted: str = "", reasons: list[str] | None = None) -> None:
        if aborted:
            tone, icon_name = "warn", "warn"
            self._result_label.setText("ABGEBROCHEN – NICHT BESTANDEN")
            self._sub_label.setText(aborted + (": " + ", ".join(reasons) if reasons else ""))
        elif passed:
            tone, icon_name = "ok", "check"
            self._result_label.setText("BESTANDEN")
            self._sub_label.setText("")
        else:
            tone, icon_name = "crit", "x"
            self._result_label.setText("NICHT BESTANDEN")
            self._sub_label.setText("")
        theme.set_tone(self._banner, tone)
        theme.set_tone(self._icon_label, tone)
        self._icon_label.setPixmap(icons.pixmap(icon_name, theme.TONE_COLORS[tone], 30))
        self._sub_label.setVisible(bool(self._sub_label.text()))

        self._table.setRowCount(len(step_results))
        for row, res in enumerate(step_results):
            self._table.setItem(row, 0, QTableWidgetItem(f"  {res['step']}"))
            self._table.setItem(row, 1, QTableWidgetItem(f"  {res['sensor']}"))
            s_item = QTableWidgetItem(f"  {res['worst_status']}")
            s_item.setForeground(QColor(theme.TONE_COLORS[theme.tone_of(res["worst_status"])]))
            self._table.setItem(row, 2, s_item)
            self._table.setItem(row, 3, QTableWidgetItem(f"  {res.get('text', '')}"))
        self._table.resizeRowsToContents()
        self._path_label.setText(f"Prüfbericht: {csv_path}" if csv_path else "Kein Prüfbericht angelegt.")
