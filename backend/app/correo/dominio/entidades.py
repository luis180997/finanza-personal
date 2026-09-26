"""El archivo de correos bancarios."""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Column, Text
from sqlmodel import Field, SQLModel

from app.compartido.entidad import enum_requerido, utcnow


class ParseStatus(str, enum.Enum):
    parseado = "parseado"
    sin_parser = "sin_parser"      # correo candidato que ningun patron reconocio
    ignorado = "ignorado"          # publicidad, no es un movimiento
    error = "error"


class EmailMessage(SQLModel, table=True):
    """Archivo crudo de cada correo procesado. Permite re-parsear sin volver a Gmail."""

    __tablename__ = "email_message"

    id: int | None = Field(default=None, primary_key=True)
    gmail_id: str = Field(index=True, unique=True)
    thread_id: str | None = None
    sender: str = Field(index=True)
    subject: str = ""
    received_at: datetime = Field(index=True)
    snippet: str = ""
    body_text: str = Field(default="", sa_column=Column(Text))
    parse_status: ParseStatus = Field(sa_column=enum_requerido(ParseStatus))
    parser: str | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
