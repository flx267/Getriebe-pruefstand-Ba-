"""Zentrales Erscheinungsbild (Entwurf „Prüfstand UI-Entwurf“, freigegeben 01.10.2026).

Alle Farben, Schriften und Widget-Stile stehen nur hier. Widgets bekommen keine eigenen
Farben mehr, sondern eine Rolle bzw. einen Ton als Qt-Property:

    btn.setProperty("variant", "primary")     # primary | secondary | ghost | danger | caution
    frame.setProperty("role", "panel")        # header | sidebar | panel | tile | strip …
    set_tone(label, "warn")                   # ok | warn | crit | active | muted | off | ""

Das Stylesheet setzt main.py einmal über apply(app) für die ganze Anwendung.
"""

from pathlib import Path

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor, QFont, QPalette
from PyQt6.QtWidgets import QFrame, QLabel, QPushButton, QSizePolicy, QWidget

from ui import icons

# ── Farben ────────────────────────────────────────────────────────────────────
BG = "#121417"            # Fenstergrund
SURFACE = "#1a1d21"       # Kopfzeile, Sidebar, Panels
RAISED = "#22262b"        # Kacheln, aktiver Schritt, Sekundär-Buttons
RAISED_HOVER = "#2b3036"
SUNKEN = "#16191d"        # Diagramme, Protokoll, Eingabefelder
BORDER = "#2c3137"
BORDER_SOFT = "#262a2f"
BORDER_STRONG = "#3a4047"

TEXT = "#e8eaed"
TEXT_2 = "#c3c8ce"
MUTED = "#9aa1a9"
FAINT = "#5d646c"

ACCENT = "#5cb8e6"        # „läuft gerade“, Fortschritt, Fokus
ACCENT_BG = "#0f2633"
ACCENT_TEXT = "#8fd0f0"
OK = "#6fdc8c"
OK_BG = "#13281c"
WARN = "#f5b83d"
WARN_BG = "#33280f"
WARN_TEXT = "#f5c56a"
CRIT = "#f2706b"
CRIT_BG = "#2a1517"
CRIT_TEXT = "#f6a19c"

PRIMARY = "#f2f3f5"
PRIMARY_HOVER = "#dfe2e6"
ON_PRIMARY = "#121417"
DANGER = "#c42b26"
DANGER_HOVER = "#a82420"
DANGER_PRESSED = "#8f1e1b"

SERIES = [ACCENT, "#f08a4b", "#b9a3f0", OK]   # Diagrammkurven

FONT = "Segoe UI"
MONO = "Cascadia Mono"

_ASSETS = (Path(__file__).parent / "assets").as_posix()   # Pfeile der Spinboxen

# Ton → Vordergrundfarbe (Icons, Diagramme, Tabellen)
TONE_COLORS = {"ok": OK, "warn": WARN, "crit": CRIT, "active": ACCENT,
               "muted": MUTED, "off": FAINT, "": TEXT}
# Bewertung aus core/ → Ton
STATUS_TONE = {"OK": "ok", "WARNUNG": "warn", "KRITISCH": "crit",
               "AKTIV": "active", "INFO": "muted", "ÜBERSPRUNGEN": "muted"}


def tone_of(status: str, default: str = "") -> str:
    return STATUS_TONE.get(status, default)


# ── Stylesheet ────────────────────────────────────────────────────────────────

def _tones(selector: str, rule: str) -> str:
    """Eine Regel je Ton; rule enthält {fg}, {bg}, {text} als Platzhalter."""
    values = {
        "ok": (OK, OK_BG, OK), "warn": (WARN, WARN_BG, WARN_TEXT),
        "crit": (CRIT, CRIT_BG, CRIT_TEXT), "active": (ACCENT, ACCENT_BG, ACCENT_TEXT),
        "muted": (MUTED, RAISED, TEXT_2),
    }
    return "\n".join(f'{selector}[tone="{t}"] {{ {rule.format(fg=fg, bg=bg, text=txt)} }}'
                     for t, (fg, bg, txt) in values.items())


