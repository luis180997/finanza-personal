"""La huella de un movimiento: lo que lo identifica aunque llegue dos veces."""
from __future__ import annotations

import hashlib


def build_hash(
    *,
    source: str,
    operation_number: str | None,
    occurred_at,
    amount_cents: int,
    merchant: str | None,
    account_id: int | None,
    external_id: str | None = None,
) -> str:
    """Huella de un MOVIMIENTO, no del correo que lo trajo.

    Es una distincion que costo un duplicado real: el BBVA manda DOS correos
    por un mismo retiro en cajero (la "Constancia de Retiro" y "Tu operacion en
    nuestros cajeros"). Antes se metia el id del correo en la huella, asi que
    dos correos distintos daban huellas distintas y el retiro se contaba dos
    veces. El id del correo no pinta nada aqui: la idempotencia por correo ya
    la garantiza `EmailMessage.gmail_id`, que es unico.

    Se usa la hora al MINUTO, no solo la fecha. Dos retiros del mismo importe el
    mismo dia son perfectamente posibles; a la misma hora y minuto, no.

    `external_id` sobrevive solo para las altas manuales, donde SI se quiere
    poder anotar dos cafes iguales el mismo dia sin que el segundo desaparezca.
    """
    if operation_number:
        key = f"op|{operation_number}|{amount_cents}"
    elif external_id:
        key = f"ext|{external_id}"
    else:
        momento = occurred_at.strftime("%Y-%m-%dT%H:%M") if occurred_at else "?"
        key = f"h|{source}|{momento}|{amount_cents}|{merchant or ''}|{account_id or ''}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
