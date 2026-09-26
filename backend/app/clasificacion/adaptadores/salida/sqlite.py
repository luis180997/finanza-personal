"""Los puertos de clasificacion sobre SQLite: aqui viven las consultas."""
from __future__ import annotations

from sqlmodel import Session, col, func, select

from app.clasificacion.dominio.entidades import Category, Rule
from app.compartido.tipos import Necessity, TxStatus
from app.movimientos.dominio.entidades import Transaction


class CategoriasSqlite:
    def __init__(self, session: Session):
        self.session = session

    def ordenadas(self) -> list[Category]:
        return list(self.session.exec(
            select(Category).order_by(col(Category.sort), col(Category.name))
        ).all())

    def todas(self) -> dict[int, Category]:
        return {c.id: c for c in self.session.exec(select(Category)).all()}

    def obtener(self, cat_id: int) -> Category | None:
        return self.session.get(Category, cat_id)

    def por_nombre(self, nombre: str) -> Category | None:
        return self.session.exec(select(Category).where(Category.name == nombre)).first()

    def en_nivel(self, nombre: str, parent_id: int | None) -> Category | None:
        mismo_nivel = (
            col(Category.parent_id).is_(None) if parent_id is None
            else Category.parent_id == parent_id
        )
        return self.session.exec(select(Category).where(Category.name == nombre, mismo_nivel)).first()

    def hijas(self, cat_id: int) -> list[Category]:
        return list(self.session.exec(select(Category).where(Category.parent_id == cat_id)).all())

    def agregar(self, cat: Category) -> None:
        self.session.add(cat)

    def borrar(self, cat: Category) -> None:
        self.session.delete(cat)


class ReglasSqlite:
    def __init__(self, session: Session):
        self.session = session

    def activas_por_prioridad(self) -> list[Rule]:
        return list(self.session.exec(
            select(Rule).where(Rule.active == True).order_by(col(Rule.priority))  # noqa: E712
        ).all())

    def por_prioridad(self) -> list[Rule]:
        return list(self.session.exec(select(Rule).order_by(col(Rule.priority))).all())

    def obtener(self, regla_id: int) -> Rule | None:
        return self.session.get(Rule, regla_id)

    def que_apuntan_a(self, cat_id: int) -> list[Rule]:
        return list(self.session.exec(select(Rule).where(Rule.set_category_id == cat_id)).all())

    def registrar_acierto(self, regla: Rule) -> None:
        regla.hits += 1
        self.session.add(regla)

    def agregar(self, regla: Rule) -> None:
        self.session.add(regla)

    def borrar(self, regla: Rule) -> None:
        self.session.delete(regla)


class MemoriaSqlite:
    """La memoria de comercio se lee de los movimientos confirmados."""

    def __init__(self, session: Session):
        self.session = session

    def mas_usada(
        self, comercio: str, excluir_id: int | None,
    ) -> tuple[int, Necessity | None, int] | None:
        fila = self.session.exec(
            select(Transaction.category_id, Transaction.necessity, func.count().label("n"))
            .where(
                Transaction.merchant == comercio,
                Transaction.category_id.is_not(None),
                Transaction.status == TxStatus.confirmada,
                Transaction.id != excluir_id,
            )
            .group_by(Transaction.category_id, Transaction.necessity)
            .order_by(func.count().desc())
        ).first()
        return tuple(fila) if fila else None
