"""Contratos HTTP de presupuestos y meta de ahorro. El frontend habla en soles."""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.compartido.validaciones import exigir_un_centimo


class BudgetIn(BaseModel):
    category_id: int
    amount: float = Field(gt=0, description="Tope mensual en soles")
    active: bool = True

    # Un tope de 0.004 se guardaba como S/ 0.00 y salia "excedido" con el primer gasto.
    _un_centimo = field_validator("amount")(exigir_un_centimo)


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
