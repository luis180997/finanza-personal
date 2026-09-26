"""La hora, en un solo sitio.

El dominio nunca la lee: la recibe. Los casos de uso la piden aqui, y los tests
pueden fijarla sustituyendo estas funciones.
"""
from __future__ import annotations

from datetime import date, datetime, timezone, tzinfo


def ahora_utc() -> datetime:
    return datetime.now(timezone.utc)


def ahora_en(zona: tzinfo) -> datetime:
    return datetime.now(zona)


def ahora_local() -> datetime:
    """La hora del sistema, sin zona (el contenedor corre en hora de Lima)."""
    return datetime.now()


def hoy() -> date:
    return date.today()