STYLESHEET = f"""
QToolTip {{ background: {RAISED}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px 6px; }}
QDialog[role="alert"] {{ background: {SURFACE}; }}
QSplitter::handle {{ background: {BORDER}; width: 1px; }}

/* Flächen */
QFrame[role="header"]  {{ background: {SURFACE}; border: none; border-bottom: 1px solid {BORDER}; }}
QFrame[role="sidebar"] {{ background: {SURFACE}; border: none; border-right: 1px solid {BORDER}; }}
QFrame[role="panel"]   {{ background: {SURFACE}; border: 1px solid {BORDER_SOFT}; border-radius: 12px; }}
QFrame[role="tile"]    {{ background: {RAISED}; border: none; border-radius: 10px; }}
QFrame[role="checktile"] {{ background: {SUNKEN}; border: 1px dashed {BORDER_STRONG}; border-radius: 10px; }}
QFrame[role="banner"]  {{ background: {SURFACE}; border: none; border-bottom: 1px solid {BORDER}; }}
QFrame[role="logbar"]  {{ background: transparent; border: none; border-top: 1px solid {BORDER_SOFT}; }}
QFrame[role="sep"]     {{ background: {BORDER}; border: none; }}
QFrame[role="strip"]   {{ background: {MUTED}; border: none; }}
{_tones('QFrame[role="strip"]', "background: {fg};")}
{_tones('QFrame[role="banner"]', "background: {bg};")}

/* Text */
QLabel[role="apptitle"] {{ font-size: 13pt; font-weight: 600; color: {TEXT}; }}
QLabel[role="h1"]       {{ font-size: 18pt; font-weight: 600; color: {TEXT}; }}
QLabel[role="h2"]       {{ font-size: 14pt; font-weight: 600; color: {TEXT}; }}
QLabel[role="section"]  {{ font-size: 10pt; font-weight: 600; color: {TEXT}; padding-top: 4px; }}
QLabel[role="overline"] {{ color: {MUTED}; }}
QLabel[role="body"]     {{ font-size: 10pt; color: {TEXT_2}; }}
QLabel[role="listitem"] {{ font-size: 11pt; color: {TEXT_2}; padding: 5px 2px; }}
QLabel[role="field"]    {{ font-size: 10pt; color: {TEXT_2}; }}
QLabel[role="muted"]    {{ color: {MUTED}; }}
QLabel[role="caption"]  {{ font-size: 8pt; color: {MUTED}; }}
QLabel[role="value"]    {{ font-family: "{MONO}"; font-size: 16pt; font-weight: 600; color: {TEXT}; }}
QLabel[role="valuesm"]  {{ font-family: "{MONO}"; font-size: 13pt; font-weight: 600; color: {TEXT}; }}
QLabel[role="unit"]     {{ font-size: 9pt; color: {MUTED}; }}
QLabel[role="pill"]     {{ font-size: 8pt; color: {MUTED}; border: 1px solid {BORDER};
                           border-radius: 10px; padding: 2px 9px; }}
QLabel[role="badge"]    {{ font-size: 9pt; font-weight: 600; color: {MUTED}; background: {RAISED};
                           border-radius: 13px; padding: 5px 12px; }}
QLabel[role="box"]      {{ font-size: 11pt; font-weight: 600; color: {TEXT_2}; background: {RAISED};
                           border-radius: 10px; padding: 10px 14px; }}
QLabel[role="hint"]     {{ font-size: 9pt; color: {TEXT_2}; background: {RAISED};
                           border-radius: 8px; padding: 6px 10px; }}
QLabel[role="icontile"] {{ background: {RAISED}; border-radius: 12px; }}
QLabel[role="logo"]     {{ background: transparent; }}

/* Schrittliste */
QFrame[role="steprow"] {{ background: transparent; border: none; border-radius: 8px; }}
QFrame[role="steprow"][state="active"] {{ background: {RAISED}; }}
QLabel[role="stepname"] {{ font-size: 10pt; color: {MUTED}; }}
QLabel[role="stepname"][state="done"] {{ color: {TEXT_2}; }}
QLabel[role="stepname"][state="active"] {{ color: #ffffff; font-weight: 600; }}
QLabel[role="stepnum"] {{ font-size: 8pt; color: {MUTED}; border: 1px solid {BORDER_STRONG};
                          border-radius: 11px; }}
QLabel[role="stepnum"][state="active"] {{ background: {ACCENT}; color: #0d1114; border: none;
                                          font-weight: 700; }}
QLabel[role="stepnum"][state="ok"]   {{ background: {OK_BG}; border: none; }}
QLabel[role="stepnum"][state="warn"] {{ background: {WARN_BG}; border: none; }}
QLabel[role="stepnum"][state="crit"] {{ background: {CRIT_BG}; border: none; }}
QLabel[role="stepnum"][state="skip"] {{ border: 1px dashed {BORDER_STRONG}; color: {FAINT}; }}
QLabel[role="stepname"][state="skip"] {{ color: {FAINT}; }}

/* Töne (nach den Rollen, damit die Farbe gewinnt) */
{_tones("QLabel", "color: {fg};")}
QLabel[tone="off"] {{ color: {FAINT}; }}
{_tones('QLabel[role="box"]', "color: {text}; background: {bg};")}
{_tones('QLabel[role="hint"]', "color: {text}; background: {bg};")}
{_tones('QLabel[role="badge"]', "color: {fg}; background: {bg};")}
{_tones('QLabel[role="pill"]', "color: {text}; background: {bg}; border-color: {bg};")}
{_tones('QLabel[role="icontile"]', "background: {bg};")}
QLabel[role="value"][tone="warn"] {{ color: {WARN_TEXT}; }}
QLabel[role="value"][tone="crit"] {{ color: {CRIT_TEXT}; }}
QLabel[role="value"][tone="ok"]   {{ color: {TEXT}; }}
QLabel[role="valuesm"][tone="warn"] {{ color: {WARN_TEXT}; }}
QLabel[role="valuesm"][tone="crit"] {{ color: {CRIT_TEXT}; }}
QLabel[role="valuesm"][tone="ok"]   {{ color: {TEXT}; }}

/* Knöpfe */
QPushButton {{ background: {RAISED}; color: {TEXT}; border: 1px solid transparent;
               border-radius: 8px; padding: 6px 14px; }}
QPushButton:hover    {{ background: {RAISED_HOVER}; }}
QPushButton:pressed  {{ background: {BORDER}; }}
QPushButton:disabled {{ background: {SUNKEN}; color: {FAINT}; }}
QPushButton[variant="primary"]          {{ background: {PRIMARY}; color: {ON_PRIMARY}; font-weight: 600; }}
QPushButton[variant="primary"]:hover    {{ background: {PRIMARY_HOVER}; }}
QPushButton[variant="primary"]:pressed  {{ background: #c9cdd2; }}
QPushButton[variant="primary"]:disabled {{ background: {RAISED}; color: {FAINT}; }}
QPushButton[variant="ghost"]            {{ background: transparent; color: {TEXT_2}; border: 1px solid {BORDER_STRONG}; }}
QPushButton[variant="ghost"]:hover      {{ background: {RAISED}; color: {TEXT}; }}
QPushButton[variant="ghost"]:disabled   {{ color: {FAINT}; border-color: {BORDER}; }}
QPushButton[variant="danger"]           {{ background: {DANGER}; color: #ffffff; font-weight: 700; }}
QPushButton[variant="danger"]:hover     {{ background: {DANGER_HOVER}; }}
QPushButton[variant="danger"]:pressed   {{ background: {DANGER_PRESSED}; }}
QPushButton[variant="danger"]:disabled  {{ background: #3a1716; color: {FAINT}; }}
QPushButton[variant="caution"]          {{ background: {WARN_BG}; color: {WARN_TEXT}; }}
QPushButton[variant="caution"]:hover    {{ background: #45360f; }}
QPushButton[variant="caution"]:disabled {{ background: {SUNKEN}; color: {FAINT}; }}
QPushButton[size="sm"] {{ padding: 2px 10px; border-radius: 6px; }}
QPushButton[size="lg"] {{ padding: 4px 8px; border-radius: 10px; }}

/* Eingaben */
QLineEdit, QSpinBox, QDoubleSpinBox {{
    background: {SUNKEN}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 5px 8px; selection-background-color: {ACCENT}; selection-color: {BG}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border: 1px solid {ACCENT}; }}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{ color: {FAINT}; }}
QLineEdit[readOnly="true"] {{ background: {BG}; color: {MUTED}; }}
QLineEdit[size="lg"], QSpinBox[size="lg"] {{ padding: 8px 10px; font-size: 11pt; }}
QSpinBox[size="sm"], QDoubleSpinBox[size="sm"] {{ padding: 2px 20px 2px 6px; border-radius: 6px; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
    subcontrol-origin: border; width: 18px; border: none; background: transparent; }}
QAbstractSpinBox::up-button   {{ subcontrol-position: top right; border-top-right-radius: 6px; }}
QAbstractSpinBox::down-button {{ subcontrol-position: bottom right; border-bottom-right-radius: 6px; }}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{ background: {RAISED}; }}
QAbstractSpinBox::up-arrow   {{ image: url("{_ASSETS}/chevron-up.svg"); width: 9px; height: 9px; }}
QAbstractSpinBox::down-arrow {{ image: url("{_ASSETS}/chevron-down.svg"); width: 9px; height: 9px; }}
QAbstractSpinBox::up-arrow:disabled, QAbstractSpinBox::down-arrow:disabled {{ image: none; }}

QTextEdit {{ background: {SUNKEN}; color: {MUTED}; border: 1px solid {BORDER_SOFT};
             border-radius: 8px; padding: 4px 6px; }}

QTableWidget {{ background: {SURFACE}; color: {TEXT}; gridline-color: {BORDER_SOFT};
                border: 1px solid {BORDER_SOFT}; border-radius: 10px; font-size: 10pt; }}
QHeaderView::section {{ background: {SUNKEN}; color: {MUTED}; padding: 7px 6px; border: none;
                        border-bottom: 1px solid {BORDER}; font-weight: 600; }}

QProgressBar {{ background: {BORDER}; border: none; border-radius: 3px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
QProgressBar[tone="ok"]::chunk    {{ background: {OK}; }}
QProgressBar[tone="warn"]::chunk  {{ background: {WARN}; }}
QProgressBar[tone="crit"]::chunk  {{ background: {CRIT}; }}
QProgressBar[tone="muted"]::chunk {{ background: {FAINT}; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical   {{ background: transparent; width: 8px; margin: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 0; }}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{ background: {BORDER_STRONG}; border-radius: 4px; }}
QScrollBar::handle:vertical {{ min-height: 24px; }}
QScrollBar::handle:horizontal {{ min-width: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

QMessageBox QPushButton {{ min-width: 90px; }}
"""


