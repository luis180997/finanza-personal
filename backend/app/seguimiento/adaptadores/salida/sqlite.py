"""Los puertos de seguimiento sobre SQLite: aqui viven las consultas."""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from sqlalchemy import case
from sqlmodel import Session, col, func, select

from app.compartido.tipos import Direction, TxStatus
from app.movimientos.dominio.entidades import Transaction
from app.plataforma.config import settings
from app.seguimiento.dominio.entidades import SaldoCorte, SaldoCuenta

_EXCLUIDOS = (TxStatus.duplicada, TxStatus.ignorada)


class CortesSqlite:
    def __init__(self, session: Session):
        self.session = session

    def por_fecha(self) -> list[SaldoCorte]:
        return list(self.session.exec(select(SaldoCorte).order_by(col(SaldoCorte.fecha))).all())

    def saldos_por_corte(self) -> dict[int, list[SaldoCuenta]]:
        saldos: dict[int, list[SaldoCuenta]] = defaultdict(list)
        for s in self.session.exec(
            select(SaldoCuenta).order_by(col(SaldoCuenta.orden), col(SaldoCuenta.id))
        ).all():
            saldos[s.corte_id].append(s)
        return saldos

    def obtener(self, corte_id: int) -> SaldoCorte | None:
        return self.session.get(SaldoCorte, corte_id)

    def en_fecha(self, fecha: date, excluir_id: int | None = None) -> SaldoCorte | None:
        consulta = select(SaldoCorte).where(SaldoCorte.fecha == fecha)
        if excluir_id is not None:
            consulta = consulta.where(SaldoCorte.id != excluir_id)
        return self.session.exec(consulta).first()

    def fechas(self) -> set[date]:
        return set(self.session.exec(select(SaldoCorte.fecha)).all())

    def saldos_de(self, corte_id: int) -> list[SaldoCuenta]:
        return list(self.session.exec(
            select(SaldoCuenta).where(SaldoCuenta.corte_id == corte_id)
        ).all())

    def agregar(self, fila) -> None:
        self.session.add(fila)

    def borrar(self, fila) -> None:
        self.session.delete(fila)


class RegistradoSqlite:
    """Lo registrado entre dos cortes, leido de los movimientos."""

    def __init__(self, session: Session):
        self.session = session

    def entre(self, desde_excluido: date, hasta: date) -> tuple[int, int]:
        es_ingreso = Transaction.direction == Direction.ingreso
        es_gasto = Transaction.direction == Direction.gasto
        ingresos, gastos = self.session.exec(
            select(
                func.coalesce(func.sum(case((es_ingreso, Transaction.amount_cents), else_=0)), 0),
                func.coalesce(func.sum(case((es_gasto, Transaction.amount_cents), else_=0)), 0),
            ).where(
                Transaction.booking_date > desde_excluido,
                Transaction.booking_date <= hasta,
                col(Transaction.status).not_in(_EXCLUIDOS),
                # Un cobro en dolares aun sin su importe en soles (Por revisar) no se
                # puede sumar a soles: queda en el descuadre hasta que lo completes.
                Transaction.currency == settings.base_currency,
            )
        ).one()
        return int(ingresos), int(gastos)
