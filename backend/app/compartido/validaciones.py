"""Validaciones de datos de entrada que comparten los contratos HTTP de varios modulos."""
from __future__ import annotations

from datetime import datetime

from app.compartido.corte import ANIO_MAX, ANIO_MIN


def rechazar_nulo(valor):
    """Para columnas que la base no deja vacias: un null explicito llegaba hasta el
    commit y devolvia un 500. Si no quieres cambiar el campo, no lo mandes."""
    if valor is None:
        raise ValueError("no puede ser null; omite el campo si no quieres cambiarlo")
    return valor


def exigir_fecha_posible(valor: datetime | None) -> datetime | None:
    """Un movimiento del año 1 o del 9999 estiraba el historial a decenas de miles de
    meses y colgaba Tendencia (ver app/compartido/corte.py)."""
    if valor is not None and not ANIO_MIN <= valor.year <= ANIO_MAX:
        raise ValueError(f"la fecha tiene que estar entre los años {ANIO_MIN} y {ANIO_MAX}")
    return valor
