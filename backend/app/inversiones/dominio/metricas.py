"""Metricas de la cartera: valor en el tiempo, rentabilidad, dividendos.

Todo es calculo puro sobre las operaciones y los precios; nada sabe de la base.

RENTABILIDAD ANUAL (XIRR). La ganancia total en porcentaje engana cuando el
dinero entra poco a poco: 100 dolares que ganaron 10 en un mes no rinden lo mismo
que 100 que ganaron 10 en tres anios. La XIRR es la tasa anual que, aplicada a
cada aporte desde el dia en que entro, explica el valor de hoy.

COMPARACION CON EL S&P 500. Se simula que cada aporte compro VOO ese mismo dia (y
cada retiro lo vendio), con su rentabilidad total: dividendos reinvertidos. Es una
referencia algo generosa: los dividendos reales de un no residente pierden un
30% de retencion antes de reinvertirse.

RENTABILIDAD POR MES Y POR ANIO (ponderada en el tiempo, TWR). Mide como rindio
lo invertido, no cuanto dinero entro: un deposito no es ganancia ni infla el
porcentaje. Se calcula dia a dia y se encadena: (1 + r1) x (1 + r2) x ... - 1. Es
la que publican los fondos y los indices, asi que se compara justo con el S&P 500
en el mismo periodo.
"""
from __future__ import annotations

import bisect
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.inversiones.dominio import calendario
from app.inversiones.dominio.cartera import (
    MICRO, Cartera, aplicar, clave_de, cuentan, ordenar, valor_inicial_cents,
)
from app.inversiones.dominio.entidades import EstadoOperacion, Operacion, TipoOperacion

_T = TipoOperacion


class SeriePrecios:
    """Cierres de un valor por fecha. Un dia sin precio usa el ultimo anterior."""

    def __init__(self, puntos: Iterable[tuple[date, int]]):
        ordenados = sorted(puntos)
        self.fechas = [f for f, _ in ordenados]
        self.valores = [v for _, v in ordenados]

    def en(self, d: date) -> int | None:
        i = bisect.bisect_right(self.fechas, d)
        return self.valores[i - 1] if i else None

    def desde(self, d: date) -> int | None:
        """El primer cierre en `d` o despues (para comprar con dinero que entra)."""
        i = bisect.bisect_left(self.fechas, d)
        return self.valores[i] if i < len(self.valores) else None

    def __bool__(self) -> bool:
        return bool(self.fechas)


def valor_de_posiciones(cartera: Cartera, precio: dict[str, int | None]) -> int:
    """Acciones x precio. Sin precio, el de la ultima compra o venta del valor."""
    total = 0
    for p in cartera.abiertas():
        micro = precio.get(p.clave) or p.ultimo_precio_micro or 0
        total += round(p.cantidad_micro * micro / MICRO / MICRO * 100)
    return total


# ----------------------------------------------------------------------------- serie diaria


@dataclass
class Punto:
    fecha: date
    acciones_cents: int
    efectivo_cents: int
    aportes_cents: int
    ajustes_cents: int = 0           # ajuste del saldo inicial: ni aporte ni rentabilidad

    @property
    def valor_cents(self) -> int:
        return self.acciones_cents + self.efectivo_cents


def serie_diaria(ops: Iterable[Operacion], precios: dict[str, SeriePrecios], hasta: date) -> list[Punto]:
    """Valor de la cuenta al cierre de cada dia de bolsa hasta `hasta`.

    Solo dias de bolsa: un sabado no es un punto nuevo (repetiria el viernes).
    """
    libro = ordenar(cuentan(ops))
    if not libro:
        return []
    dias = [d for d in _dias(libro[0].fecha, hasta) if calendario.es_habil(d)]
    cartera, i, puntos = Cartera(), 0, []
    for d in dias:
        while i < len(libro) and libro[i].fecha <= d:
            aplicar(cartera, libro[i])
            i += 1
        precio = {k: (precios[p.simbolo].en(d) if p.simbolo in precios else None)
                  for k, p in cartera.posiciones.items()}
        puntos.append(Punto(d, valor_de_posiciones(cartera, precio), cartera.efectivo_cents,
                            cartera.aportes_cents, cartera.ajustes_cents))
    return puntos


