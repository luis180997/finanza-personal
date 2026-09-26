"""La papelera: recuperar tus decisiones sobre un movimiento borrado.

Si aun asi un movimiento con decisiones tuyas desaparece y su correo se vuelve a
procesar, vuelve con tus decisiones, sacadas de la papelera, no reclasificado.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

from app.compartido.dinero import to_amount
from app.compartido.tipos import Direction, Necessity, PaymentMethod, Source, TxStatus
from app.movimientos.dominio.entidades import Transaction, TransactionPapelera

# Lo que puedes cambiar desde la pantalla (TransactionPatch), en columnas.
CAMPOS_TUYOS = (
    "amount_cents", "currency", "direction", "occurred_at", "booking_date", "account_id",
    "payment_method", "category_id", "merchant", "description", "necessity",
    "status", "tags", "notes", "is_recurring",
)

# Columnas que apuntan a otra fila. Una categoria o cuenta borrada despues no puede
# impedir recuperar el resto: esas referencias se sueltan.
FORANEAS = (
    "account_id", "counter_account_id", "category_id", "email_id", "duplicate_of_id",
    "import_batch_id",
)

_FECHAHORA = {"occurred_at", "created_at", "updated_at", "user_edited_at"}
_ENUMS = {
    "direction": Direction, "payment_method": PaymentMethod, "necessity": Necessity,
    "status": TxStatus, "source": Source,
}


def convertir(campo: str, crudo):
    """Del JSON de la papelera (lo que guarda SQLite) al tipo del modelo."""
    if crudo is None:
        return None
    if campo in _FECHAHORA:
        return datetime.fromisoformat(str(crudo))
    if campo == "booking_date":
        return date.fromisoformat(str(crudo)[:10])
    if campo in _ENUMS:
        return _ENUMS[campo](crudo)
    if campo == "tags":
        return json.loads(crudo) if isinstance(crudo, str) else crudo
    if campo in ("is_recurring", "locked_by_user"):
        return bool(crudo)
    return crudo


def reaplicar_decisiones(tx: Transaction, fila: TransactionPapelera, ahora: datetime) -> None:
    """Devuelve a `tx` lo que decidiste sobre el movimiento que esta en la papelera."""
    datos = json.loads(fila.datos)
    for campo in CAMPOS_TUYOS:
        if campo in datos:
            setattr(tx, campo, convertir(campo, datos[campo]))
    tx.confidence = 1.0
    tx.locked_by_user = True
    tx.user_edited_at = convertir("user_edited_at", datos.get("user_edited_at")) or ahora


def reconstruir(fila: TransactionPapelera, id_libre: bool) -> Transaction:
    """El movimiento tal cual estaba. Conserva su id si nadie lo ha ocupado."""
    datos = json.loads(fila.datos)
    campos = {c: convertir(c, v) for c, v in datos.items() if c in Transaction.model_fields}
    if campos.get("id") is not None and not id_libre:
        campos.pop("id")
    return Transaction(**campos)


def huella_de(fila: TransactionPapelera) -> str | None:
    return json.loads(fila.datos).get("dedupe_hash")


def id_de(fila: TransactionPapelera) -> int | None:
    return json.loads(fila.datos).get("id")


def utc_iso(momento: datetime | None) -> str | None:
    """El trigger guarda CURRENT_TIMESTAMP, que es UTC pero sin zona: sin marcarla,
    el navegador lo leeria como hora de Lima y lo mostraria cinco horas corrido."""
    if momento is None:
        return None
    return (momento if momento.tzinfo else momento.replace(tzinfo=timezone.utc)).isoformat()


def para_listado(fila: TransactionPapelera, tx_actual_id: int | None) -> dict:
    """Como se muestra en la papelera. `tx_actual_id`: el movimiento volvio solo
    (se reproceso su correo) y restaurarlo lo contaria dos veces."""
    d = json.loads(fila.datos or "{}")
    return {
        "id": fila.id,
        "tx_id": fila.tx_id,
        "tx_actual_id": tx_actual_id,
        "borrado_en": utc_iso(fila.borrado_en),
        "origen": fila.source,
        "editado_por_usuario": fila.editado_por_usuario,
        "fecha": d.get("booking_date"),
        "monto": to_amount(d.get("amount_cents") or 0),
        "moneda": d.get("currency"),
        "direccion": d.get("direction"),
        "comercio": d.get("merchant") or d.get("merchant_raw") or d.get("description"),
        "categoria_id": d.get("category_id"),
        "notas": d.get("notes"),
    }
