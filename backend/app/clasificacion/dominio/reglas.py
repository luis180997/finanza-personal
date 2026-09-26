"""Reglas del usuario: cuando aplica una y que cambia en el movimiento."""
from __future__ import annotations

import re
from collections.abc import Iterable

from app.clasificacion.dominio.entidades import Rule
from app.movimientos.dominio.entidades import Transaction


def valor_campo(tx: Transaction, campo: str, contexto: dict) -> str:
    if campo == "merchant":
        return tx.merchant or tx.merchant_raw or ""
    if campo == "description":
        return tx.description or ""
    if campo == "subject":
        return contexto.get("subject", "")
    if campo == "sender":
        return contexto.get("sender", "")
    if campo == "account":
        return contexto.get("account_name", "")
    return ""


def coincide(op: str, valor: str, patron: str) -> bool:
    valor, patron = valor.lower(), patron.lower()
    if not patron:
        return False
    if op == "equals":
        return valor == patron
    if op == "startswith":
        return valor.startswith(patron)
    if op == "regex":
        try:
            return re.search(patron, valor, re.IGNORECASE) is not None
        except re.error:
            return False
    return patron in valor


def aplica(regla: Rule, tx: Transaction, contexto: dict) -> bool:
    if regla.direction and regla.direction != tx.direction:
        return False
    if regla.min_amount_cents and tx.amount_cents < regla.min_amount_cents:
        return False
    if regla.max_amount_cents and tx.amount_cents > regla.max_amount_cents:
        return False
    return coincide(regla.op, valor_campo(tx, regla.field, contexto), regla.value)


def primera_que_aplica(reglas: Iterable[Rule], tx: Transaction, contexto: dict) -> Rule | None:
    """Las reglas llegan ya ordenadas por prioridad: gana la primera que encaja."""
    return next((r for r in reglas if aplica(r, tx, contexto)), None)


def aplicar_efectos(regla: Rule, tx: Transaction) -> None:
    """Lo que la regla cambia en el movimiento ademas de la categoria."""
    if regla.set_merchant:
        tx.merchant = regla.set_merchant
    if regla.set_recurring is not None:
        tx.is_recurring = regla.set_recurring
