"""Por que un movimiento esta esperando revision.

Un aviso que no dice que hacer no sirve de nada. "Confianza 30%" es un numero
que solo significa algo para quien escribio el codigo; "el correo no traia el
nombre del comercio" se entiende y se puede actuar sobre ello.

Cada motivo es una tupla (clave, texto, que_hacer). La clave permite filtrar y
agrupar sin depender del texto.

Es dominio puro: la moneda base y lo seguro que declara cada parser se reciben,
no se leen de la configuracion ni del catalogo de patrones.
"""
from __future__ import annotations

from collections.abc import Callable

from app.compartido.dinero import to_amount
from app.correo.dominio.dinero_propio import (
    NOTA_CASA_DE_CAMBIO,
    NOTA_ENVIO_PROPIO,
    motivo_no_es_gasto,
)
from app.clasificacion.dominio.entidades import Category
from app.movimientos.dominio.entidades import Transaction
from app.compartido.tipos import TxStatus

# Categorias que en realidad significan "no lo sabemos"
CAJONES = {"Sin clasificar", "Otros ingresos"}


def motivos(
    tx: Transaction,
    cat: Category | None,
    cuenta_nombre: str | None,
    *,
    moneda_base: str,
    confianza_del_parser: Callable[[str], float | None],
) -> list[dict]:
    """Devuelve la lista de razones por las que este movimiento pide atencion.

    `confianza_del_parser(id)`: lo seguro que declara ese parser al leer el correo.
    """
    razones: list[dict] = []

    # Va primero: mientras falte el importe en soles, los totales usan una cifra que
    # no es la que te cobraron.
    if tx.currency != moneda_base:
        operacion = f" {tx.operation_number}" if tx.operation_number else ""
        razones.append({
            "clave": "moneda_extranjera",
            "texto": f"El banco lo aviso en {tx.currency} ({to_amount(tx.amount_cents):.2f}) y el "
                     "correo no dice cuantos soles te cobro. Mientras tanto se suma como si "
                     "fueran soles.",
            "accion": f"Busca la operacion{operacion} en la app del banco y escribe aqui el "
                      "importe en soles.",
        })

    if tx.duplicate_of_id:
        razones.append({
            "clave": "duplicado",
            "texto": f"Se parece mucho al movimiento #{tx.duplicate_of_id}: mismo importe "
                     "y casi la misma hora, pero llego por otra via.",
            "accion": "Si son el mismo gasto, marca este como duplicado para que no "
                      "cuente dos veces. Si son dos gastos distintos, confirmalo.",
        })

    if tx.category_id is None or (cat and cat.name in CAJONES):
        if tx.parser and tx.parser.startswith(("yape_envio", "bbva_plin")):
            razones.append({
                "clave": "pago_a_persona",
                "texto": "Es un pago a una persona. El correo dice a quien, pero no para "
                         "que: puede ser el almuerzo, un prestamo o la cuota del gimnasio.",
                "accion": "Elige la categoria real. La proxima vez que le pagues a esa "
                          "misma persona, se acordara.",
            })
        else:
            razones.append({
                "clave": "sin_categoria",
                "texto": "Nadie supo en que categoria va: ni tus reglas, ni el historial "
                         "de este comercio, ni el diccionario de comercios conocidos.",
                "accion": "Elige una categoria. Queda aprendida para ese comercio.",
            })

    if not tx.merchant and not tx.merchant_raw:
        razones.append({
            "clave": "sin_comercio",
            "texto": "El correo no traia el nombre del comercio, asi que no hay nada con "
                     "lo que reconocerlo la proxima vez.",
            "accion": "Escribe el comercio a mano si lo recuerdas; sirve para que el "
                      "sistema lo aprenda.",
        })

    if tx.account_id is None:
        razones.append({
            "clave": "sin_cuenta",
            "texto": "No se pudo saber de que cuenta salio el dinero.",
            "accion": "Asignale una cuenta. Si es por los ultimos 4 digitos de la "
                      "tarjeta, registralos en la pantalla Cuentas y dejara de pasar.",
        })

    deduccion = motivo_no_es_gasto(tx.notes)
    if tx.direction.value == "transferencia" and deduccion == NOTA_ENVIO_PROPIO:
        razones.append({
            "clave": "envio_a_mi_mismo",
            "texto": "El dinero fue a un destinatario con tu mismo nombre, asi que se "
                     "tomo como un traspaso entre tus cuentas y NO cuenta como gasto.",
            "accion": "Si en realidad le pagaste a otra persona que se llama como tu, "
                      "cambialo a gasto.",
        })
    elif tx.direction.value == "transferencia" and deduccion == NOTA_CASA_DE_CAMBIO:
        razones.append({
            "clave": "casa_de_cambio",
            "texto": "El destinatario es una casa de cambio: comprar dolares no es "
                     "gastar, el dinero solo cambia de moneda. NO cuenta como gasto.",
            "accion": "Si esa transferencia fue para otra cosa, cambiala a gasto.",
        })
    elif tx.direction.value == "transferencia":
        razones.append({
            "clave": "transferencia",
            "texto": "Se registro como movimiento entre tus cuentas, asi que NO cuenta "
                     "como gasto.",
            "accion": "Si en realidad le pagaste a alguien, cambialo a gasto.",
        })

    if not razones and tx.confidence < 0.75:
        del_parser = confianza_del_parser(tx.parser) if tx.parser else None
        razones.append(motivo_confianza(tx, del_parser))

    return razones


