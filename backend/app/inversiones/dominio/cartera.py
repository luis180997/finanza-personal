"""Que tienes, cuanto te costo y cuanto ganaste: se recorre el libro en orden.

El costo de cada valor sigue el metodo del COSTO PROMEDIO, el mismo que muestra
Hapi: una compra suma su importe (comision incluida) al costo; una venta saca la
parte proporcional y la diferencia con lo cobrado es ganancia realizada. Un split
suma acciones sin tocar el costo.

Se cuentan las operaciones oficiales y las provisionales; las descartadas no.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from app.inversiones.dominio import calendario
from app.inversiones.dominio.entidades import EstadoOperacion, Operacion, TipoOperacion

MICRO = 1_000_000
_T = TipoOperacion

# Dentro de un mismo dia: primero entra el dinero, luego se opera, al final sale.
_ORDEN_EN_EL_DIA = {
    _T.deposito: 0, _T.cripto_entrada: 0, _T.split: 1, _T.compra: 2, _T.venta: 3,
    _T.dividendo: 4, _T.ajuste_impuesto: 5, _T.interes: 6, _T.retiro: 7, _T.cripto_salida: 7,
    _T.ajuste_saldo: 0, _T.posicion_inicial: 0,
}
_APORTES = (_T.deposito, _T.retiro, _T.cripto_entrada, _T.cripto_salida)


def clave_de(op: Operacion) -> str:
    """Un valor se identifica por su simbolo; sin el, por su nombre."""
    return op.simbolo or f"?{op.nombre}"


def ordenar(ops: Iterable[Operacion]) -> list[Operacion]:
    def clave(op: Operacion):
        momento = op.ejecutada_at or datetime.max
        return (op.fecha, _ORDEN_EN_EL_DIA[op.tipo], momento, op.id or 0)

    return sorted(ops, key=clave)


def cuentan(ops: Iterable[Operacion]) -> list[Operacion]:
    return [op for op in ops if op.estado is not EstadoOperacion.descartada]


@dataclass
class Posicion:
    clave: str
    simbolo: str | None
    nombre: str | None
    cantidad_micro: int = 0
    costo_cents: Decimal = Decimal(0)        # de lo que queda
    realizada_cents: Decimal = Decimal(0)
    dividendos_cents: int = 0                # bruto
    retenciones_cents: int = 0               # retenido menos devuelto
    comisiones_cents: int = 0
    ultimo_precio_micro: int | None = None   # de la ultima compra o venta

    @property
    def abierta(self) -> bool:
        return self.cantidad_micro > 0

    @property
    def costo_promedio_micro(self) -> int | None:
        if self.cantidad_micro <= 0:
            return None
        return round(self.costo_cents / 100 * MICRO * MICRO / self.cantidad_micro)


@dataclass
class Cartera:
    posiciones: dict[str, Posicion] = field(default_factory=dict)
    efectivo_cents: int = 0
    depositos_cents: int = 0
    retiros_cents: int = 0          # positivo
    a_cripto_cents: int = 0         # neto que salio hacia cripto (positivo = salio)
    intereses_cents: int = 0
    ajustes_cents: int = 0          # ajuste de saldo (no es un aporte)
    aportado_en_acciones_cents: int = 0   # posiciones iniciales, a su valor de entonces
    comisiones_operacion_cents: int = 0
    comisiones_deposito_cents: int = 0
    comisiones_retiro_cents: int = 0
    avisos: list[str] = field(default_factory=list)

    @property
    def aportes_cents(self) -> int:
        """Lo que pusiste de tu bolsillo y sigue dentro: depositos - retiros - cripto."""
        return (self.depositos_cents - self.retiros_cents - self.a_cripto_cents
                + self.aportado_en_acciones_cents)

    def abiertas(self) -> list[Posicion]:
        return [p for p in self.posiciones.values() if p.abierta]


def calcular(ops: Iterable[Operacion], hasta: date | None = None) -> Cartera:
    cartera = Cartera()
    for op in ordenar(cuentan(ops)):
        if hasta is not None and op.fecha > hasta:
            break
        aplicar(cartera, op)
    return cartera


def valor_inicial_cents(op: Operacion) -> int:
    return round((op.cantidad_micro or 0) * (op.precio_micro or 0) / MICRO / MICRO * 100)


def fecha_de_liquidacion(op: Operacion) -> date:
    """Cuando la operacion toca la cuenta segun el estado de cuenta."""
    if op.fecha_liquidacion is not None:
        return op.fecha_liquidacion
    if op.tipo in (_T.compra, _T.venta):
        return calendario.liquidacion(op.fecha)
    return op.fecha


def calcular_liquidado(ops: Iterable[Operacion], hasta: date) -> Cartera:
    """La cartera como la ve el estado de cuenta: solo lo liquidado hasta `hasta`."""
    return calcular([op for op in ops if fecha_de_liquidacion(op) <= hasta])


def aplicar(cartera: Cartera, op: Operacion) -> None:
    """Suma una operacion a la cartera. Se llama en orden cronologico."""
    cartera.efectivo_cents += op.monto_cents - op.retencion_cents
    if op.tipo in _APORTES:
        _aporte(cartera, op)
        return
    if op.tipo is _T.interes:
        cartera.intereses_cents += op.monto_cents
        return
    if op.tipo is _T.ajuste_saldo:
        cartera.ajustes_cents += op.monto_cents
        return

    clave = clave_de(op)
    p = cartera.posiciones.get(clave)
    if p is None:
        p = cartera.posiciones[clave] = Posicion(clave=clave, simbolo=op.simbolo, nombre=op.nombre)
    p.nombre = p.nombre or op.nombre

    if op.tipo is _T.compra:
        p.cantidad_micro += op.cantidad_micro or 0
        p.costo_cents += -op.monto_cents
        p.comisiones_cents += op.comision_cents or 0
        cartera.comisiones_operacion_cents += op.comision_cents or 0
        p.ultimo_precio_micro = op.precio_micro or p.ultimo_precio_micro
    elif op.tipo is _T.venta:
        _venta(cartera, p, op)
    elif op.tipo is _T.split:
        p.cantidad_micro += op.cantidad_micro or 0
    elif op.tipo is _T.posicion_inicial:
        costo = valor_inicial_cents(op)
        p.cantidad_micro += op.cantidad_micro or 0
        p.costo_cents += costo
        p.ultimo_precio_micro = op.precio_micro or p.ultimo_precio_micro
        cartera.aportado_en_acciones_cents += costo
    elif op.tipo is _T.dividendo:
        p.dividendos_cents += op.monto_cents
        p.retenciones_cents += op.retencion_cents
    elif op.tipo is _T.ajuste_impuesto:
        # Un ajuste positivo es retencion que te devuelven.
        p.retenciones_cents -= op.monto_cents


def _aporte(cartera: Cartera, op: Operacion) -> None:
    if op.tipo is _T.deposito:
        cartera.depositos_cents += op.monto_cents
        cartera.comisiones_deposito_cents += op.comision_cents or 0
    elif op.tipo is _T.retiro:
        cartera.retiros_cents += -op.monto_cents
        cartera.comisiones_retiro_cents += op.comision_cents or 0
    else:   # cripto: sale con signo negativo, vuelve con positivo
        cartera.a_cripto_cents += -op.monto_cents


def _venta(cartera: Cartera, p: Posicion, op: Operacion) -> None:
    vendida = op.cantidad_micro or 0
    if vendida > p.cantidad_micro:
        cartera.avisos.append(
            f"{op.fecha} {p.clave}: se venden {vendida / MICRO:g} acciones y solo constan "
            f"{p.cantidad_micro / MICRO:g}",
        )
        vendida = p.cantidad_micro
    costo_vendido = p.costo_cents * vendida / p.cantidad_micro if p.cantidad_micro else Decimal(0)
    p.realizada_cents += op.monto_cents - costo_vendido
    p.costo_cents -= costo_vendido
    p.cantidad_micro -= vendida
    if p.cantidad_micro == 0:
        p.costo_cents = Decimal(0)
    p.comisiones_cents += op.comision_cents or 0
    cartera.comisiones_operacion_cents += op.comision_cents or 0
    p.ultimo_precio_micro = op.precio_micro or p.ultimo_precio_micro
