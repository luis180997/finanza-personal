"""Almacen clave-valor: estado del sincronizador y ajustes sueltos.

Es infraestructura, no negocio: cada modulo que necesita guardar un valor suelto
(la meta de ahorro, el nombre del titular, la ultima sincronizacion) lo hace a
traves de un adaptador que usa estas funciones.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Field, Session, SQLModel

from app.compartido.entidad import utcnow


class KV(SQLModel, table=True):
    """Estado del sincronizador y ajustes sueltos (meta de ahorro, etc.)."""

    __tablename__ = "kv"

    key: str = Field(primary_key=True)
    value: str = ""
    updated_at: datetime = Field(default_factory=utcnow)


def leer(session: Session, clave: str) -> str | None:
    fila = session.get(KV, clave)
    return fila.value if fila else None


def guardar(session: Session, clave: str, valor: str) -> None:
    """Crea o actualiza la clave y confirma."""
    fila = session.get(KV, clave)
    if fila:
        fila.value = valor
        fila.updated_at = datetime.now(timezone.utc)
    else:
        fila = KV(key=clave, value=valor)
    session.add(fila)
    session.commit()
