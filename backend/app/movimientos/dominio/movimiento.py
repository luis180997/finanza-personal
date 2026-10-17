"""Lo que se le puede hacer a un movimiento. Reglas puras: sin base de datos.

Un movimiento tiene dos capas:

  * los HECHOS que trae el banco (importe, fecha, comercio, numero de operacion),
    que la app puede volver a leer del correo cuantas veces haga falta;
  * TUS DECISIONES (categoria, necesidad, notas, estado y cualquier campo que
    corrijas), que no se pueden volver a deducir de ningun sitio.

La app puede regenerar la primera capa; la segunda solo puede conservarla. Por eso
lo que registras o corriges queda protegido (`locked_by_user`) y la base de datos
rechaza borrarlo (trigger en plataforma/db.py).
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.compartido.comercio import normalize_merchant
from app.compartido.corte import FECHA_INICIO_AUTOMATIZADO, FECHA_INICIO_AUTOMATIZADO_TEXTO
from app.compartido.dinero import to_cents
from app.compartido.errores import DatoInvalido
from app.compartido.tipos import Direction, Necessity, PaymentMethod, Source, TxStatus
from app.movimientos.dominio.entidades import AccountType, Transaction
from app.movimientos.dominio.huella import build_hash

# Si no dices el medio de pago, se deduce del tipo de cuenta. Es lo correcto en
# el 99% de las altas manuales (efectivo), y siempre se puede corregir.
MEDIO_POR_TIPO = {
    AccountType.efectivo: PaymentMethod.efectivo,
    AccountType.debito: PaymentMethod.debito,
    AccountType.credito: PaymentMethod.credito,
    AccountType.billetera: PaymentMethod.yape,   # Yape o Plin: se ajusta a mano
}


# --------------------------------------------------------------------------- alta
def alta_manual(
    alta: dict,
    *,
    local: datetime,
    cuenta_id: int | None,
    medio: PaymentMethod | None,
    ahora_utc: datetime,
) -> Transaction:
    """Un movimiento que registras tu: entra confirmado y con toda la confianza.

    La huella lleva la hora exacta del alta, para poder anotar dos cafes iguales el
    mismo dia sin que el segundo desaparezca como duplicado.
    """
    merchant = normalize_merchant(alta["merchant"]) or (alta["merchant"] or None)
    amount_cents = to_cents(alta["amount"])
    return Transaction(
        occurred_at=local,
        booking_date=local.date(),
        amount_cents=amount_cents,
        currency=alta["currency"],
        direction=alta["direction"],
        account_id=cuenta_id,
        counter_account_id=alta["counter_account_id"],
        payment_method=medio,
        category_id=alta["category_id"],
        merchant=merchant,
        merchant_raw=alta["merchant"],
        description=alta["description"],
        necessity=alta["necessity"],
        tags=alta["tags"],
        notes=alta["notes"],
        is_recurring=alta["is_recurring"],
        source=Source.manual,
        status=TxStatus.confirmada,
        confidence=1.0,
        dedupe_hash=build_hash(
            source="manual",
            operation_number=None,
            occurred_at=local,
            amount_cents=amount_cents,
            merchant=merchant,
            account_id=cuenta_id,
            external_id=f"manual-{ahora_utc.timestamp()}",
        ),
    )


# --------------------------------------------------------------------- proteccion
def proteger(tx: Transaction, ahora: datetime) -> None:
    """Marca el movimiento como tuyo. Se llama en cada alta, edicion o revision."""
    tx.locked_by_user = True
    tx.user_edited_at = ahora
    tx.updated_at = ahora


def descartar(tx: Transaction, ahora: datetime) -> None:
    """Quitar un movimiento que viene del banco o del Excel.

    Queda como ignorado (no cuenta en ningun total ni aparece en los listados) y
    protegido. No se borra: su correo sigue archivado, y si la fila desapareciera
    el siguiente sincronizado lo volveria a crear, clasificado otra vez desde cero.
    """
    tx.status = TxStatus.ignorada
    proteger(tx, ahora)


def se_borra_de_verdad(tx: Transaction) -> bool:
    """Solo tus registros manuales se borran; lo del banco o del Excel se descarta."""
    return tx.source == Source.manual


def desproteger_para_borrar(tx: Transaction) -> None:
    """Solo para tus registros manuales, cuando los borras a proposito.

    Se quita la proteccion justo antes de borrar (sin eso el trigger rechaza el
    borrado) y el trigger deja la copia en la papelera por si fue un error.
    """
    tx.locked_by_user = False


def soltar_duplicado(otro: Transaction, borrado_id: int) -> None:
    """`otro` estaba marcado como duplicado de un movimiento que se borra.

    Sin pisar la nota que ya hubiera: hay notas que el sistema reconoce por su
    principio para saber que un movimiento no cuenta como gasto (envio a ti
    mismo, casa de cambio). El aviso va detras.
    """
    aviso = f"El movimiento #{borrado_id} del que era duplicado se borro."
    otro.duplicate_of_id = None
    otro.notes = f"{otro.notes}\n{aviso}" if otro.notes else aviso


# ------------------------------------------------------------------- fechas y corte
def a_hora_local(momento: datetime, zona: ZoneInfo) -> datetime:
    """Una fecha sin zona se toma como hora local."""
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=zona)
    return momento.astimezone(zona)


def antes_del_corte(tx: Transaction) -> bool:
    """Ningun movimiento del correo anterior a la frontera entra en transaction:
    hasta entonces la fuente de verdad es el Excel (CLAUDE.md, regla 3)."""
    return tx.source == Source.gmail and tx.booking_date < FECHA_INICIO_AUTOMATIZADO


# --------------------------------------------------------------------- categoria
def quitar_categoria(tx: Transaction, destino_id: int | None) -> None:
    """Su categoria desaparece: pasa a `destino_id` o se queda sin categoria.

    Sin categoria no puede seguir como confirmado: no apareceria en ningun sitio
    para volver a clasificarlo. Con destino, sigue como estaba (y si era una
    decision tuya, sigue protegida).
    """
    if destino_id is not None:
        tx.category_id = destino_id
        return
    tx.category_id = None
    if tx.status == TxStatus.confirmada:
        tx.status = TxStatus.por_revisar


# --------------------------------------------------------------------- moneda
FALTA_IMPORTE_EN_SOLES = (
    "Este cobro llego en otra moneda y todavia no tiene su importe en soles. Escribelo "
    "antes de confirmarlo: si no, se sumaria como si fueran soles."
)


def falta_importe_en_soles(tx: Transaction, moneda_base: str) -> bool:
    """El BCP avisa algunos cobros en dolares ("$ 8.85") y los debita en soles, pero el
    correo no dice cuantos. Hasta que escribas los soles no puede quedar confirmado:
    los totales lo sumarian como si fueran soles. Una transferencia no, porque no
    cuenta como gasto ni como ingreso."""
    return tx.currency != moneda_base and tx.direction != Direction.transferencia


# --------------------------------------------------------------------- correccion
def corregir(tx: Transaction, cambios: dict, zona: ZoneInfo) -> None:
    """Aplica lo que corriges a mano. `cambios` trae solo los campos que mandaste."""
    if "amount" in cambios and cambios["amount"] is not None:
        tx.amount_cents = to_cents(cambios.pop("amount"))
    cambios.pop("amount", None)
    if "occurred_at" in cambios and cambios["occurred_at"]:
        local = a_hora_local(cambios.pop("occurred_at"), zona)
        # Regla 3 de CLAUDE.md: un movimiento del correo no puede quedar antes de la
        # frontera; hasta esa fecha la unica fuente de verdad es el Excel.
        if tx.source == Source.gmail and local.date() < FECHA_INICIO_AUTOMATIZADO:
            raise DatoInvalido(
                f"Un movimiento del correo no puede quedar antes del "
                f"{FECHA_INICIO_AUTOMATIZADO_TEXTO}: hasta esa fecha la fuente de verdad "
                "es el Excel."
            )
        tx.occurred_at = local
        tx.booking_date = local.date()
    if cambios.get("merchant"):
        cambios["merchant"] = normalize_merchant(cambios["merchant"]) or cambios["merchant"]
    if "tags" in cambios and cambios["tags"] is None:
        cambios["tags"] = []            # la columna no admite nulo: vaciar es lista vacia

    for k, v in cambios.items():
        setattr(tx, k, v)


def confirmar_correccion(
    tx: Transaction, categoria_elegida: int | None, estado_elegido: TxStatus | None,
    moneda_base: str,
) -> None:
    """Se llama despues de `corregir`: si en la misma edicion escribiste los soles,
    el movimiento ya esta en la moneda base."""
    sin_soles = falta_importe_en_soles(tx, moneda_base)
    if estado_elegido == TxStatus.confirmada and sin_soles:
        raise DatoInvalido(FALTA_IMPORTE_EN_SOLES)

    # Corregir a mano equivale a confirmar: asi la memoria de comercio aprende.
    # Salvo que quien edita diga explicitamente en que estado lo deja: la
    # bandeja de revision manda `status` para que la ficha no se desvanezca en
    # cuanto eliges categoria, sin darte tiempo a marcar la necesidad. Un cobro
    # sin sus soles se queda en la bandeja aunque elijas categoria.
    if categoria_elegida is not None and estado_elegido is None:
        tx.status = TxStatus.por_revisar if sin_soles else TxStatus.confirmada

    # Lo que toca una persona deja de ser dudoso, aunque siga en la bandeja: si
    # no, al elegir categoria el movimiento se quedaba en 0.3 y la propia ficha
    # respondia "lo dudoso es la categoria (30%)" sobre la que acababas de poner.
    if categoria_elegida is not None or estado_elegido == TxStatus.confirmada:
        tx.confidence = 1.0


def hereda_necesidad(
    tx: Transaction, categoria_elegida: int | None, mandaste_necesidad: bool,
) -> bool:
    """Al elegir categoria hereda su necesidad por defecto, salvo que ya tuviera
    una. Si no, quedarse en la bandeja para marcar la necesidad obligaba a tocar
    dos desplegables para decir algo que la categoria ya implica."""
    return categoria_elegida is not None and tx.necessity is None and not mandaste_necesidad


def aplicar_lote(
    tx: Transaction,
    category_id: int | None,
    necessity: Necessity | None,
    status: TxStatus | None,
    moneda_base: str,
) -> bool:
    """Confirmar, ignorar o marcar duplicado desde la bandeja tambien es decidir.

    Devuelve False si no lo pudo confirmar porque le falta el importe en soles: se
    queda en la bandeja, con la categoria y la necesidad que elegiste.
    """
    if category_id is not None:
        tx.category_id = category_id
    if necessity is not None:
        tx.necessity = necessity
    tx.confidence = 1.0
    estado = status or TxStatus.confirmada
    if estado == TxStatus.confirmada and falta_importe_en_soles(tx, moneda_base):
        tx.status = TxStatus.por_revisar
        return False
    tx.status = estado
    return True
