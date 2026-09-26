"""Vocabulario comun: lo que significa un movimiento en cualquier modulo.

Direccion, necesidad, estado, medio de pago y origen los usan movimientos,
clasificacion, correo, excel, analitica y seguimiento. Viven aqui para que ningun
modulo tenga que importar las entidades de otro solo para nombrar un valor.
"""
from __future__ import annotations

import enum


class Direction(str, enum.Enum):
    gasto = "gasto"
    ingreso = "ingreso"
    transferencia = "transferencia"


class Necessity(str, enum.Enum):
    """Sustituye a la nota libre "Gasto innecesario"."""

    esencial = "esencial"          # comida de casa, transporte al trabajo, servicios
    discrecional = "discrecional"  # salidas, antojos justificados
    evitable = "evitable"


class TxStatus(str, enum.Enum):
    confirmada = "confirmada"
    por_revisar = "por_revisar"    # baja confianza del parser o sin categoria
    duplicada = "duplicada"
    ignorada = "ignorada"


class PaymentMethod(str, enum.Enum):
    """Como se pago, que no es lo mismo que de que cuenta salio.

    Yape debita directo de la cuenta BCP y el BCP no manda un correo aparte por
    el yapeo. Asi que un yapeo es un cargo a BCP Debito pagado *por Yape*: la
    cuenta dice de donde sale el dinero, el medio dice por donde salio.

    Plin es lo mismo por el lado del BBVA. Se distinguen porque saber si pagas
    mas por Yape o por Plin dice de que cuenta esta saliendo tu dinero del dia
    a dia.
    """

    efectivo = "efectivo"
    debito = "debito"
    credito = "credito"
    yape = "yape"
    plin = "plin"
    transferencia = "transferencia"
    otro = "otro"


class Source(str, enum.Enum):
    gmail = "gmail"
    manual = "manual"
    excel = "excel"