def apply(app) -> None:
    """Stil, Palette, Grundschrift und Stylesheet für die ganze Anwendung."""
    app.setStyle("Fusion")
    pal = QPalette()
    for role, color in (
            (QPalette.ColorRole.Window, BG), (QPalette.ColorRole.WindowText, TEXT),
            (QPalette.ColorRole.Base, SUNKEN), (QPalette.ColorRole.AlternateBase, SURFACE),
            (QPalette.ColorRole.Text, TEXT), (QPalette.ColorRole.Button, RAISED),
            (QPalette.ColorRole.ButtonText, TEXT), (QPalette.ColorRole.Highlight, ACCENT),
            (QPalette.ColorRole.HighlightedText, BG), (QPalette.ColorRole.ToolTipBase, RAISED),
            (QPalette.ColorRole.ToolTipText, TEXT), (QPalette.ColorRole.PlaceholderText, "#6b727a"),
            (QPalette.ColorRole.Link, ACCENT)):
        pal.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text,
                 QPalette.ColorRole.ButtonText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor(FAINT))
    app.setPalette(pal)
    app.setFont(QFont(FONT, 9))
    app.setStyleSheet(STYLESHEET)


# ── Helfer ────────────────────────────────────────────────────────────────────

def font(size: float, weight: QFont.Weight = QFont.Weight.Normal, mono: bool = False) -> QFont:
    f = QFont(MONO if mono else FONT)
    f.setPointSizeF(size)
    f.setWeight(weight)
    return f


