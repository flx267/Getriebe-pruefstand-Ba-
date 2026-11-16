"""
Sicherheitsbedingungen über die Digitaleingänge – reine Logik ohne Qt/DAQ, genutzt vom
Prüfablauf (core/test_runner.py) und vom DAQ-Monitor.

SAFETY_REQUIRED_DI gilt während der ganzen Prüfung. Der Sperrbolzen (BOLT_DI) wird nur
geprüft, wenn der Schritt einen Zustand verlangt: "out" (Motorlauf) oder "in"
(oberer Zylinder drückt gegen das blockierte Getriebe). Steckt der Sperrbolzen, entfallen
die Eingänge aus SAFETY_IGNORED_WHEN_BOLT_IN (DI0 wird vom Kraftbolzen ausgelöst).
"""

from typing import Iterable, Optional

from config.settings import (
    BOLT_DI, BOLT_FAULT_TEXTS, BOLT_OUT_VALUE, DI_FAULT_TEXTS, DI_LABELS,
    SAFETY_IGNORED_WHEN_BOLT_IN, SAFETY_REQUIRED_DI,
)


def bolt_inserted(di: Optional[list]) -> Optional[bool]:
    """True = Sperrbolzen steckt, False = gezogen, None = nicht lesbar."""
    if not di or BOLT_DI >= len(di) or di[BOLT_DI] is None:
        return None
    return di[BOLT_DI] != BOLT_OUT_VALUE


def di_violations(di: Optional[list], bolt: Optional[str] = None,
                  ignore: Iterable[int] = ()) -> list[str]:
    """Nicht erfüllte Bedingungen; leer = in Ordnung. bolt: None | "out" | "in".
    ignore: Sicherheits-Eingänge, die nicht geprüft werden (STEPS → "ignore_di")."""
    if not di:
        return ["Digitaleingänge nicht lesbar"]
    required = dict(SAFETY_REQUIRED_DI)
    for ch in ignore:
        required.pop(ch, None)
    if bolt == "in" or (bolt != "out" and bolt_inserted(di)):
        for ch in SAFETY_IGNORED_WHEN_BOLT_IN:
            required.pop(ch, None)
    if bolt == "out":
        required[BOLT_DI] = BOLT_OUT_VALUE
    elif bolt == "in":
        required[BOLT_DI] = 1 - BOLT_OUT_VALUE
    violations = []
    for ch, soll in required.items():
        actual = di[ch] if ch < len(di) else None
        if actual is None:
            violations.append(f"DI{ch} {DI_LABELS.get(ch, '')} nicht lesbar")
        elif actual != soll:
            violations.append(f"{_fault_text(ch, soll)}  (DI{ch})")
    return violations


def _fault_text(ch: int, soll: int) -> str:
    """Klartext für den Werker; DI3 je nach verlangtem Bolzenzustand."""
    if ch == BOLT_DI:
        return BOLT_FAULT_TEXTS["out" if soll == BOLT_OUT_VALUE else "in"]
    return DI_FAULT_TEXTS.get(ch) or f"{DI_LABELS.get(ch, '')} = {1 - soll} (Soll {soll})"
