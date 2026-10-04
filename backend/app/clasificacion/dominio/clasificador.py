"""Clasificacion automatica en cascada: las reglas de la decision.

Se prueban 4 capas en orden y gana la primera que responde. Cada capa devuelve
tambien cuanta confianza aporta, porque de eso depende si el movimiento entra
como `confirmada` o cae a la cola `por_revisar`.

  1. REGLAS DEL USUARIO   -> deterministas, prioridad ascendente. Mandan siempre.
  2. MEMORIA DE COMERCIO  -> "la ultima vez que gaste en 'rappi' lo pusiste en
                             Delivery". Aprende de tus propias correcciones.
  3. DICCIONARIO SEMILLA  -> comercios peruanos frecuentes, para el arranque en frio.
  4. FALLBACK             -> "Sin clasificar" + revision manual.

Quien recorre las capas es el caso de uso (aplicacion/clasificar.py), porque cada
una necesita datos de la base. Aqui vive lo que no la necesita.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.clasificacion.dominio.entidades import Rule
from app.compartido.tipos import Direction, Necessity, TxStatus
from app.movimientos.dominio.entidades import Transaction

UMBRAL_REVISION = 0.75


@dataclass
class Clasificacion:
    category_id: int | None
    necessity: Necessity | None
    origen: str          # regla | memoria | diccionario | parser | direccion | ninguno | usuario
    confianza: float
    rule_id: int | None = None


def categoria_por_defecto(direccion: Direction) -> str:
    """El cajon donde cae lo que ninguna capa reconoce."""
    if direccion == Direction.ingreso:
        return "Otros ingresos"
    if direccion == Direction.transferencia:
        return "Entre cuentas propias"
    return "Sin clasificar"


def por_regla(regla: Rule) -> Clasificacion:
    return Clasificacion(
        category_id=regla.set_category_id,
        necessity=regla.set_necessity,
        origen="regla",
        confianza=1.0,
        rule_id=regla.id,
    )


def por_memoria(category_id: int, necessity: Necessity | None, veces: int) -> Clasificacion:
    """Cuantas mas veces elegiste esa categoria para el comercio, mas confianza."""
    return Clasificacion(
        category_id=category_id,
        necessity=necessity,
        origen="memoria",
        confianza=min(0.98, 0.80 + 0.05 * veces),
    )


def texto_para_diccionario(tx: Transaction) -> str:
    return f"{tx.merchant or ''} {tx.merchant_raw or ''} {tx.description or ''}".lower()


def sin_clasificar(category_id: int | None) -> Clasificacion:
    return Clasificacion(category_id=category_id, necessity=None, origen="ninguno", confianza=0.3)


def de_un_protegido(tx: Transaction) -> Clasificacion:
    """Un movimiento protegido conserva lo que decidiste (CLAUDE.md, regla 1)."""
    return Clasificacion(tx.category_id, tx.necessity, "usuario", 1.0)


def aplicar_resultado(tx: Transaction, c: Clasificacion) -> None:
    """Escribe la clasificacion en el movimiento y decide si necesita revision."""
    tx.category_id = c.category_id
    if tx.necessity is None:
        tx.necessity = c.necessity

    confianza_total = min(tx.confidence, c.confianza)
    tx.confidence = round(confianza_total, 2)
    if confianza_total < UMBRAL_REVISION or c.origen == "ninguno":
        tx.status = TxStatus.por_revisar