def set_prop(widget: QWidget, name: str, value) -> None:
    """Property setzen und Stil neu anwenden – nur bei Änderung (Live-Werte alle 100 ms)."""
    if widget.property(name) == value:
        return
    widget.setProperty(name, value)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def set_tone(widget: QWidget, tone: str | None) -> None:
    set_prop(widget, "tone", tone or "")


def label(text: str = "", role: str | None = None, tone: str | None = None,
          wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    if role:
        lbl.setProperty("role", role)
    lbl.setProperty("tone", tone or "")
    lbl.setWordWrap(wrap)
    if role in ("pill", "badge"):   # nicht auf Zeilenhöhe aufziehen (Kopfzeile)
        lbl.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    return lbl


def overline(text: str) -> QLabel:
    """Kleine Abschnittsüberschrift in Großbuchstaben („SCHRITT 3 / 7“, „PROTOKOLL“)."""
    lbl = label(text.upper(), "overline")
    f = font(8, QFont.Weight.DemiBold)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.0)
    lbl.setFont(f)
    return lbl


def frame(role: str, tone: str | None = None) -> QFrame:
    fr = QFrame()
    fr.setProperty("role", role)
    if tone is not None:
        fr.setProperty("tone", tone)
    return fr


def separator() -> QFrame:
    sep = frame("sep")
    sep.setFixedHeight(1)
    return sep


def button(text: str, variant: str = "secondary", icon_name: str | None = None,
           height: int | None = None, size: str | None = None) -> QPushButton:
    btn = QPushButton(f"  {text}" if icon_name else text)   # Abstand Icon ↔ Text
    btn.setProperty("variant", variant)
    if size:
        btn.setProperty("size", size)
    if height:
        btn.setFixedHeight(height)
    if icon_name:
        set_button_icon(btn, icon_name)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    return btn


def set_button_icon(btn: QPushButton, icon_name: str, px: int = 16) -> None:
    variant = btn.property("variant") or "secondary"
    color = {"primary": ON_PRIMARY, "danger": "#ffffff", "caution": WARN_TEXT,
             "ghost": TEXT_2}.get(variant, TEXT)
    btn.setIcon(icons.icon(icon_name, color, px, disabled_color=FAINT))
    btn.setIconSize(QSize(px, px))


def icon_tile(icon_name: str, tone: str, size: int = 44) -> QLabel:
    """Quadratische Kachel mit Linien-Icon (Dialoge, Ergebnis-Banner)."""
    tile = label("", "icontile", tone)
    tile.setFixedSize(size, size)
    tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
    tile.setPixmap(icons.pixmap(icon_name, TONE_COLORS.get(tone, TEXT), size // 2))
    return tile
