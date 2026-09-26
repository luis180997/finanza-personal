"""Contratos HTTP de movimientos y cuentas. El frontend habla en soles (float), la BD
en centimos."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

from app.compartido.tipos import Direction, Necessity, PaymentMethod, Source, TxStatus
from app.compartido.validaciones import exigir_fecha_posible, rechazar_nulo
from app.movimientos.dominio.entidades import AccountType


class AccountIn(BaseModel):
    name: str
    bank: str = "otro"
    type: AccountType
    currency: str = "PEN"
    last4: str | None = None
    aliases: list[str] = Field(default_factory=list)
    billing_day: int | None = None
    active: bool = True


class AccountOut(AccountIn):
    id: int


class AccountPatch(BaseModel):
    """Edicion parcial de una cuenta: solo cambia lo que mandas."""

    name: str | None = None
    bank: str | None = None
    type: AccountType | None = None
    currency: str | None = None
    last4: str | None = None
    aliases: list[str] | None = None
    billing_day: int | None = None
    active: bool | None = None

    _sin_nulos = field_validator(
        "name", "bank", "type", "currency", "aliases", "active", mode="before",
    )(rechazar_nulo)


class TransactionIn(BaseModel):
    """Alta manual: el caso de los gastos en efectivo."""

    amount: float = Field(gt=0, description="Monto positivo en la moneda de la cuenta")
    direction: Direction = Direction.gasto
    occurred_at: datetime | None = None
    account_id: int | None = None
    counter_account_id: int | None = None
    payment_method: PaymentMethod | None = None
    category_id: int | None = None
    merchant: str | None = None
    description: str | None = None
    necessity: Necessity | None = None
    currency: str = "PEN"
    tags: list[str] = Field(default_factory=list)
    notes: str | None = None
    is_recurring: bool = False

    @field_validator("merchant", "description", "notes")
    @classmethod
    def _limpiar(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        return v or None

    _fecha_posible = field_validator("occurred_at")(exigir_fecha_posible)


class TransactionPatch(BaseModel):
    amount: float | None = Field(default=None, gt=0)
    # Para pasar a soles un cobro que el banco aviso en dolares: {amount, currency: "PEN"}.
    currency: str | None = None
    direction: Direction | None = None
    occurred_at: datetime | None = None
    account_id: int | None = None
    payment_method: PaymentMethod | None = None
    category_id: int | None = None
    merchant: str | None = None
    description: str | None = None
    necessity: Necessity | None = None
    status: TxStatus | None = None
    tags: list[str] | None = None
    notes: str | None = None
    is_recurring: bool | None = None

    _sin_nulos = field_validator(
        "amount", "currency", "direction", "occurred_at", "status", "is_recurring", mode="before",
    )(rechazar_nulo)
    _fecha_posible = field_validator("occurred_at")(exigir_fecha_posible)

    @field_validator("currency")
    @classmethod
    def _moneda(cls, v: str | None) -> str | None:
        v = (v or "").strip().upper()
        if len(v) != 3 or not v.isalpha():
            raise ValueError("la moneda es un codigo de 3 letras, como PEN o USD")
        return v

    @field_validator("merchant", "description", "notes")
    @classmethod
    def _limpiar(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        return v or None


class TransactionOut(BaseModel):
    id: int
    occurred_at: datetime
    booking_date: date
    amount: float
    currency: str
    direction: Direction
    account_id: int | None
    account_name: str | None = None
    payment_method: PaymentMethod | None = None
    category_id: int | None
    category_name: str | None = None
    category_parent: str | None = None
    category_color: str | None = None
    merchant: str | None
    merchant_raw: str | None
    description: str | None
    operation_number: str | None = None
    necessity: Necessity | None
    tags: list[str] = Field(default_factory=list)
    notes: str | None
    is_recurring: bool
    source: Source
    status: TxStatus
    confidence: float
    parser: str | None
    email_id: int | None
    duplicate_of_id: int | None
    # Lo registraste o corregiste tu: protegido contra borrados y reprocesos.
    locked_by_user: bool = False
    # Solo se rellenan cuando el movimiento esta por revisar.
    motivos: list["MotivoRevision"] = Field(default_factory=list)
    motivo_resumen: str | None = None


class MotivoRevision(BaseModel):
    """Por que este movimiento pide atencion, en castellano y con que hacer."""

    clave: str
    texto: str
    accion: str


class PaginaTransacciones(BaseModel):
    items: list[TransactionOut]
    total: int
    pagina: int
    tamano: int
    suma_gastos: float
    suma_ingresos: float


class BulkAction(BaseModel):
    ids: list[int]
    category_id: int | None = None
    necessity: Necessity | None = None
    status: TxStatus | None = None