def _dias(desde: date, hasta: date):
    d = desde
    while d <= hasta:
        yield d
        d += timedelta(days=1)


# ----------------------------------------------------------------------------- rentabilidad


def flujos_de_aporte(ops: Iterable[Operacion]) -> list[tuple[date, int]]:
    """Dinero que entra (+) o sale (-) de la cuenta, visto desde la cuenta."""
    flujos = []
    for op in ordenar(cuentan(ops)):
        if op.tipo in (_T.deposito, _T.retiro, _T.cripto_entrada, _T.cripto_salida):
            flujos.append((op.fecha, op.monto_cents))
        elif op.tipo is _T.posicion_inicial:
            flujos.append((op.fecha, valor_inicial_cents(op)))
    return flujos


def aporte_mensual(flujos: list[tuple[date, int]], hoy: date) -> float:
    """Lo que entro de media cada mes en el ultimo anio (neto de retiros), en centavos.
    Es el punto de partida de la proyeccion."""
    desde = hoy - timedelta(days=365)
    return sum(c for d, c in flujos if desde < d <= hoy) / 12


def xirr(flujos: list[tuple[date, int]]) -> float | None:
    """Tasa anual que hace cero el valor presente de los flujos (del inversor).

    Aportes en negativo, retiros y valor final en positivo. None si no hay
    solucion (todo del mismo signo, o menos de un mes de historia).
    """
    flujos = [(d, c) for d, c in flujos if c]
    if len(flujos) < 2 or all(c > 0 for _, c in flujos) or all(c < 0 for _, c in flujos):
        return None
    inicio = min(d for d, _ in flujos)
    if (max(d for d, _ in flujos) - inicio).days < 30:
        return None
    anios = [((d - inicio).days / 365.0, c) for d, c in flujos]

    def vpn(tasa: float) -> float:
        return sum(c / (1 + tasa) ** t for t, c in anios)

    bajo, alto = -0.99, 10.0
    if vpn(bajo) * vpn(alto) > 0:
        return None
    for _ in range(200):                     # biseccion: lenta pero no diverge
        medio = (bajo + alto) / 2
        if vpn(bajo) * vpn(medio) <= 0:
            alto = medio
        else:
            bajo = medio
        if alto - bajo < 1e-9:
            break
    return (bajo + alto) / 2


def flujos_del_inversor(aportes: list[tuple[date, int]], valor_final: int,
                        hoy: date) -> list[tuple[date, int]]:
    return [(d, -c) for d, c in aportes] + [(hoy, valor_final)]


def valor_si_fuera_indice(aportes: list[tuple[date, int]], indice: SeriePrecios, hoy: date) -> int | None:
    """Valor de hoy si cada aporte hubiera comprado el indice ese dia."""
    if not indice:
        return None
    participaciones = 0.0
    for d, cents in aportes:
        precio = indice.desde(d) or indice.en(d)
        if not precio:
            return None
        participaciones += cents / precio
    actual = indice.en(hoy)
    return round(participaciones * actual) if actual else None


# ----------------------------------------------------------------------------- rentabilidad por periodos


@dataclass
class DiaRentable:
    fecha: date
    rentabilidad: float              # la del dia, sin contar lo depositado como ganancia
    referencia: float | None         # la del indice ese mismo dia
    ganancia_cents: int
    aportes_cents: int               # lo que entro (+) o salio (-) ese dia
    valor_cents: int                 # al cierre


