"""Los puertos de movimientos sobre SQLite: aqui viven las consultas."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import case
from sqlmodel import Session, col, func, or_, select

from app.clasificacion.dominio.entidades import Category
from app.compartido.tipos import Direction, TxStatus
from app.correo.dominio.entidades import EmailMessage
from app.excel.dominio.entidades import ImportBatch
from app.movimientos.aplicacion.puertos import FiltrosMovimientos, PaginaDeMovimientos
from app.movimientos.dominio.duplicados import minuto_de
from app.movimientos.dominio.entidades import Account, Transaction, TransactionPapelera
from app.movimientos.dominio.papelera import FORANEAS


class MovimientosSqlite:
    def __init__(self, session: Session):
        self.session = session

    def obtener(self, tx_id: int) -> Transaction | None:
        return self.session.get(Transaction, tx_id)

    def agregar(self, tx: Transaction) -> None:
        self.session.add(tx)

    def borrar(self, tx: Transaction) -> None:
        self.session.delete(tx)

    def de_categoria(self, cat_id: int) -> list[Transaction]:
        return list(self.session.exec(
            select(Transaction).where(Transaction.category_id == cat_id)
        ).all())

    def duplicados_de(self, tx_id: int) -> list[Transaction]:
        return list(self.session.exec(
            select(Transaction).where(Transaction.duplicate_of_id == tx_id)
        ).all())

    def por_huella(self, huella: str) -> Transaction | None:
        return self.session.exec(
            select(Transaction).where(Transaction.dedupe_hash == huella)
        ).first()

    def del_lote(self, lote_id: int) -> list[Transaction]:
        return list(self.session.exec(
            select(Transaction).where(Transaction.import_batch_id == lote_id)
        ).all())

    def protegidos_del_lote(self, lote_id: int) -> int:
        return len(self.session.exec(
            select(Transaction.id).where(
                Transaction.import_batch_id == lote_id,
                Transaction.locked_by_user == True,  # noqa: E712
            )
        ).all())

    def duplicados_de_fuera_del_lote(self, lote_id: int) -> list[Transaction]:
        del_lote = select(Transaction.id).where(Transaction.import_batch_id == lote_id)
        return list(self.session.exec(
            select(Transaction).where(
                col(Transaction.duplicate_of_id).in_(del_lote),
                or_(
                    col(Transaction.import_batch_id).is_(None),
                    Transaction.import_batch_id != lote_id,
                ),
            )
        ).all())

    def ids_por_huella(self, huellas: list[str]) -> dict[str, int]:
        return dict(self.session.exec(
            select(Transaction.dedupe_hash, Transaction.id)
            .where(col(Transaction.dedupe_hash).in_(huellas))
        ).all())

    def candidatos_mellizo(self, tx: Transaction) -> list[Transaction]:
        minuto = minuto_de(tx)
        if minuto is None:
            return []
        return list(self.session.exec(
            select(Transaction).where(
                Transaction.id != tx.id,
                Transaction.amount_cents == tx.amount_cents,
                Transaction.direction == tx.direction,
                Transaction.account_id == tx.account_id,
                Transaction.occurred_at >= minuto,
                Transaction.occurred_at < minuto + timedelta(minutes=1),
                Transaction.status != TxStatus.duplicada,
            )
        ).all())

    def candidatos_cruzados(self, tx: Transaction, ventana: timedelta) -> list[Transaction]:
        return list(self.session.exec(
            select(Transaction).where(
                Transaction.id != tx.id,
                Transaction.amount_cents == tx.amount_cents,
                Transaction.direction == tx.direction,
                Transaction.occurred_at >= tx.occurred_at - ventana,
                Transaction.occurred_at <= tx.occurred_at + ventana,
                Transaction.status != TxStatus.duplicada,
            )
        ).all())

    def por_revisar(self, limite: int) -> list[Transaction]:
        return list(self.session.exec(
            select(Transaction)
            .where(Transaction.status == TxStatus.por_revisar)
            .order_by(col(Transaction.occurred_at).desc())
            .limit(limite)
        ).all())

    def pagina(
        self, filtros: FiltrosMovimientos, pagina: int, tamano: int, orden: str,
    ) -> PaginaDeMovimientos:
        f = filtros
        condiciones = []
        if f.desde:
            condiciones.append(Transaction.booking_date >= f.desde)
        if f.hasta:
            condiciones.append(Transaction.booking_date <= f.hasta)
        if f.direccion:
            condiciones.append(Transaction.direction == f.direccion)
        if f.estado:
            condiciones.append(Transaction.status == f.estado)
        else:
            # Sin filtro explicito, fuera lo que no cuenta. Los duplicados y los
            # ignorados si sumaban en la cabecera de la tabla, que contradecia al
            # panel: el mismo periodo daba dos totales distintos segun la pantalla.
            condiciones.append(
                col(Transaction.status).not_in([TxStatus.duplicada, TxStatus.ignorada])
            )
        if f.cuenta_id:
            condiciones.append(Transaction.account_id == f.cuenta_id)
        if f.categoria_id:
            condiciones.append(Transaction.category_id == f.categoria_id)
        if f.necesidad:
            condiciones.append(Transaction.necessity == f.necesidad)
        if f.origen:
            condiciones.append(Transaction.source == f.origen)
        if f.buscar:
            patron = f"%{f.buscar.lower()}%"
            condiciones.append(
                or_(
                    func.lower(Transaction.merchant).like(patron),
                    func.lower(Transaction.merchant_raw).like(patron),
                    func.lower(Transaction.description).like(patron),
                    func.lower(Transaction.notes).like(patron),
                )
            )

        base = select(Transaction)
        for c in condiciones:
            base = base.where(c)

        # Total y sumas en la propia base: antes se cargaban todas las filas del filtro
        # solo para contarlas, y "Todo mi historial" traia miles en cada cambio de pagina.
        es_gasto = Transaction.direction == Direction.gasto
        es_ingreso = Transaction.direction == Direction.ingreso
        total, suma_gastos, suma_ingresos = self.session.exec(
            select(
                func.count(),
                func.coalesce(func.sum(case((es_gasto, Transaction.amount_cents), else_=0)), 0),
                func.coalesce(func.sum(case((es_ingreso, Transaction.amount_cents), else_=0)), 0),
            ).select_from(Transaction).where(*condiciones)
        ).one()

        # Con importes iguales (hay cientos en el Excel) el orden entre ellos no estaba
        # definido, y al pasar de pagina se podian repetir o saltar filas.
        ordenes = {
            "fecha_desc": (col(Transaction.occurred_at).desc(), col(Transaction.id).desc()),
            "fecha_asc": (col(Transaction.occurred_at).asc(), col(Transaction.id).asc()),
            "monto_desc": (col(Transaction.amount_cents).desc(), col(Transaction.id).desc()),
            "monto_asc": (col(Transaction.amount_cents).asc(), col(Transaction.id).asc()),
        }
        consulta = base.order_by(*ordenes[orden]).offset((pagina - 1) * tamano).limit(tamano)
        return PaginaDeMovimientos(
            items=list(self.session.exec(consulta).all()),
            total=total,
            suma_gastos_cents=suma_gastos,
            suma_ingresos_cents=suma_ingresos,
        )


class CuentasSqlite:
    def __init__(self, session: Session):
        self.session = session

    def ordenadas(self) -> list[Account]:
        return list(self.session.exec(select(Account).order_by(col(Account.name))).all())

    def todas(self) -> dict[int, Account]:
        return {a.id: a for a in self.session.exec(select(Account)).all()}

    def obtener(self, cuenta_id: int) -> Account | None:
        return self.session.get(Account, cuenta_id)

    def por_nombre(self, nombre: str) -> Account | None:
        return self.session.exec(select(Account).where(Account.name == nombre)).first()

    def activas(self) -> list[Account]:
        return list(self.session.exec(select(Account).where(Account.active == True)).all())  # noqa: E712

    def efectivo(self) -> Account | None:
        return self.session.exec(select(Account).where(Account.bank == "efectivo")).first()

    def tiene_movimientos(self, cuenta_id: int) -> bool:
        return self.session.exec(
            select(Transaction).where(Transaction.account_id == cuenta_id).limit(1)
        ).first() is not None

    def agregar(self, cuenta: Account) -> None:
        self.session.add(cuenta)

    def borrar(self, cuenta: Account) -> None:
        self.session.delete(cuenta)


# A que tabla apunta cada columna foranea de un movimiento.
_TABLA_DE = {
    "account_id": Account, "counter_account_id": Account, "category_id": Category,
    "email_id": EmailMessage, "duplicate_of_id": Transaction, "import_batch_id": ImportBatch,
}
assert set(_TABLA_DE) == set(FORANEAS)


class PapeleraSqlite:
    def __init__(self, session: Session):
        self.session = session

    def ultimas(self, limite: int) -> list[TransactionPapelera]:
        return list(self.session.exec(
            select(TransactionPapelera).order_by(col(TransactionPapelera.id).desc()).limit(limite)
        ).all())

    def obtener(self, papelera_id: int) -> TransactionPapelera | None:
        return self.session.get(TransactionPapelera, papelera_id)

    def borrar(self, fila: TransactionPapelera) -> None:
        self.session.delete(fila)

    def decisiones_para(self, huella: str, email_id: int | None) -> TransactionPapelera | None:
        condiciones = [TransactionPapelera.dedupe_hash == huella]
        if email_id is not None:
            condiciones.append(TransactionPapelera.email_id == email_id)
        return self.session.exec(
            select(TransactionPapelera)
            .where(TransactionPapelera.editado_por_usuario == True, or_(*condiciones))  # noqa: E712
            .order_by(col(TransactionPapelera.id).desc())
        ).first()

    def referencias_rotas(self, tx: Transaction) -> list[str]:
        rotas = []
        for campo in FORANEAS:
            valor = getattr(tx, campo)
            if valor is not None and self.session.get(_TABLA_DE[campo], valor) is None:
                rotas.append(campo)
        return rotas
