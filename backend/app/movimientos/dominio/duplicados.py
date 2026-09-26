"""Deduplicacion: cuando dos movimientos son el mismo.

Dos niveles, porque son problemas distintos:

  1. HASH EXACTO (bloqueante). Impide insertar dos veces el mismo movimiento
     al re-sincronizar. Si hay numero de operacion, es la clave; si no, se
     construye con fecha + monto + comercio + cuenta (dominio/huella.py).

  2. SOSPECHA CRUZADA (informativa). Un mismo gasto puede llegar dos veces por
     canales distintos: la notificacion de Yape y el cargo de la tarjeta BCP
     que financia el yapeo. No se borra nada: se marca `por_revisar` con una
     nota, y tu decides. Borrar automaticamente aqui es como se pierden datos.

La base de datos solo trae los candidatos (mismo importe, direccion y ventana de
tiempo); quien decide cual es el mismo movimiento es este modulo.
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta

from app.compartido.tipos import TxStatus
from app.movimientos.dominio.entidades import Transaction

# ventana y tolerancia para considerar dos movimientos "el mismo"
CROSS_WINDOW = timedelta(hours=36)
CROSS_AMOUNT_TOLERANCE_CENTS = 0


def minuto_de(tx: Transaction) -> datetime | None:
    """El minuto en que ocurrio: dos avisos del mismo movimiento lo comparten."""
    return tx.occurred_at.replace(second=0, microsecond=0) if tx.occurred_at else None


def elegir_mellizo(tx: Transaction, candidatos: Iterable[Transaction]) -> Transaction | None:
    """El MISMO movimiento notificado dos veces, entre los candidatos.

    El BBVA manda dos correos por cada retiro en cajero, y solo uno de los dos
    trae numero de operacion. Como la huella corta en cuanto hay numero de
    operacion, los dos correos daban huellas distintas y el retiro se contaba
    dos veces.

    Criterio (los candidatos ya llegan filtrados): mismo importe, misma direccion,
    misma cuenta y el MISMO MINUTO. Dos gastos identicos al mismo minuto y en la
    misma cuenta no existen en la practica; dos notificaciones del mismo, todo el
    tiempo.

    La excepcion que obliga a hilar fino: si AMBOS traen numero de operacion y
    son distintos, son dos movimientos de verdad. Pasa con las transferencias
    del BCP: dos de S/400 a las 14:07 con operaciones 02992672 y 02998363.
    """
    for cand in candidatos:
        ambos_con_operacion = bool(tx.operation_number) and bool(cand.operation_number)
        if ambos_con_operacion and tx.operation_number != cand.operation_number:
            continue          # dos operaciones distintas: son dos movimientos
        return cand
    return None


def elegir_sospechoso(tx: Transaction, candidatos: Iterable[Transaction]) -> Transaction | None:
    """Un movimiento gemelo de otra cuenta u origen, entre los candidatos de la ventana."""
    for cand in candidatos:
        if cand.account_id == tx.account_id and cand.source == tx.source:
            continue
        # Con una ventana de 36 horas, "mismo importe" solo no basta: dos cafes
        # de S/2.40 en dos dias distintos se acusaban de ser el mismo gasto. Si
        # ambos dicen en que comercio fueron y NO coinciden, son dos gastos.
        if cand.merchant and tx.merchant and cand.merchant != tx.merchant:
            continue
        return cand
    return None


def marcar_mellizo(tx: Transaction, mellizo: Transaction) -> None:
    """Se guarda marcado como duplicado: no cuenta en ningun total y queda el rastro."""
    tx.status = TxStatus.duplicada
    tx.duplicate_of_id = mellizo.id
    tx.notes = (
        f"Mismo movimiento que #{mellizo.id}, notificado por dos correos "
        f"distintos ({mellizo.parser} y {tx.parser}). No cuenta en los totales."
    )


def marcar_sospecha(tx: Transaction, gemelo: Transaction) -> None:
    """Aqui NO se decide nada, solo se avisa; la ultima palabra es tuya."""
    tx.status = TxStatus.por_revisar
    tx.duplicate_of_id = gemelo.id
    tx.notes = (
        f"Posible duplicado del movimiento #{gemelo.id} "
        f"({gemelo.source.value}, mismo monto en +-36h). Revisa antes de contar los dos."
    )
