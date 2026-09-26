"""Cortes de saldo: cuanto dinero hay de verdad en cada fecha."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from app.compartido.entidad import utcnow


class SaldoCorte(SQLModel, table=True):
    """Cuanto dinero tienes de verdad en una fecha: una foto de tus cuentas.

    Es la otra mitad del control. Los movimientos dicen lo que registraste; los
    cortes, lo que de verdad hay. Entre dos cortes, lo que cambio tu dinero tendria
    que coincidir con los ingresos menos los gastos registrados (mas el efecto del
    tipo de cambio en tus dolares). Lo que no cuadra es lo que se escapo sin
    registrar (services/seguimiento.py).

    Vive aparte de los movimientos a proposito: un corte no es un gasto ni un
    ingreso, y mezclarlo con ellos contaria el dinero dos veces.
    """

    __tablename__ = "saldo_corte"

    id: int | None = Field(default=None, primary_key=True)
    fecha: date = Field(index=True, unique=True)
    # Soles por dolar en diezmilesimas (3.71 -> 37100). No es dinero, pero multiplica
    # dinero, y en coma flotante los centimos se desvian.
    tipo_cambio_diezmil: int = 0
    notas: str | None = None
    origen: str = "manual"            # manual | excel
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class SaldoCuenta(SQLModel, table=True):
    """El saldo de una cuenta en un corte, en la moneda de esa cuenta."""

    __tablename__ = "saldo_cuenta"

    id: int | None = Field(default=None, primary_key=True)
    corte_id: int = Field(foreign_key="saldo_corte.id", index=True)
    cuenta: str                        # "Hapi", "BCP", "Efectivo", "Tarjeta de crédito"...
    moneda: str = "PEN"                # PEN | USD
    # Una deuda (la tarjeta de credito) resta del total en vez de sumar.
    es_deuda: bool = False
    monto_cents: int = 0               # siempre positivo: el signo lo da es_deuda
    orden: int = 0                     # orden de las columnas, para el formulario

    __table_args__ = (
        UniqueConstraint("corte_id", "cuenta", "moneda", name="uq_saldo_cuenta_corte"),
    )
