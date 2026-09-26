"""Movimientos y cuentas.

Decisiones clave:
  * El dinero se guarda en *centimos* (int). Cero errores de coma flotante.
  * Toda fila es un movimiento en formato *largo* (una fila = una transaccion),
    no el formato ancho del Excel actual. Eso permite cortar por cualquier eje.
  * `direction` + `account` reemplazan las columnas "Ingresos / Gastos totales".
  * `necessity` estructura lo que hoy escribes a mano en "Observaciones".

Las entidades se declaran con SQLModel: es la forma de describir los datos, no
una puerta a la base. Nada en `dominio/` abre una sesion ni hace consultas.
"""
from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import JSON, Column, Index, Text
from sqlmodel import Field, SQLModel

from app.compartido.entidad import enum_requerido, enum_opcional, utcnow
from app.compartido.tipos import Direction, Necessity, PaymentMethod, Source, TxStatus


class AccountType(str, enum.Enum):
    debito = "debito"            # cuenta de ahorros / sueldo
    credito = "credito"          # tarjeta de credito
    billetera = "billetera"      # Yape / Plin
    efectivo = "efectivo"


class Account(SQLModel, table=True):
    __tablename__ = "account"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)          # "BCP Debito", "BBVA Credito"
    bank: str = "otro"                                   # bcp | bbva | yape | efectivo | otro
    type: AccountType = Field(sa_column=enum_requerido(AccountType))
    currency: str = "PEN"
    last4: str | None = None                             # ultimos 4 digitos, para el matcheo
    aliases: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    credit_limit_cents: int | None = None
    billing_day: int | None = None                       # dia de cierre de la tarjeta
    active: bool = True
    created_at: datetime = Field(default_factory=utcnow)


class Transaction(SQLModel, table=True):
    __tablename__ = "transaction"

    id: int | None = Field(default=None, primary_key=True)

    # --- que, cuanto, cuando
    occurred_at: datetime = Field(index=True)
    booking_date: date = Field(index=True)               # fecha local (America/Lima) para agrupar
    amount_cents: int                                    # SIEMPRE positivo, el signo lo da direction
    currency: str = "PEN"
    direction: Direction = Field(sa_column=enum_requerido(Direction))

    # --- donde
    account_id: int | None = Field(default=None, foreign_key="account.id", index=True)
    counter_account_id: int | None = Field(default=None, foreign_key="account.id")
    payment_method: PaymentMethod | None = Field(default=None, sa_column=enum_opcional(PaymentMethod))
    merchant: str | None = Field(default=None, index=True)   # normalizado: "rappi"
    merchant_raw: str | None = None                          # tal cual vino en el correo
    description: str | None = None
    operation_number: str | None = Field(default=None, index=True)

    # --- clasificacion
    category_id: int | None = Field(default=None, foreign_key="category.id", index=True)
    necessity: Necessity | None = Field(default=None, sa_column=enum_opcional(Necessity))
    tags: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    notes: str | None = None
    is_recurring: bool = False

    # --- procedencia y control de calidad
    source: Source = Field(sa_column=enum_requerido(Source))
    status: TxStatus = Field(sa_column=enum_requerido(TxStatus))
    confidence: float = 1.0                              # 0-1, lo asigna el parser
    parser: str | None = None
    email_id: int | None = Field(default=None, foreign_key="email_message.id")
    dedupe_hash: str = Field(index=True, unique=True)
    duplicate_of_id: int | None = Field(default=None, foreign_key="transaction.id")
    import_batch_id: int | None = Field(default=None, foreign_key="import_batch.id", index=True)

    # --- tus decisiones (services/decisiones.py)
    # Lo registraste o lo corregiste tu. La base de datos rechaza borrarlo (trigger
    # en core/db.py) y ningun reproceso ni regla nueva lo reclasifica.
    locked_by_user: bool = False
    # Cuando lo tocaste por ultima vez. A diferencia de locked_by_user, no se borra
    # al quitar la proteccion: es lo que permite recuperar tus decisiones si el
    # movimiento se borra y su correo se vuelve a procesar.
    user_edited_at: datetime | None = None

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    __table_args__ = (
        Index("ix_tx_date_dir", "booking_date", "direction"),
        Index("ix_tx_status", "status"),
    )


class TransactionPapelera(SQLModel, table=True):
    """Copia de cada movimiento borrado, sea quien sea quien lo borre.

    No la escribe la app: la escribe un trigger de SQLite (core/db.py). Asi tambien
    quedan copiados los borrados que no pasan por el codigo de la app: un script,
    una limpieza a mano, un test mal apuntado.
    """

    __tablename__ = "transaction_papelera"

    id: int | None = Field(default=None, primary_key=True)
    tx_id: int = Field(index=True)
    email_id: int | None = Field(default=None, index=True)
    dedupe_hash: str = Field(default="", index=True)
    source: str = ""
    # El movimiento tenia decisiones tuyas (user_edited_at no era nulo).
    editado_por_usuario: bool = False
    datos: str = Field(default="", sa_column=Column(Text))     # la fila entera, en JSON
    borrado_en: datetime = Field(default_factory=utcnow)
