"""Contratos HTTP de presupuestos y meta de ahorro. El frontend habla en soles."""
from __future__ import annotations

from pydantic import BaseModel, Field


class BudgetIn(BaseModel):
    category_id: int
    amount: float = Field(gt=0, description="Tope mensual en soles")
    active: bool = True


class BudgetOut(BaseModel):
    id: int
    category_id: int
    categoria: str
    color: str
    amount: float
    active: bool


class MetaAhorroIn(BaseModel):
    """Monto fijo que quieres ahorrar cada mes. 0 la desactiva."""

    amount: float = Field(ge=0)
