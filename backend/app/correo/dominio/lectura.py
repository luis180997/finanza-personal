"""De correo bancario a movimiento: las reglas, sin base de datos.

El caso de uso (aplicacion/sincronizacion.py) trae el correo, las cuentas y el
nombre del titular; aqui se decide que movimiento sale de ahi.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.compartido.comercio import normalize_merchant
from app.compartido.corte import (
    ANIO_MAX,
    ANIO_MIN,
    FECHA_INICIO_AUTOMATIZADO,
    FECHA_INICIO_AUTOMATIZADO_TEXTO,
)
from app.compartido.dinero import to_cents
from app.compartido.tipos import Direction, PaymentMethod, Source, TxStatus
from app.correo.dominio import dinero_propio
from app.correo.dominio.correo import ParsedTx, RawEmail
from app.correo.dominio.entidades import EmailMessage, ParseStatus
from app.movimientos.dominio.entidades import Account, Transaction
from app.movimientos.dominio.huella import build_hash

# No se procesan correos anteriores a 2022 (requisito explicito).
ANIO_PRIMER_CORREO = 2022

# Por que un correo reconocido no genera movimiento. Se anota en el propio correo:
# se ve en la pantalla Correo, y la siguiente sincronizacion ya no lo procesa. Antes
# lo reprocesaba cada 15 minutos, sumando un "duplicado" fantasma cada vez y un uso
# mas a la regla que lo clasificaba.
NOTAS_SIN_MOVIMIENTO = {
    "duplicado": "No genera movimiento: es el mismo que ya trajo otro correo.",
    "corte": (
        f"No genera movimiento: es anterior al {FECHA_INICIO_AUTOMATIZADO_TEXTO}, "
        "cuando aun mandaba el Excel."
    ),
}

# Cuanto texto del correo se archiva.
MAX_CUERPO = 20000


def recibido_antes_del_corte(recibido: datetime | None) -> bool:
    """Hasta la frontera el Excel es la fuente de verdad unica: los correos anteriores
    se quedan archivados, pero no generan movimiento."""
    fecha: date | None = recibido.date() if recibido else None
    return bool(fecha) and fecha < FECHA_INICIO_AUTOMATIZADO


def resolver_cuenta(cuentas: Iterable[Account], parsed: ParsedTx) -> Account | None:
    """Elige la cuenta: primero por ultimos 4 digitos, luego por sugerencia del
    parser, luego por banco."""
    cuentas = list(cuentas)
    if parsed.last4:
        for c in cuentas:
            if c.last4 and c.last4 == parsed.last4:
                return c
    if parsed.account_hint:
        for c in cuentas:
            if c.name.lower() == parsed.account_hint.lower():
                return c
    if parsed.bank:
        candidatas = [c for c in cuentas if c.bank == parsed.bank]
        if candidatas:
            return candidatas[0]
    return None


def transaccion_desde_correo(
    parsed: ParsedTx,
    *,
    cuenta: Account | None,
    email: EmailMessage | None,
    source: Source,
    zona: ZoneInfo,
    ahora: datetime,
) -> Transaction:
    """El movimiento que describe el correo, todavia sin clasificar."""
    ocurrido = parsed.occurred_at or ahora
    # Una fecha imposible (el patron capturo otro numero) se cambia por la de
    # llegada del correo: un movimiento del año 1 estiraba el historial a miles de meses.
    if not ANIO_MIN <= ocurrido.year <= ANIO_MAX and email is not None and email.received_at:
        ocurrido = email.received_at
    if ocurrido.tzinfo is None:
        ocurrido = ocurrido.replace(tzinfo=zona)
    local = ocurrido.astimezone(zona)

    merchant = normalize_merchant(parsed.merchant_raw)
    amount_cents = to_cents(parsed.amount)

    tx = Transaction(
        occurred_at=local,
        booking_date=local.date(),
        amount_cents=amount_cents,
        currency=parsed.currency,
        direction=Direction(parsed.direction),
        account_id=cuenta.id if cuenta else None,
        payment_method=PaymentMethod(parsed.payment_method) if parsed.payment_method else None,
        merchant=merchant,
        merchant_raw=parsed.merchant_raw,
        description=parsed.description,
        operation_number=parsed.operation_number,
        source=source,
        status=TxStatus.confirmada,
        confidence=parsed.confidence,
        parser=parsed.parser,
        email_id=email.id if email else None,
        dedupe_hash=build_hash(
            source=source.value,
            operation_number=parsed.operation_number,
            occurred_at=local,
            amount_cents=amount_cents,
            merchant=merchant,
            account_id=cuenta.id if cuenta else None,
            # SIN external_id a proposito: meter el id del correo hacia que dos
            # correos del mismo movimiento (el BBVA manda dos por cada retiro)
            # dieran huellas distintas y el gasto se contara dos veces.
        ),
    )
    if cuenta is None:
        tx.confidence = min(tx.confidence, 0.6)
    return tx


def apartar_dinero_propio(
    tx: Transaction,
    parsed: ParsedTx,
    email: EmailMessage | None,
    titular: Callable[[], list[str]],
) -> None:
    """Lo que parece gasto pero sigue siendo tu dinero pasa a transferencia.

    Va antes de clasificar porque el categorizador elige entre categorias de gasto
    o de ingreso segun la direccion. `titular()` solo se consulta si hace falta.
    """
    # Mover dinero de una cuenta tuya a otra tuya no es gastarlo. El correo del
    # BCP es identico al de un pago a un tercero, asi que lo unico que los
    # distingue es que el destinatario se llama como tu.
    if (
        tx.direction == Direction.gasto
        and tx.payment_method in (PaymentMethod.transferencia, PaymentMethod.yape, PaymentMethod.plin)
        and email is not None
        and dinero_propio.es_envio_a_uno_mismo(email.body_text, parsed.merchant_raw, titular())
    ):
        tx.direction = Direction.transferencia
        tx.notes = dinero_propio.NOTA_ENVIO_PROPIO

    # Comprar dolares tampoco es gastar. Aqui no hay que deducir nada: la casa
    # de cambio se llama por su nombre y la lista la confirmo el usuario.
    elif tx.direction == Direction.gasto and dinero_propio.es_casa_de_cambio(tx.merchant):
        tx.direction = Direction.transferencia
        tx.notes = dinero_propio.NOTA_CASA_DE_CAMBIO


def contexto_de_clasificacion(
    email: EmailMessage | None, cuenta: Account | None, parsed: ParsedTx,
) -> dict:
    """Lo que las reglas del usuario pueden mirar ademas del propio movimiento."""
    return {
        "subject": email.subject if email else "",
        "sender": email.sender if email else "",
        "account_name": cuenta.name if cuenta else "",
        "category_hint": parsed.category_hint,
    }


def revisar_si_otra_moneda(tx: Transaction, moneda_base: str) -> None:
    """El BCP avisa algunos cobros en dolares ("$ 8.85") y los debita en soles, pero el
    correo no dice cuantos. Ni se da por bueno ni se inventa un tipo de cambio: va a
    Por revisar para que escribas los soles que te cobraron (decision del 13/09/2026).
    Una transferencia no, porque no cuenta como gasto ni como ingreso."""
    if tx.currency != moneda_base and tx.direction != Direction.transferencia:
        tx.status = TxStatus.por_revisar


def correo_archivado(raw: RawEmail, parsed: ParsedTx | None, motivo: str | None) -> EmailMessage:
    return EmailMessage(
        gmail_id=raw.gmail_id,
        thread_id=raw.thread_id,
        sender=raw.sender,
        subject=raw.subject,
        received_at=raw.received_at,
        snippet=raw.snippet,
        body_text=raw.body[:MAX_CUERPO],
        parse_status=ParseStatus.parseado if parsed else ParseStatus.sin_parser,
        parser=parsed.parser if parsed else None,
        error=motivo,
    )


def como_correo(email: EmailMessage) -> RawEmail:
    """Un correo archivado, listo para volver a pasar por los parsers."""
    return RawEmail(
        gmail_id=email.gmail_id,
        sender=email.sender,
        subject=email.subject,
        body=email.body_text,
        received_at=email.received_at,
        thread_id=email.thread_id,
        snippet=email.snippet,
    )


def vaciar_cuerpo(email: EmailMessage) -> None:
    """Se conserva la ficha (gmail_id, remitente, asunto, fecha): es lo que impide
    reprocesar el mismo correo. Lo que se borra es el contenido, que es lo sensible."""
    email.body_text = ""
    email.snippet = ""
