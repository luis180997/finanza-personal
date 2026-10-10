"""Mantener al dia los precios: cierres diarios e intradia.

- Cierres diarios de todo valor que haya pasado por la cuenta, desde unos dias
  antes de su primera operacion, mas VOO (la referencia del S&P 500). La primera
  vez se baja la historia; despues, solo los dias que faltan.
- Intradia, cada pocos minutos y solo con la bolsa abierta, de lo que tienes hoy.

Sin claves del proveedor no se hace nada: la cartera se valora con el ultimo
precio conocido (el de cierre de mes del estado de cuenta o el de la ultima
operacion).
"""
from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from app.compartido import reloj
from app.compartido.puertos import UnidadDeTrabajo
from app.inversiones.aplicacion.puertos import (
    Cierre, ErrorDePrecios, FuenteDePrecios, RepositorioInversiones,
)
from app.inversiones.dominio import calendario, cartera
from app.inversiones.dominio.entidades import PrecioDiario, PrecioIntradia

log = logging.getLogger("finanzas.inversiones")

REFERENCIA = "VOO"
_DIAS_PREVIOS = 10
# Apex publica el cierre oficial unos minutos despues de las 16:00 de Nueva York.
_CIERRE_DISPONIBLE = timedelta(minutes=20)


@dataclass
class ResultadoPrecios:
    configurado: bool
    cierres: int = 0
    intradia: int = 0
    error: str | None = None


def _cambio_el_ajuste(guardado: PrecioDiario, nuevo: Cierre) -> bool:
    def distinto(a: int, b: int) -> bool:
        return abs(a - b) > max(1, abs(a) // 1_000_000)

    return (distinto(guardado.cierre_split_micro, nuevo.split_micro)
            or distinto(guardado.cierre_total_micro, nuevo.total_micro))


class ServicioPrecios:
    def __init__(self, fuente: FuenteDePrecios, repo: RepositorioInversiones, uow: UnidadDeTrabajo,
                 ahora: Callable[[], datetime] = reloj.ahora_utc, minutos: int = 5):
        self.fuente = fuente
        self.repo = repo
        self.uow = uow
        self.ahora = ahora
        self.minutos = minutos

    def actualizar(self) -> ResultadoPrecios:
        """Lo que toque ahora: cierres que falten y, con la bolsa abierta, intradia."""
        r = ResultadoPrecios(configurado=self.fuente.configurada)
        if not r.configurado:
            return r
        try:
            r.cierres = self._cierres()
            if calendario.abierta(self.ahora()):
                r.intradia = self._intradia()
            self.uow.confirmar()
        except ErrorDePrecios as exc:
            self.uow.deshacer()
            r.error = str(exc)
            log.warning("precios: %s", exc)
        return r

    def ultimo_cierre_disponible(self) -> date:
        """El ultimo dia de bolsa cuyo cierre ya se puede pedir."""
        ny = (self.ahora() - _CIERRE_DISPONIBLE).astimezone(calendario.NUEVA_YORK)
        d = ny.date()
        if calendario.es_habil(d) and ny.time() >= calendario.CIERRE:
            return d
        d -= timedelta(days=1)
        while not calendario.es_habil(d):
            d -= timedelta(days=1)
        return d

    def _rangos(self, hasta: date) -> dict[str, tuple[date, date]]:
        """Que dias hacen falta de cada valor: desde poco antes de su primera
        operacion hasta hoy si lo tienes, o hasta poco despues de venderlo.

        Lo vendido no se sigue pidiendo: un valor que ya no cotiza (comprado por
        otra empresa) no tendria cierres nuevos nunca y se pediria para siempre.
        """
        ops = cartera.cuentan(self.repo.operaciones())
        abiertas = {p.simbolo for p in cartera.calcular(ops).abiertas() if p.simbolo}
        fechas: dict[str, tuple[date, date]] = {}
        for op in ops:
            if op.simbolo and not op.simbolo.startswith("?"):
                primera, ultima = fechas.get(op.simbolo, (op.fecha, op.fecha))
                fechas[op.simbolo] = (min(primera, op.fecha), max(ultima, op.fecha))
        rangos = {
            s: (primera - timedelta(days=_DIAS_PREVIOS),
                hasta if s in abiertas else min(hasta, ultima + timedelta(days=_DIAS_PREVIOS)))
            for s, (primera, ultima) in fechas.items()
        }
        if rangos:                  # la referencia, desde el primer dia de la cuenta
            rangos[REFERENCIA] = (min(inicio for inicio, _ in rangos.values()), hasta)
        return rangos

    def _cierres(self) -> int:
        """Los cierres que faltan. Se vuelve a pedir el ultimo dia ya guardado: si su
        precio ajustado cambio, hubo un split o un dividendo nuevo y Alpaca recalculo
        toda la historia ajustada de ese valor, que entonces se baja entera otra vez."""
        rangos = self._rangos(self.ultimo_cierre_disponible())
        ultimas = self.repo.ultimas_fechas_de_precio()
        por_rango: dict[tuple[date, date], list[str]] = defaultdict(list)
        for simbolo, (inicio, fin) in rangos.items():
            if simbolo in ultimas and ultimas[simbolo] >= fin:
                continue                                    # al dia
            por_rango[(ultimas.get(simbolo, inicio), fin)].append(simbolo)
        guardados = 0
        rehacer: list[str] = []
        for (desde, fin), simbolos in sorted(por_rango.items()):
            for simbolo, cierres in self.fuente.cierres(sorted(simbolos), desde, fin).items():
                previo = self.repo.cierre(simbolo, ultimas[simbolo]) if simbolo in ultimas else None
                for c in cierres:
                    if previo is not None and c.fecha == previo.fecha and _cambio_el_ajuste(previo, c):
                        rehacer.append(simbolo)
                    self.repo.guardar_cierre(simbolo, c)
                    guardados += 1
        for simbolo in rehacer:
            log.info("precios: %s tuvo un split o un dividendo; se rehace su historia ajustada", simbolo)
            inicio, fin = rangos[simbolo]
            for c in self.fuente.cierres([simbolo], inicio, fin).get(simbolo, []):
                self.repo.guardar_cierre(simbolo, c)
                guardados += 1
        return guardados

    def _intradia(self) -> int:
        hoy_ny = self.ahora().astimezone(calendario.NUEVA_YORK).date()
        apertura = calendario.apertura_de(hoy_ny)
        abiertas = cartera.calcular(self.repo.operaciones()).abiertas()
        simbolos = sorted({p.simbolo for p in abiertas if p.simbolo} | {REFERENCIA})
        desde_utc = apertura.astimezone(timezone.utc).replace(tzinfo=None)
        guardados = 0
        for simbolo, barras in self.fuente.barras(simbolos, apertura, self.minutos).items():
            ya = self.repo.momentos_intradia(simbolo, desde_utc)
            for momento, precio in barras:
                if momento not in ya:
                    self.repo.agregar(PrecioIntradia(simbolo=simbolo, momento=momento, precio_micro=precio))
                    guardados += 1
        return guardados
