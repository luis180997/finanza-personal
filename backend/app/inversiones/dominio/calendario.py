"""Calendario de la bolsa de Nueva York: dias habiles, horario y liquidacion.

Sirve para dos cosas:

1. **Saber si la bolsa esta abierta**, para pedir precios solo cuando cambian.
   El horario es el de Nueva York (9:30 a 16:00), no el de Lima: la diferencia
   cambia con el horario de verano de EE. UU.

2. **Deducir la fecha de una operacion a partir de su liquidacion.** El estado de
   cuenta fecha las compras y ventas el dia en que se liquidan: dos dias habiles
   despues de la orden hasta el 27 de mayo de 2024 y uno desde el 28 (la SEC paso
   de T+2 a T+1). Cuando una operacion no tiene correo, su fecha se calcula hacia
   atras y se marca como estimada.

HAY DOS CALENDARIOS, y confundirlos descuadra fechas reales:

    - el de la BOLSA dice que dias se opera;
    - el de LIQUIDACION dice que dias se liquida, y depende tambien de los bancos.

El Dia de Colon y el de los Veteranos la bolsa abre pero los bancos no: no se
liquida (una orden del viernes anterior se liquida el miercoles, no el martes). Al reves,
en un cierre extraordinario de la bolsa (duelo nacional, 9/1/2025) los bancos
abren y se liquida con normalidad. Comprobado contra todas las operaciones del
usuario que tienen correo y estado de cuenta.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

NUEVA_YORK = ZoneInfo("America/New_York")
APERTURA = time(9, 30)
CIERRE = time(16, 0)
INICIO_T1 = date(2024, 5, 28)

# Cierres que no salen de ninguna regla: dias de duelo nacional.
_CIERRES_EXTRAORDINARIOS = {date(2025, 1, 9)}


def _pascua(anio: int) -> date:
    """Domingo de Pascua (algoritmo de Meeus/Jones/Butcher)."""
    a, b, c = anio % 19, anio // 100, anio % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = (h + l - 7 * m + 114) % 31 + 1
    return date(anio, mes, dia)


def _enesimo_lunes(anio: int, mes: int, n: int) -> date:
    primero = date(anio, mes, 1)
    return primero + timedelta(days=(7 - primero.weekday()) % 7 + 7 * (n - 1))


def _ultimo_lunes(anio: int, mes: int) -> date:
    siguiente = date(anio + (mes == 12), mes % 12 + 1, 1)
    ultimo = siguiente - timedelta(days=1)
    return ultimo - timedelta(days=ultimo.weekday())


def _cuarto_jueves_de_noviembre(anio: int) -> date:
    primero = date(anio, 11, 1)
    return primero + timedelta(days=(3 - primero.weekday()) % 7 + 21)


def _observado(d: date) -> date:
    """Un festivo en sabado se cierra el viernes; en domingo, el lunes."""
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


@lru_cache(maxsize=None)
def _festivos_comunes(anio: int) -> frozenset[date]:
    """Festivos de la bolsa que salen de una regla fija."""
    dias = {
        _enesimo_lunes(anio, 1, 3),                       # Martin Luther King
        _enesimo_lunes(anio, 2, 3),                       # Washington
        _pascua(anio) - timedelta(days=2),                # Viernes Santo
        _ultimo_lunes(anio, 5),                           # Memorial Day
        _observado(date(anio, 7, 4)),                     # Independencia
        _enesimo_lunes(anio, 9, 1),                       # Labor Day
        _cuarto_jueves_de_noviembre(anio),                # Accion de Gracias
        _observado(date(anio, 12, 25)),                   # Navidad
    }
    # Anio Nuevo en sabado NO se cierra el viernes anterior (seria otro anio).
    anio_nuevo = date(anio, 1, 1)
    if anio_nuevo.weekday() != 5:
        dias.add(_observado(anio_nuevo))
    if anio >= 2022:
        dias.add(_observado(date(anio, 6, 19)))           # Juneteenth
    return frozenset(dias)


@lru_cache(maxsize=None)
def _festivos_bancarios(anio: int) -> frozenset[date]:
    """Dias sin bancos (Reserva Federal) en que la bolsa si abre."""
    veteranos = date(anio, 11, 11)
    dias = {_enesimo_lunes(anio, 10, 2)}                  # Colon
    # La Reserva Federal no adelanta al viernes un festivo en sabado.
    if veteranos.weekday() == 6:
        dias.add(veteranos + timedelta(days=1))
    elif veteranos.weekday() < 5:
        dias.add(veteranos)
    return frozenset(dias)


def es_habil(d: date) -> bool:
    """Dia de bolsa: se puede operar."""
    return d.weekday() < 5 and d not in _festivos_comunes(d.year) and d not in _CIERRES_EXTRAORDINARIOS


def es_dia_de_liquidacion(d: date) -> bool:
    return d.weekday() < 5 and d not in _festivos_comunes(d.year) and d not in _festivos_bancarios(d.year)


def habiles_despues(d: date, n: int) -> date:
    """El dia de bolsa que queda `n` dias de bolsa despues de `d`."""
    while n > 0:
        d += timedelta(days=1)
        if es_habil(d):
            n -= 1
    return d


def _liquidables_antes(d: date, n: int) -> date:
    while n > 0:
        d -= timedelta(days=1)
        if es_dia_de_liquidacion(d):
            n -= 1
    return d


def dias_de_liquidacion(fecha_operacion: date) -> int:
    return 1 if fecha_operacion >= INICIO_T1 else 2


def liquidacion(fecha_operacion: date) -> date:
    """Dia en que se liquida una orden ejecutada en `fecha_operacion` (dia de bolsa)."""
    d, n = fecha_operacion, dias_de_liquidacion(fecha_operacion)
    while n > 0:
        d += timedelta(days=1)
        if es_dia_de_liquidacion(d):
            n -= 1
    return d


def operacion_desde_liquidacion(fecha_liquidacion: date) -> date:
    """La fecha de la orden que se liquido en `fecha_liquidacion`.

    En la semana del cambio de T+2 a T+1 dos fechas pueden liquidarse el mismo
    dia; se toma la de T+1, la mas reciente.
    """
    t1 = _liquidables_antes(fecha_liquidacion, 1)
    candidata = t1 if t1 >= INICIO_T1 else _liquidables_antes(fecha_liquidacion, 2)
    while not es_habil(candidata):          # un dia con bancos pero sin bolsa
        candidata -= timedelta(days=1)
    return candidata


def dia_de_bolsa(momento: datetime) -> date:
    """El dia de bolsa al que corresponde una orden ejecutada en `momento`.

    Fuera de sesion (de noche o en fin de semana) cuenta el siguiente dia de bolsa.
    """
    ny = momento.astimezone(NUEVA_YORK)
    if es_habil(ny.date()) and ny.time() < CIERRE:
        return ny.date()
    return habiles_despues(ny.date(), 1)


def abierta(momento: datetime) -> bool:
    """La bolsa esta en sesion en ese instante (con zona horaria)."""
    ny = momento.astimezone(NUEVA_YORK)
    return es_habil(ny.date()) and APERTURA <= ny.time() < CIERRE


def apertura_de(d: date) -> datetime:
    return datetime.combine(d, APERTURA, tzinfo=NUEVA_YORK)


def cierre_de(d: date) -> datetime:
    return datetime.combine(d, CIERRE, tzinfo=NUEVA_YORK)
