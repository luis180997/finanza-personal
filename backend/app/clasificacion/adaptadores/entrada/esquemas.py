"""Contratos HTTP de categorias y reglas. El frontend habla en soles (float)."""
from __future__ import annotations

from pydantic import BaseModel

from app.compartido.tipos import Direction, Necessity


class CategoryIn(BaseModel):
    name: str
    parent_id: int | None = None
    kind: Direction = Direction.gasto
    color: str = "#64748b"
    icon: str = "circle"
    default_necessity: Necessity | None = None


class CategoryOut(CategoryIn):
    id: int
    is_system: bool = False
    sort: int = 100


class RuleIn(BaseModel):
    name: str
    priority: int = 100
    active: bool = True
    field: str = "merchant"
    op: str = "contains"
    value: str = ""
    min_amount: float | None = None
    max_amount: float | None = None
    direction: Direction | None = None
    set_category_id: int | None = None
    set_necessity: Necessity | None = None
    set_merchant: str | None = None
    set_recurring: bool | None = None
    stop: bool = True


class RuleOut(RuleIn):
    id: int
    hits: int = 0
