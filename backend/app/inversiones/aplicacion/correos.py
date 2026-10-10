"""Leer los correos de Hapi y anotar sus operaciones como provisionales.

Se procesan en orden cronologico y cada correo una sola vez (su Message-ID queda
en `inv_correo`, sin el texto). Para cada uno:

- **Ejecucion repetida.** Hapi a veces manda el mismo "Orden Ejecutada" varias
  veces. Una ejecucion identica (valor, sentido, cantidad, precio e importe) a
  otra de las ultimas horas solo cuenta si hubo tantas ordenes colocadas como
  ejecuciones.
- **Mes con estado de cuenta.** Si la operacion ya figura como oficial (el estado
  se importo antes que el correo), el correo solo le anade lo que el estado no
  tiene: la hora y la fecha real de la orden. Si no figura, no se anota: el
  estado de cuenta manda.
- **Mes sin estado de cuenta.** Se anota como provisional hasta que llegue.

Los "Deposito completado" no traen importe: lo da la "solicitud de deposito"
anterior.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from app.compartido.puertos import UnidadDeTrabajo
from app.inversiones.aplicacion import saldo_inicial
from app.inversiones.aplicacion.puertos import BuzonHapi, RepositorioInversiones
from app.inversiones.dominio import calendario, correo_hapi, libro
from app.inversiones.dominio.correo_hapi import CorreoHapi, EventoHapi, TipoCorreo
from app.inversiones.dominio.entidades import (
    CorreoHapiLeido, EstadoCuentaImportado, EstadoOperacion, Operacion, TipoOperacion,
)

log = logging.getLogger("finanzas.inversiones")
_T = TipoOperacion

# La primera vez se lee todo el historial de Hapi; despues, desde el ultimo leido
# con un margen por si un correo llego tarde.
PRIMER_DIA = date(2022, 1, 1)
MARGEN = timedelta(days=3)
_VENTANA_REPETIDOS = timedelta(hours=3)
_VENTANA_COLOCADAS = timedelta(hours=6)


@dataclass
class ResultadoCorreos:
    leidos: int = 0
    nuevos: int = 0
    operaciones: int = 0
    completadas: int = 0          # anadieron hora a una operacion oficial
    repetidos: int = 0
    sin_cuadre: int = 0
    ilegibles: list[str] = field(default_factory=list)


def _utc(momento: datetime) -> datetime:
    return momento.astimezone(timezone.utc).replace(tzinfo=None)


class ServicioCorreosHapi:
    def __init__(self, buzon: BuzonHapi, repo: RepositorioInversiones, uow: UnidadDeTrabajo):
        self.buzon = buzon
        self.repo = repo
        self.uow = uow

    def sincronizar(self, desde: date | None = None) -> ResultadoCorreos:
        resultado = ResultadoCorreos()
        if not self.buzon.configurado:
            return resultado
        if desde is None:
            ultimo = self.repo.ultimo_correo_at()
            desde = (ultimo - MARGEN).date() if ultimo else PRIMER_DIA
        # Los que no se pudieron leer se reintentan cuando el lector cambio: si Hapi
        # cambio una etiqueta y se corrigio el lector, sus operaciones aparecen solas.
        # Con el mismo lector no: fallarian igual y obligarian a releer todo el
        # historial desde ellos en cada lectura.
        a_reintentar = [c for c in self.repo.correos_con_resultado("ilegible") if _reintentable(c)]
        if a_reintentar:
            desde = min(desde, min(c.recibido_at for c in a_reintentar).date())
        correos = sorted(self.buzon.correos(desde), key=lambda c: c.recibido)
        resultado.leidos = len(correos)
        estados = self.repo.estados()
        # El libro se carga una vez; lo que se anade se suma a esta lista.
        self._ops = self.repo.operaciones()
        for correo in correos:
            ya_leido = self.repo.correo(correo.message_id)
            if ya_leido is not None and not _reintentable(ya_leido):
                continue
            resultado.nuevos += 1
            self._procesar(correo, estados, resultado, ya_leido)
            self.uow.volcar()
        _completar_simbolos(self._ops)
        self.uow.volcar()
        saldo_inicial.ajustar(self.repo)
        self.uow.confirmar()
        if resultado.nuevos:
            log.info("correos de Hapi: %s nuevos, %s operaciones",
                     resultado.nuevos, resultado.operaciones)
        return resultado

    # ------------------------------------------------------------------ un correo

    def _procesar(self, correo: CorreoHapi, estados: list[EstadoCuentaImportado],
                  r: ResultadoCorreos, ficha: CorreoHapiLeido | None = None) -> None:
        if ficha is None:
            ficha = CorreoHapiLeido(message_id=correo.message_id, recibido_at=_utc(correo.recibido),
                                    tipo="", resultado="")
        ficha.tipo = correo_hapi.tipo_de(correo.asunto).value
        ficha.resultado, ficha.detalle = "informativo", None
        self.repo.agregar(ficha)
        try:
            evento = correo_hapi.leer(correo)
        except correo_hapi.CorreoIlegible as exc:
            ficha.resultado = "ilegible"
            ficha.detalle = f"{_MARCA_LECTOR} {exc}"
            r.ilegibles.append(f"{correo.recibido:%Y-%m-%d} {correo.asunto}: {exc}")
            return
        ficha.tipo = evento.tipo.value
        ficha.ticker, ficha.lado = evento.ticker, evento.lado
        ficha.cantidad_micro = libro.micro(evento.cantidad)

        if evento.tipo is TipoCorreo.ignorado:
            ficha.resultado, ficha.detalle = "ignorado", evento.motivo
            return
        if evento.tipo in (TipoCorreo.colocada, TipoCorreo.cancelada):
            return
        if evento.tipo is TipoCorreo.solicitud_deposito:
            ficha.monto_cents = libro.cents(evento.monto)
            if evento.moneda_pagada == "USD":
                ficha.pagado_cents = libro.cents(evento.monto_pagado)
            return

        solicitud = None
        if evento.tipo is TipoCorreo.deposito_completado:
            solicitud = self._solicitud_previa(evento)
            if solicitud is None:
                ficha.resultado = "sin_cuadre"
                ficha.detalle = "Deposito completado sin solicitud previa"
                r.sin_cuadre += 1
                return
            op = libro.deposito_completado(evento, solicitud.monto_cents, solicitud.pagado_cents)
        else:
            op = libro.del_correo(evento)
        if op is None:
            return
        repetida = (op.tipo in (_T.compra, _T.venta) and self._es_repetida(op, evento)) or (
            op.tipo is _T.dividendo and self._dividendo_repetido(op))
        if repetida:
            ficha.resultado, ficha.detalle = "repetido", "Hapi envio otra vez el mismo aviso"
            r.repetidos += 1
            return

        oficial = self._oficial_sin_correo(op)
        if oficial is not None:
            _completar(oficial, op)
            ficha.resultado, ficha.operacion_id = "operacion", oficial.id
            r.completadas += 1
        elif _cubierta(op, estados):
            ficha.resultado = "sin_cuadre"
            ficha.detalle = "El estado de cuenta de ese mes no recoge esta operacion"
            r.sin_cuadre += 1
        else:
            self.repo.agregar(op)
            self.uow.volcar()
            self._ops.append(op)
            ficha.resultado, ficha.operacion_id = "operacion", op.id
            r.operaciones += 1
        if solicitud is not None:              # que no sirva para otro deposito
            solicitud.resultado = "usada"
            solicitud.operacion_id = ficha.operacion_id

    def _solicitud_previa(self, evento: EventoHapi) -> CorreoHapiLeido | None:
        """La ultima solicitud de deposito de la semana anterior aun sin usar."""
        recibido = _utc(evento.recibido)
        solicitudes = [
            s for s in self.repo.correos_leidos(TipoCorreo.solicitud_deposito.value,
                                                recibido - timedelta(days=7), recibido)
            if s.resultado == "informativo" and s.monto_cents
        ]
        return solicitudes[-1] if solicitudes else None

    def _es_repetida(self, op: Operacion, evento: EventoHapi) -> bool:
        momento = op.ejecutada_at
        iguales = [
            o for o in self._ops
            if o.tipo is op.tipo and o.simbolo == op.simbolo
            and o.cantidad_micro == op.cantidad_micro and o.precio_micro == op.precio_micro
            and o.ejecutada_at is not None
            and abs(o.ejecutada_at - momento) <= _VENTANA_REPETIDOS
        ]
        if not iguales:
            return False
        colocadas = [
            c for c in self.repo.correos_leidos(TipoCorreo.colocada.value,
                                                momento - _VENTANA_COLOCADAS, momento)
            if c.ticker == evento.ticker and c.lado == evento.lado
            and (c.cantidad_micro is None or c.cantidad_micro == op.cantidad_micro)
        ]
        return len(iguales) >= max(1, len(colocadas))

    def _dividendo_repetido(self, op: Operacion) -> bool:
        """Otro aviso del mismo dividendo (mismo valor, mismo neto, pago cercano) ya leido."""
        for o in self._ops:
            if o.tipo is not _T.dividendo or o.correo_id is None or o.simbolo != op.simbolo:
                continue
            neto = o.monto_cents - o.retencion_cents
            if abs(neto - op.monto_cents) <= 1 and abs((o.fecha - op.fecha).days) <= 5:
                return True
        return False

    def _oficial_sin_correo(self, op: Operacion) -> Operacion | None:
        for oficial in self._ops:
            if oficial.estado is not EstadoOperacion.oficial or oficial.correo_id is not None:
                continue
            pendiente = oficial.tipo in (_T.compra, _T.venta) and oficial.fecha_liquidacion is None
            if libro.emparejan(op, oficial, pendiente):
                return oficial
        return None


_MARCA_LECTOR = f"[lector {correo_hapi.VERSION_LECTOR}]"


def _reintentable(ficha: CorreoHapiLeido) -> bool:
    """Un ilegible que leyo otra version del lector."""
    return ficha.resultado == "ilegible" and not (ficha.detalle or "").startswith(_MARCA_LECTOR)


def _completar(oficial: Operacion, del_correo: Operacion) -> None:
    """Lo que el correo sabe y el estado no: hora, fecha real de la orden, ticker."""
    oficial.correo_id = del_correo.correo_id
    oficial.ejecutada_at = del_correo.ejecutada_at
    oficial.simbolo = oficial.simbolo or del_correo.simbolo
    if oficial.tipo in (_T.compra, _T.venta):
        oficial.fecha = del_correo.fecha
        oficial.fecha_estimada = False
    if oficial.tipo in (_T.deposito, _T.retiro) and oficial.comision_cents is None:
        oficial.comision_cents = del_correo.comision_cents


def _completar_simbolos(ops: list[Operacion]) -> None:
    """Lo que un correo enseno (el ticker de un nombre) sirve para las demas operaciones."""
    simbolos = {
        o.nombre: o.simbolo for o in ops if o.simbolo and o.nombre and o.nombre != o.simbolo
    }
    for o in ops:
        if o.simbolo is None and o.nombre in simbolos:
            o.simbolo = simbolos[o.nombre]


def _cubierta(op: Operacion, estados: list[EstadoCuentaImportado]) -> bool:
    """Si la operacion cae en un mes cuyo estado de cuenta ya esta importado."""
    if not estados:
        return False
    inicio, fin = estados[0].inicio, estados[-1].fin
    fechas = [op.fecha]
    if op.tipo in (_T.compra, _T.venta):
        fechas.append(calendario.liquidacion(op.fecha))
    if op.tipo in (_T.deposito, _T.retiro):
        desde, hasta = libro.ventana_de_descarte(inicio, fin, op.tipo)
        return desde <= op.fecha <= hasta
    return any(inicio <= f <= fin for f in fechas)
