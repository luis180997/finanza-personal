"""Categorias y reglas: el catalogo con el que se clasifica cada movimiento."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from app.compartido.entidad import enum_requerido, enum_opcional, utcnow
from app.compartido.tipos import Direction, Necessity


class Category(SQLModel, table=True):
    __tablename__ = "category"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    parent_id: int | None = Field(default=None, foreign_key="category.id")
    kind: Direction = Field(sa_column=enum_requerido(Direction))
    color: str = "#64748b"
    icon: str = "circle"
    default_necessity: Necessity | None = Field(default=None, sa_column=enum_opcional(Necessity))
    is_system: bool = False
    sort: int = 100

    __table_args__ = (UniqueConstraint("name", "parent_id", name="uq_category_name_parent"),)


class Rule(SQLModel, table=True):
    """Reglas del usuario. Se evaluan por prioridad ascendente."""

    __tablename__ = "rule"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    priority: int = 100
    active: bool = True

    # condiciones (todas las definidas deben cumplirse)
    field: str = "merchant"          # merchant | description | subject | sender | account
    op: str = "contains"             # contains | equals | regex | startswith
    value: str = ""
    min_amount_cents: int | None = None
    max_amount_cents: int | None = None
    direction: Direction | None = Field(default=None, sa_column=enum_opcional(Direction))

    # acciones
    set_category_id: int | None = Field(default=None, foreign_key="category.id")
    set_necessity: Necessity | None = Field(default=None, sa_column=enum_opcional(Necessity))
    set_merchant: str | None = None
    set_recurring: bool | None = None
    stop: bool = True

    hits: int = 0
    created_at: datetime = Field(default_factory=utcnow)