def rentabilidad_diaria(puntos: list[Punto], indice: SeriePrecios | None = None) -> list[DiaRentable]:
    """La rentabilidad de cada dia de la serie.

    Ganancia = valor de hoy - valor de ayer - lo que entro hoy. Se divide entre lo
    que estuvo invertido: el dinero que entra cuenta desde el inicio del dia (suele
    comprar ese mismo dia) y el que sale, hasta el final. Asi un deposito grande en
    una cuenta pequena no dispara el porcentaje, y retirarlo todo no lo hunde.

    El ajuste del saldo inicial resta en dolares pero no en el porcentaje: es un
    descuadre de antes del primer estado de cuenta, no un resultado de invertir.

    El primer dia parte de cero: su base es lo que entro. El indice empieza a contar
    desde ese dia.
    """
    dias: list[DiaRentable] = []
    antes: Punto | None = None
    for hoy in puntos:
        valor_antes = antes.valor_cents if antes else 0
        entra = hoy.aportes_cents - (antes.aportes_cents if antes else 0)
        ganancia = hoy.valor_cents - valor_antes - entra
        ajuste = hoy.ajustes_cents - (antes.ajustes_cents if antes else 0)
        base = valor_antes + max(entra, 0)
        referencia = None
        if indice:
            previo = indice.en(antes.fecha) if antes else indice.en(hoy.fecha)
            actual = indice.en(hoy.fecha)
            referencia = actual / previo - 1 if previo and actual else None
        dias.append(DiaRentable(hoy.fecha, (ganancia - ajuste) / base if base > 0 else 0.0,
                                referencia, ganancia, entra, hoy.valor_cents))
        antes = hoy
    return dias


@dataclass
class Periodo:
    clave: str                       # "2026-10", "2026"...
    rentabilidad: float = 0.0
    referencia: float | None = None
    ganancia_cents: int = 0
    aportes_cents: int = 0           # lo que entro menos lo que salio
    valor_final_cents: int = 0


def por_periodo(dias: Iterable[DiaRentable], clave: Callable[[date], str]) -> list[Periodo]:
    """Encadena los dias de cada periodo, en orden."""
    periodos: dict[str, Periodo] = {}
    for d in dias:
        p = periodos.setdefault(clave(d.fecha), Periodo(clave(d.fecha)))
        p.rentabilidad = _encadenar(p.rentabilidad, d.rentabilidad)
        if d.referencia is not None:
            p.referencia = _encadenar(p.referencia or 0.0, d.referencia)
        p.ganancia_cents += d.ganancia_cents
        p.aportes_cents += d.aportes_cents
        p.valor_final_cents = d.valor_cents
    return list(periodos.values())


def acumulada(dias: Iterable[DiaRentable]) -> list[tuple[date, float, float | None]]:
    """(fecha, la tuya, la del indice) desde el primer dia, encadenadas."""
    tuya, indice, filas = 0.0, None, []
    for d in dias:
        tuya = _encadenar(tuya, d.rentabilidad)
        if d.referencia is not None:
            indice = _encadenar(indice or 0.0, d.referencia)
        filas.append((d.fecha, tuya, indice))
    return filas


def _encadenar(acumulada: float, del_dia: float) -> float:
    return (1 + acumulada) * (1 + del_dia) - 1


# ----------------------------------------------------------------------------- dividendos


@dataclass
class Dividendos:
    bruto_cents: int = 0
    retencion_cents: int = 0
    # Los dividendos que solo constan por correo traen el neto: su bruto y su
    # retencion se conocen cuando llega el estado de cuenta.
    neto_sin_detalle_cents: int = 0

    @property
    def neto_cents(self) -> int:
        return self.bruto_cents - self.retencion_cents + self.neto_sin_detalle_cents


@dataclass
class ResumenDividendos:
    total: Dividendos = field(default_factory=Dividendos)
    por_mes: dict[str, Dividendos] = field(default_factory=lambda: defaultdict(Dividendos))
    por_valor: dict[str, Dividendos] = field(default_factory=lambda: defaultdict(Dividendos))


def dividendos(ops: Iterable[Operacion]) -> ResumenDividendos:
    r = ResumenDividendos()
    for op in cuentan(ops):
        if op.tipo not in (_T.dividendo, _T.ajuste_impuesto):
            continue
        destinos = (r.total, r.por_mes[f"{op.fecha:%Y-%m}"], r.por_valor[clave_de(op)])
        for d in destinos:
            if op.tipo is _T.ajuste_impuesto:
                d.retencion_cents -= op.monto_cents
            elif op.estado is EstadoOperacion.provisional and op.retencion_cents == 0:
                d.neto_sin_detalle_cents += op.monto_cents
            else:
                d.bruto_cents += op.monto_cents
                d.retencion_cents += op.retencion_cents
    return r
