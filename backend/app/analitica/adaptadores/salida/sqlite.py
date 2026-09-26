"""Los puertos de analitica sobre SQLite: aqui viven las consultas."""
from __future__ import annotations

from datetime import date

from sqlmodel import Session, func, select

from app.analitica.dominio.calculos import CLAVE_META_AHORRO, EXCLUIDOS
from app.analitica.dominio.entidades import Budget
from app.analitica.dominio.periodos import Rango
from app.compartido.tipos import TxStatus
from app.movimientos.dominio.entidades import Transaction
from app.plataforma import kv


class MovimientosQueCuentan:
    """Lectura de los movimientos del modulo movimientos (solo consultas)."""

    def __init__(self, session: Session):
        self.session = session

    def que_cuentan(self, rango: Rango) -> list[Transaction]:
        return list(self.session.exec(
            select(Transaction).where(
                Transaction.booking_date >= rango.desde,
                Transaction.booking_date <= rango.hasta,
                Transaction.status.not_in(EXCLUIDOS),
            )
        ).all())

    def primera_y_ultima_fecha(self) -> tuple[date | None, date | None]:
        fechas = self.session.exec(
            select(func.min(Transaction.booking_date), func.max(Transaction.booking_date))
            .where(Transaction.status.not_in(EXCLUIDOS))
        ).first()
        return (fechas[0], fechas[1]) if fechas else (None, None)

    def cuantos_por_revisar(self) -> int:
        return len(self.session.exec(
            select(Transaction).where(Transaction.status == TxStatus.por_revisar)
        ).all())


class TopesSqlite:
    def __init__(self, session: Session):
        self.session = session

    def activos(self) -> list[Budget]:
        return list(self.session.exec(select(Budget).where(Budget.active == True)).all())  # noqa: E712

    def todos(self) -> list[Budget]:
        return list(self.session.exec(select(Budget)).all())

    def obtener(self, tope_id: int) -> Budget | None:
        return self.session.get(Budget, tope_id)

    def de_categoria(self, cat_id: int) -> list[Budget]:
        return list(self.session.exec(select(Budget).where(Budget.category_id == cat_id)).all())

    def existe_para(self, cat_id: int) -> bool:
        return self.session.exec(
            select(Budget).where(Budget.category_id == cat_id)
        ).first() is not None

    def agregar(self, tope: Budget) -> None:
        self.session.add(tope)

    def borrar(self, tope: Budget) -> None:
        self.session.delete(tope)


class MetaKv:
    """La meta de ahorro, en la tabla clave-valor."""

    def __init__(self, session: Session):
        self.session = session

    def leer(self) -> str | None:
        return kv.leer(self.session, CLAVE_META_AHORRO)

    def guardar(self, cents: int) -> None:
        kv.guardar(self.session, CLAVE_META_AHORRO, str(cents))
