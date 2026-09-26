"""Topes de presupuesto."""
from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel

from app.compartido.entidad import utcnow


class Budget(SQLModel, table=True):
    """Tope mensual de gasto para una categoria.

    Se repite cada mes: no hay una fila por mes. Un presupuesto es una intencion
    estable ("no mas de S/150 en delivery"), y guardar una copia por mes solo
    anadiria filas que mantener.

    Solo existen las categorias donde TU pusiste un tope. Un tope por defecto
    inventado por el sistema seria peor que ninguno: dispararia alarmas que no
    significan nada y te ensenaria a ignorarlas.
    """

    __tablename__ = "budget"

    id: int | None = Field(default=None, primary_key=True)
    category_id: int = Field(foreign_key="category.id", unique=True, index=True)
    amount_cents: int
    active: bool = True
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
