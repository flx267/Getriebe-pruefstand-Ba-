"""Linien-Icons (24×24, Strich 2 px) statt Emojis – sehen auf jedem Rechner gleich aus.

    icons.icon("play", "#121417", 16)     → QIcon für Buttons
    icons.pixmap("warn", "#f5b83d", 22)   → QPixmap für Labels
"""

from PyQt6.QtCore import QByteArray, QRectF, Qt
from PyQt6.QtGui import QGuiApplication, QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

_PATHS = {
    "logo": '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.9 4.9l2.1 2.1M17 17l2.1 2.1'
            'M2 12h3M19 12h3M4.9 19.1L7 17M17 7l2.1-2.1"/>',
    "warn": '<path d="M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>'
            '<path d="M12 9v4M12 17h.01"/>',
    "stop": '<path d="M7.9 2h8.2L22 7.9v8.2L16.1 22H7.9L2 16.1V7.9z"/><path d="M8 12h8"/>',
    "refresh": '<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>',
    "check": '<path d="M5 12l5 5L19 7"/>',
    "x": '<path d="M6 6l12 12M18 6L6 18"/>',
    "play": '<path d="M7 4.5v15l12-7.5z"/>',
    "square": '<rect x="6" y="6" width="12" height="12" rx="1.5"/>',
    "up": '<path d="M12 19V5M5 12l7-7 7 7"/>',
    "down": '<path d="M12 5v14M19 12l-7 7-7-7"/>',
    "right": '<path d="M5 12h14M12 5l7 7-7 7"/>',
    "sliders": '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12"/>'
               '<circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
    "wrench": '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.8-3.8a6 6 0 0 1-7.9 7.9'
              'l-6.9 6.9a2.1 2.1 0 0 1-3-3l6.9-6.9a6 6 0 0 1 7.9-7.9l-3.8 3.8z"/>',
    "power": '<path d="M12 2v10"/><path d="M18.4 6.6a9 9 0 1 1-12.8 0"/>',
}


def _svg(name: str, color: str) -> bytes:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
            f'stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
            f'{_PATHS[name]}</svg>').encode()


def pixmap(name: str, color: str, size: int = 16) -> QPixmap:
    app = QGuiApplication.instance()
    dpr = app.devicePixelRatio() if app else 1.0
    pm = QPixmap(round(size * dpr), round(size * dpr))
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    QSvgRenderer(QByteArray(_svg(name, color))).render(painter, QRectF(0, 0, pm.width(), pm.height()))
    painter.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def icon(name: str, color: str, size: int = 16, disabled_color: str | None = None) -> QIcon:
    ic = QIcon(pixmap(name, color, size))
    if disabled_color:
        ic.addPixmap(pixmap(name, disabled_color, size), QIcon.Mode.Disabled)
    return ic
