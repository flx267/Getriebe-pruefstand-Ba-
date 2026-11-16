import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer

import config.settings as _settings
from config.settings import MEASUREMENT_INTERVAL_MS
from ui import theme

_REDRAW_INTERVAL_MS = 500
_INTERVAL_S = MEASUREMENT_INTERVAL_MS / 1000.0
# Beschriftung der Grenzlinien rechtsbündig über der Linie (sonst rechts abgeschnitten)
_LABEL_POS = {"position": 0.98, "anchors": [(1, 0), (1, 0)]}
_LABEL_POS_WARN = {"position": 0.78, "anchors": [(1, 0), (1, 0)]}   # versetzt zu Kritisch


class ChartWidget(pg.PlotWidget):

    def __init__(self, sensors: list[dict]):
        super().__init__()
        self.setBackground(theme.SUNKEN)
        self.setAntialiasing(True)

        ref = sensors[0]
        colors = [theme.SERIES[i % len(theme.SERIES)] for i in range(len(sensors))]
        self.setTitle(self._title_html(sensors, colors, ref["unit"]),
                      color=theme.MUTED, size="10pt", justify="left")
        for name in ("left", "bottom"):
            axis = self.getAxis(name)
            axis.setPen(theme.BORDER)
            axis.setTextPen(theme.MUTED)
        self.getAxis("bottom").setLabel("Zeit", units="s", color=theme.MUTED)
        self.showGrid(x=True, y=True, alpha=0.10)

        self._max_points = 10_000
        self._data: dict[str, list[float]] = {}
        self._curves: dict[str, pg.PlotDataItem] = {}
        self._dirty = False
        self._target_range: tuple[float, float] | None = None

        for sensor, color in zip(sensors, colors):
            sid = sensor["id"]
            curve = self.plot(pen=pg.mkPen(color, width=2), name=sensor["name"])
            self._data[sid] = []
            self._curves[sid] = curve

        self._redraw_timer = QTimer(self)
        self._redraw_timer.setInterval(_REDRAW_INTERVAL_MS)
        self._redraw_timer.timeout.connect(self._flush)
        self._redraw_timer.start()

        dash = Qt.PenStyle.DashLine
        warn_val = ref.get("warn_threshold") or ref.get("warn_high")
        crit_val = ref.get("critical_threshold") or ref.get("critical_high")
        warn_low = ref.get("warn_low")
        crit_low = ref.get("critical_low")

        if warn_val is not None:
            self.addItem(pg.InfiniteLine(pos=warn_val, angle=0,
                                         pen=pg.mkPen(theme.WARN, width=1, style=dash),
                                         label=f"Warnung {warn_val}",
                                         labelOpts={"color": theme.WARN, **_LABEL_POS_WARN}))
        if crit_val is not None:
            self.addItem(pg.InfiniteLine(pos=crit_val, angle=0,
                                         pen=pg.mkPen(theme.CRIT, width=1, style=dash),
                                         label=f"Kritisch {crit_val}",
                                         labelOpts={"color": theme.CRIT, **_LABEL_POS}))
        # Soll-Linie (z. B. RPM1 gegen MOTOR_RUN_RPM) + Toleranzband Warnung
        if ref.get("target_setting"):
            target = float(getattr(_settings, ref["target_setting"]))
            self.addItem(pg.InfiniteLine(pos=target, angle=0,
                                         pen=pg.mkPen(theme.OK, width=2),
                                         label=f"Soll {target:.0f}",
                                         labelOpts={"color": theme.OK, **_LABEL_POS}))
            band = target * _settings.RPM1_WARN_PCT / 100.0
            for pos in (target - band, target + band):
                self.addItem(pg.InfiniteLine(pos=pos, angle=0,
                                             pen=pg.mkPen(theme.WARN, width=1, style=dash)))
            # Y-Bereich in _flush: Messwerte + Soll-Linie mit Toleranzband immer sichtbar
            self._target_range = (target - 2 * band, target + 2 * band)
        if warn_low is not None:
            self.addItem(pg.InfiniteLine(pos=warn_low, angle=0,
                                         pen=pg.mkPen(theme.WARN, width=1, style=dash)))
        if crit_low is not None:
            self.addItem(pg.InfiniteLine(pos=crit_low, angle=0,
                                         pen=pg.mkPen(theme.CRIT, width=1, style=dash)))

    @staticmethod
    def _title_html(sensors: list[dict], colors: list[str], unit: str) -> str:
        """Titelzeile mit Legende: farbiger Strich + Name je Kurve, Einheit grau."""
        parts = [f'<span style="color:{color}">━━</span>&nbsp;'
                 f'<span style="color:{theme.TEXT};font-weight:600">{s["name"]}</span>'
                 for s, color in zip(sensors, colors)]
        return "&nbsp;&nbsp;&nbsp;&nbsp;".join(parts) + f"&nbsp;&nbsp;&nbsp;[{unit}]"

    def add_value(self, sensor_id: str, value: float) -> None:
        if sensor_id not in self._data:
            return
        buf = self._data[sensor_id]
        if len(buf) >= self._max_points:
            del buf[: self._max_points // 2]
        buf.append(value)
        self._dirty = True

    def _flush(self) -> None:
        if not self._dirty:
            return
        for sid, curve in self._curves.items():
            buf = self._data[sid]
            n = len(buf)
            if n == 0:
                continue
            max_display = 2000
            if n > max_display:
                step = n // max_display
                display = buf[::step]
            else:
                display = buf
            y = np.array(display, dtype=np.float64)
            x = np.linspace(0.0, (n - 1) * _INTERVAL_S, len(y))
            curve.setData(x, y)
            if self._target_range is not None:
                lo = min(self._target_range[0], float(y.min()))
                hi = max(self._target_range[1], float(y.max()))
                self.setYRange(lo, hi, padding=0.05)
        self._dirty = False

    def clear_data(self) -> None:
        for sid in self._data:
            self._data[sid].clear()
        for curve in self._curves.values():
            curve.setData([], [])
        self._dirty = False
