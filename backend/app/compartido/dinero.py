"""Dinero = enteros en centimos. Nunca float en la base de datos."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_CLEAN = re.compile(r"[^\d,.\-]")


def to_cents(value: float | str | Decimal) -> int:
    return int((Decimal(str(value)).quantize(Decimal("0.01"))) * 100)


def to_amount(cents: int) -> float:
    return round(cents / 100, 2)


def parse_money(raw: str) -> Decimal | None:
    """Convierte '1,234.56' | '1.234,56' | 'S/ 39.63' -> Decimal.

    Los correos peruanos usan formato en-US (coma = miles), pero toleramos ambos.
    """
    if raw is None:
        return None
    s = _CLEAN.sub("", str(raw)).strip()
    if not s:
        return None
    if "," in s and "." in s:
        # el separador decimal es el ultimo que aparece
        s = s.replace(",", "") if s.rfind(".") > s.rfind(",") else s.replace(".", "").replace(",", ".")
    elif "," in s:
        # coma sola: decimal si deja exactamente 2 digitos a la derecha
        s = s.replace(",", ".") if len(s.split(",")[-1]) == 2 else s.replace(",", "")
    try:
        return Decimal(s).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None