def motivo_confianza(tx: Transaction, del_parser: float | None) -> dict:
    """`tx.confidence` mezcla dos cosas distintas; decir cual falla.

    Es el minimo de lo seguro que esta el parser al leer el correo y lo seguro
    que esta el clasificador al elegir categoria. Enseñar el numero combinado
    diciendo "el parser leyo mal" acusaba al parser de errores que no eran
    suyos, y dejaba al usuario comprobando un importe que estaba bien.

    `del_parser`: lo seguro que estaba el parser al LEER el correo, sin mezclar
    nada mas (None si no hay parser o no se conoce).
    """
    pct = int(tx.confidence * 100)

    if del_parser is not None and del_parser >= 0.75:
        return {
            "clave": "categoria_dudosa",
            "texto": f"El importe y la fecha se leyeron bien del correo. Lo dudoso es "
                     f"la categoria ({pct}%).",
            "accion": "Elige la categoria que le corresponde; queda aprendida para "
                      "ese comercio.",
        }
    return {
        "clave": "lectura_dudosa",
        "texto": f"El correo se leyo con poca seguridad ({pct}%): puede que el importe "
                 "o la fecha no sean los del correo.",
        "accion": "Comprueba el importe y la fecha contra el correo original.",
    }


def resumen_motivo(razones: list[dict]) -> str:
    """Una linea corta para la cabecera de la ficha."""
    if not razones:
        return "Pendiente de confirmar"
    principal = razones[0]["clave"]
    etiquetas = {
        "moneda_extranjera": "Cobrado en otra moneda: falta el importe en soles",
        "duplicado": "Podria estar contado dos veces",
        "pago_a_persona": "Pago a una persona, sin saber para que",
        "sin_categoria": "Falta elegir la categoria",
        "sin_comercio": "Sin comercio identificable",
        "sin_cuenta": "Sin cuenta identificada",
        "envio_a_mi_mismo": "Enviado a ti mismo, no cuenta como gasto",
        "casa_de_cambio": "Casa de cambio, no cuenta como gasto",
        "transferencia": "Movimiento entre cuentas",
        "categoria_dudosa": "Falta afinar la categoria",
        "lectura_dudosa": "El correo se leyo con poca seguridad",
    }
    return etiquetas.get(principal, "Pendiente de confirmar")


def necesita_revision(tx: Transaction) -> bool:
    return tx.status == TxStatus.por_revisar
