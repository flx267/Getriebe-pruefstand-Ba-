from typing import Literal
from config.settings import SENSORS

Status = Literal["OK", "WARNUNG", "KRITISCH"]

_STATUS_RANK = {"OK": 0, "WARNUNG": 1, "KRITISCH": 2}


class Evaluator:

    def __init__(self):
        self._sensor_map = {s["id"]: s for s in SENSORS}

    def evaluate(self, sensor_id: str, value: float) -> Status:
        """Live-Bewertung für Sensoren mit warn_threshold/critical_threshold; alle anderen
        (Druck, Moment) werden erst am Schrittende bewertet → hier immer OK."""
        sensor = self._sensor_map.get(sensor_id)
        if sensor is None:
            return "OK"
        critical = sensor.get("critical_threshold")
        warn = sensor.get("warn_threshold")
        if critical is not None and value >= critical:
            return "KRITISCH"
        if warn is not None and value >= warn:
            return "WARNUNG"
        return "OK"

    def evaluate_drop(self, drop: float, warn: float, critical: float) -> Status:
        if drop >= critical:
            return "KRITISCH"
        if drop >= warn:
            return "WARNUNG"
        return "OK"

    def evaluate_min(self, value: float, pass_min: float) -> Status:
        """„Mindestens erreicht“ (Soll-Moment): darunter nicht bestanden."""
        return "OK" if value >= pass_min else "KRITISCH"

    def worst(self, a: Status, b: Status) -> Status:
        return a if _STATUS_RANK[a] >= _STATUS_RANK[b] else b

    def calculate_pass_fail(self, step_results: list[dict]) -> bool:
        # Wiederholte Durchläufe stehen im Bericht, gewertet wird nur der letzte
        return all(r.get("worst_status") != "KRITISCH"
                   for r in step_results if not r.get("superseded"))
