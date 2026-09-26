"""Piezas para declarar entidades. Solo describen datos: no abren la base."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column
from sqlalchemy import Enum as SAEnum


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def enum_requerido(e) -> Column:
    return Column(SAEnum(e, native_enum=False, length=20), nullable=False)


def enum_opcional(e) -> Column:
    return Column(SAEnum(e, native_enum=False, length=20), nullable=True)
