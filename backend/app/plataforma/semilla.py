"""Datos iniciales: cuentas y taxonomia de categorias.

Los datos viven en el dominio de cada modulo (clasificacion/dominio/taxonomia.py y
movimientos/dominio/cuentas.py). Aqui solo se insertan, al arrancar, los que falten.
"""
from __future__ import annotations

from sqlmodel import Session, select

from app.clasificacion.dominio.entidades import Category, Rule
from app.clasificacion.dominio.taxonomia import (
    EXPENSE_TREE,
    INCOME_TREE,
    SEED_RULES,
    TRANSFER_TREE,
)
from app.compartido.tipos import Direction
from app.movimientos.dominio.cuentas import DEFAULT_ACCOUNTS
from app.movimientos.dominio.entidades import Account


def seed(session: Session) -> dict[str, int]:
    created = {"accounts": 0, "categories": 0, "rules": 0}

    for acc in DEFAULT_ACCOUNTS:
        if not session.exec(select(Account).where(Account.name == acc["name"])).first():
            session.add(Account(**acc))
            created["accounts"] += 1
    session.commit()

    def add_tree(name, color, icon, kind, necessity, children, sort):
        parent = session.exec(
            select(Category).where(Category.name == name, Category.parent_id.is_(None))
        ).first()
        if not parent:
            parent = Category(
                name=name, kind=kind, color=color, icon=icon,
                default_necessity=necessity, is_system=True, sort=sort,
            )
            session.add(parent)
            session.commit()
            session.refresh(parent)
            created["categories"] += 1

        for i, child in enumerate(children):
            nombre, nec_hijo = child if isinstance(child, tuple) else (child, necessity)
            exists = session.exec(
                select(Category).where(Category.name == nombre, Category.parent_id == parent.id)
            ).first()
            if exists:
                # mantiene al dia la necesidad si se corrige la taxonomia
                if exists.is_system and exists.default_necessity != nec_hijo:
                    exists.default_necessity = nec_hijo
                    session.add(exists)
                continue
            session.add(Category(
                name=nombre, parent_id=parent.id, kind=kind, color=color,
                icon=icon, default_necessity=nec_hijo, is_system=True, sort=i,
            ))
            created["categories"] += 1
        session.commit()

    for i, (name, color, icon, nec, kids) in enumerate(EXPENSE_TREE):
        add_tree(name, color, icon, Direction.gasto, nec, kids, i)
    for i, (name, color, icon, kids) in enumerate(INCOME_TREE):
        add_tree(name, color, icon, Direction.ingreso, None, kids, 100 + i)
    for i, (name, color, icon, kids) in enumerate(TRANSFER_TREE):
        add_tree(name, color, icon, Direction.transferencia, None, kids, 200 + i)

    for name, field, op, value, cat_name, nec, prio in SEED_RULES:
        if session.exec(select(Rule).where(Rule.name == name)).first():
            continue
        cat = session.exec(select(Category).where(Category.name == cat_name)).first()
        session.add(Rule(
            name=name, field=field, op=op, value=value, priority=prio,
            set_category_id=cat.id if cat else None, set_necessity=nec,
        ))
        created["rules"] += 1
    session.commit()

    return created
