"""Contratos HTTP del correo y del laboratorio de parsers."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SyncIn(BaseModel):
    dias: int | None = Field(default=None, ge=1, le=365)
    max_correos: int = Field(default=300, ge=1, le=1000)


class SyncOut(BaseModel):
    correos_leidos: int
    correos_nuevos: int
    transacciones_creadas: int
    por_revisar: int
    duplicados: int
    sin_parser: int
    errores: list[str]
    ejecutado_en: datetime


class EmailOut(BaseModel):
    id: int
    gmail_id: str
    sender: str
    subject: str
    received_at: datetime
    snippet: str
    parse_status: str
    parser: str | None
    error: str | None
    body_text: str | None = None


class PruebaParserIn(BaseModel):
    """Pega aqui un correo real para ver que extraen los patrones."""

    sender: str = ""
    subject: str = ""
    body: str


class PruebaParserOut(BaseModel):
    reconocido: bool
    parser: str | None = None
    motivo: str | None = None
    resultado: dict | None = None
    texto_normalizado: str | None = None
