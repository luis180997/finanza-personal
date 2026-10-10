"""Del estado de cuenta (y de los correos) al libro de operaciones.

`del_estado` traduce cada fila de un estado ya validado en una `Operacion`.
`del_correo` hace lo mismo con un evento de correo. `emparejan` decide si una
operacion del correo y una del estado son la misma.

REGLA: un codigo que no se conoce NO se ignora: se lanza `FilaDesconocida` y el
estado no se importa. Y cada estado tiene que cuadrar en efectivo: lo que suman
sus operaciones es lo que cambiaron la caja y el deposito asegurado segun el
propio documento (`cuadre_de_efectivo`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.inversiones.dominio import calendario
from app.inversiones.dominio.correo_hapi import EventoHapi, TipoCorreo
from app.inversiones.dominio.entidades import (
    EstadoOperacion, FuenteOperacion, Operacion, TipoOperacion,
)
from app.inversiones.dominio.estado_cuenta import EstadoDeCuenta, Movimiento, Seccion
from app.inversiones.dominio.validacion import simbolo_de

MICRO = 1_000_000
_T = TipoOperacion
_PROCESADORES_DE_DEPOSITOS = ("HAPI", "RAPYD")
# Precio por accion: el del correo y el del estado coinciden hasta el centavo.
_TOLERANCIA_PRECIO_MICRO = 10_000


class FilaDesconocida(ValueError):
    """Una fila del estado de cuenta que no se sabe traducir."""


def micro(valor: Decimal | None) -> int | None:
    return None if valor is None else int((valor * MICRO).to_integral_value())


def cents(valor: Decimal | None) -> int | None:
    return None if valor is None else int((valor * 100).to_integral_value())


@dataclass
class FilaOficial:
    """Una operacion sacada del estado, con lo que hace falta para conciliarla."""

    op: Operacion
    pendiente: bool            # ejecutada sin liquidar al cierre: sin fecha de liquidacion
    descripcion: str


def _oficial(**campos) -> Operacion:
    return Operacion(estado=EstadoOperacion.oficial, fuente=FuenteOperacion.estado_cuenta, **campos)


def del_estado(estado: EstadoDeCuenta, simbolos: dict[str, str]) -> list[FilaOficial]:
    filas: list[FilaOficial] = []
    for m in estado.movimientos:
        op = _de_movimiento(m, simbolos)
        if op is not None:
            pendiente = m.seccion is Seccion.pendientes
            filas.append(FilaOficial(op, pendiente=pendiente, descripcion=m.descripcion))
    filas = _juntar_retenciones(filas)
    for b in estado.barrido:
        if b.actividad == "DIV":               # interes del deposito asegurado
            filas.append(FilaOficial(
                _oficial(tipo=_T.interes, fecha=b.fecha, monto_cents=b.importe_cents,
                         nombre="Deposito asegurado (FDIC)"),
                pendiente=False, descripcion="DIV REINV",
            ))
    return filas


def _juntar_retenciones(filas: list[FilaOficial]) -> list[FilaOficial]:
    """Apex a veces pone la retencion de un dividendo en una fila propia (solo
    debito). Se suma al dividendo del mismo valor y dia: es un solo pago."""
    def es_retencion(f: FilaOficial) -> bool:
        return f.op.tipo is _T.dividendo and f.op.monto_cents == 0 and f.op.retencion_cents > 0

    resultado = [f for f in filas if not es_retencion(f)]
    for f in filas:
        if not es_retencion(f):
            continue
        destino = next((g for g in resultado if g.op.tipo is _T.dividendo and g.op.monto_cents > 0
                        and g.op.fecha == f.op.fecha and g.op.nombre == f.op.nombre), None)
        if destino is None:
            resultado.append(f)
        else:
            destino.op.retencion_cents += f.op.retencion_cents
    return resultado


def _de_movimiento(m: Movimiento, simbolos: dict[str, str]) -> Operacion | None:
    simbolo = simbolo_de(m, simbolos)
    valor = {"simbolo": simbolo if simbolo != m.descripcion else None, "nombre": m.descripcion}
    detalle = " ".join(m.detalle)

    if m.seccion in (Seccion.compraventa, Seccion.pendientes) and m.codigo in ("BOUGHT", "SOLD"):
        if m.es_split:
            return _oficial(tipo=_T.split, fecha=fecha_del_split(m), fecha_liquidacion=m.fecha,
                            cantidad_micro=micro(m.cantidad), **valor)
        compra = m.codigo == "BOUGHT"
        importe = m.debito_cents if compra else m.credito_cents
        bruto = round(m.cantidad * m.precio * 100)
        comun = {
            "tipo": _T.compra if compra else _T.venta,
            "cantidad_micro": micro(m.cantidad), "precio_micro": micro(m.precio),
            "monto_cents": -importe if compra else importe,
            "comision_cents": importe - bruto if compra else bruto - importe,
            **valor,
        }
        if m.seccion is Seccion.pendientes:
            return _oficial(fecha=m.fecha, **comun)
        return _oficial(
            fecha=calendario.operacion_desde_liquidacion(m.fecha), fecha_estimada=True,
            fecha_liquidacion=m.fecha, **comun,
        )

    # Se decide por el codigo y no por la seccion: Apex a veces pone un dividendo
    # atrasado en "Funds Paid and Received", y su retencion como una fila aparte
    # con solo debito.
    if m.seccion is not Seccion.pendientes and m.codigo in ("DIVIDEND", "SUB PAY"):
        return _oficial(
            tipo=_T.dividendo, fecha=m.fecha, monto_cents=m.credito_cents,
            retencion_cents=m.retencion_cents + m.debito_cents,
            nota="Pago sustitutivo: la accion estaba prestada" if m.codigo == "SUB PAY" else None,
            **valor,
        )
    if m.seccion is not Seccion.pendientes and m.codigo == "NRA":
        return _oficial(tipo=_T.ajuste_impuesto, fecha=m.fecha,
                        monto_cents=m.credito_cents - m.debito_cents - m.retencion_cents, **valor)

    if m.seccion is Seccion.fondos:
        if "XFER" in m.descripcion:            # caja <-> prestamo de valores: interno
            return None
        if m.codigo == "TOU":
            return _oficial(tipo=_T.cripto_salida, fecha=m.fecha, monto_cents=-m.debito_cents,
                            nombre="Transferencia a cripto")
        if m.codigo == "TIN":
            return _oficial(tipo=_T.cripto_entrada, fecha=m.fecha, monto_cents=m.credito_cents,
                            nombre="Transferencia desde cripto")
        if m.codigo == "JOURNAL" and any(p in detalle for p in _PROCESADORES_DE_DEPOSITOS):
            if "Journal from" in m.descripcion:
                return _oficial(tipo=_T.deposito, fecha=m.fecha, monto_cents=m.credito_cents,
                                nombre="Deposito")
            if "Journal to" in m.descripcion:
                return _oficial(tipo=_T.retiro, fecha=m.fecha, monto_cents=-m.debito_cents,
                                nombre="Retiro")

    if m.seccion is Seccion.valores and m.codigo == "JOURNAL" and "TYPE" in detalle:
        return None                            # prestamo de valores: entra y sale, suma cero

    raise FilaDesconocida(f"{m.seccion.value}: {m.codigo} {m.fecha} {m.descripcion} ({detalle})")


def fecha_del_split(m: Movimiento) -> date:
    """El dia en que el split cambia el precio: el primer dia de bolsa tras el pago.

    El estado lo anota unos dias despues (pago un viernes, fila el martes), pero
    desde el dia siguiente al pago el precio ya cotiza dividido. Anotarlo tarde
    valoraba las acciones de antes al precio de despues: una caida falsa de un dia.
    La fila del estado queda como fecha de liquidacion: es la que cuenta al cuadrar
    con el estado de ese mes.
    """
    pago = next((re.search(r"PAY (\d\d/\d\d/\d\d)", d) for d in m.detalle if "PAY " in d), None)
    if pago is None:
        return m.fecha
    efectivo = calendario.habiles_despues(datetime.strptime(pago.group(1), "%m/%d/%y").date(), 1)
    return min(efectivo, m.fecha)


def cuadre_de_efectivo(estado: EstadoDeCuenta, filas: list[FilaOficial]) -> int:
    """Diferencia (centavos) entre lo que suman las operaciones liquidadas del mes y
    lo que cambiaron caja + deposito asegurado segun el documento. Debe ser 0."""
    caja_ini, caja_fin = estado.portada["caja"]
    fdic_ini, fdic_fin = estado.portada.get("fdic", (0, 0))
    esperado = (caja_fin + fdic_fin) - (caja_ini + fdic_ini)
    suma = sum(f.op.monto_cents - f.op.retencion_cents for f in filas if not f.pendiente)
    return suma - esperado


# ----------------------------------------------------------------------------- correo


def del_correo(evento: EventoHapi) -> Operacion | None:
    """La operacion provisional que trae un correo, o None si no trae ninguna."""
    recibido_utc = evento.recibido.astimezone(timezone.utc).replace(tzinfo=None)
    dia_ny = evento.recibido.astimezone(calendario.NUEVA_YORK).date()
    comun = {
        "estado": EstadoOperacion.provisional, "fuente": FuenteOperacion.correo,
        "correo_id": evento.message_id, "ejecutada_at": recibido_utc,
    }
    if evento.tipo is TipoCorreo.ejecutada:
        compra = evento.lado == "compra"
        total = cents(evento.total)
        return Operacion(
            tipo=_T.compra if compra else _T.venta, simbolo=evento.ticker, nombre=evento.ticker,
            fecha=calendario.dia_de_bolsa(evento.recibido),
            cantidad_micro=micro(evento.cantidad), precio_micro=micro(evento.precio),
            monto_cents=-total if compra else total, comision_cents=cents(evento.comision),
            nota=evento.tipo_orden, **comun,
        )
    if evento.tipo is TipoCorreo.dividendo:
        return Operacion(
            tipo=_T.dividendo, simbolo=evento.ticker, nombre=evento.ticker,
            fecha=evento.fecha_pago or dia_ny, monto_cents=cents(evento.monto),
            nota="Neto: el bruto y la retencion llegan con el estado de cuenta", **comun,
        )
    if evento.tipo is TipoCorreo.retiro:
        return Operacion(
            tipo=_T.retiro, fecha=dia_ny, monto_cents=-cents(evento.monto),
            comision_cents=cents(evento.costo), nombre="Retiro", **comun,
        )
    if evento.tipo is TipoCorreo.fondos_agregados:
        return Operacion(tipo=_T.deposito, fecha=dia_ny, monto_cents=cents(evento.monto),
                         nombre="Deposito", **comun)
    return None


def deposito_completado(evento: EventoHapi, recibido_cents: int, pagado_cents: int | None) -> Operacion:
    """'Deposito completado' no trae importe: lo da la solicitud que lo precedio."""
    op = Operacion(
        tipo=_T.deposito, fecha=evento.recibido.astimezone(calendario.NUEVA_YORK).date(),
        monto_cents=recibido_cents, nombre="Deposito",
        comision_cents=(pagado_cents - recibido_cents) if pagado_cents is not None else None,
        estado=EstadoOperacion.provisional, fuente=FuenteOperacion.correo,
        correo_id=evento.message_id,
        ejecutada_at=evento.recibido.astimezone(timezone.utc).replace(tzinfo=None),
    )
    return op


# ----------------------------------------------------------------------------- conciliacion


def emparejan(correo: Operacion, oficial: Operacion, pendiente: bool) -> bool:
    """Si la operacion de un correo y la de un estado de cuenta son la misma."""
    if correo.tipo is not oficial.tipo:
        return False
    if correo.simbolo and oficial.simbolo and correo.simbolo != oficial.simbolo:
        return False
    if correo.tipo in (_T.compra, _T.venta):
        if correo.cantidad_micro != oficial.cantidad_micro:
            return False
        if abs((correo.precio_micro or 0) - (oficial.precio_micro or 0)) > _TOLERANCIA_PRECIO_MICRO:
            return False
        if pendiente:
            return correo.fecha == oficial.fecha
        return calendario.liquidacion(correo.fecha) == oficial.fecha_liquidacion
    if correo.tipo is _T.dividendo:
        neto = oficial.monto_cents - oficial.retencion_cents
        # El correo del dividendo puede llegar unos dias despues del pago.
        return abs(correo.monto_cents - neto) <= 1 and abs((correo.fecha - oficial.fecha).days) <= 5
    if correo.tipo in (_T.deposito, _T.retiro):
        return correo.monto_cents == oficial.monto_cents and abs((correo.fecha - oficial.fecha).days) <= 7
    return False


def oficializar(correo: Operacion, fila: FilaOficial, estado_cuenta_id: int) -> None:
    """La operacion del correo pasa a oficial con los importes del estado.

    Se queda con lo que solo sabe el correo: la hora exacta, la fecha real de la
    orden y el ticker; lo demas lo manda el estado de cuenta.
    """
    oficial = fila.op
    correo.estado = EstadoOperacion.oficial
    correo.estado_cuenta_id = estado_cuenta_id
    correo.nombre = oficial.nombre or correo.nombre
    correo.simbolo = correo.simbolo or oficial.simbolo
    correo.monto_cents = oficial.monto_cents
    correo.retencion_cents = oficial.retencion_cents
    if correo.tipo in (_T.compra, _T.venta):
        correo.cantidad_micro = oficial.cantidad_micro
        correo.precio_micro = oficial.precio_micro
        correo.comision_cents = oficial.comision_cents
        correo.fecha_liquidacion = oficial.fecha_liquidacion
    if correo.tipo is _T.dividendo:
        correo.fecha = oficial.fecha
        correo.nota = oficial.nota
    correo.fecha_estimada = False


def misma_liquidada(pendiente: Operacion, fila: FilaOficial) -> bool:
    """Una operacion que quedo pendiente un mes es esta fila liquidada del siguiente."""
    o = fila.op
    return (
        not fila.pendiente and pendiente.fecha_liquidacion is None
        and o.tipo is pendiente.tipo and o.cantidad_micro == pendiente.cantidad_micro
        and o.monto_cents == pendiente.monto_cents
        and o.fecha_liquidacion == calendario.liquidacion(pendiente.fecha)
    )


def ventana_de_descarte(estado_inicio: date, estado_fin: date, tipo: TipoOperacion) -> tuple[date, date]:
    """Fechas en las que una operacion del correo TIENE que aparecer en ese estado.

    Las compras, ventas y dividendos del mes aparecen siempre (liquidados o
    pendientes). Los depositos y retiros pueden caer en el estado siguiente si
    llegan en los ultimos dias: esos se esperan una semana mas.
    """
    if tipo in (_T.deposito, _T.retiro):
        return estado_inicio, estado_fin - timedelta(days=7)
    return estado_inicio, estado_fin
