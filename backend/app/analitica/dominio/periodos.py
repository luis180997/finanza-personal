"""Periodos: rangos de fechas, meses y el periodo con el que se compara."""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

from app.compartido.corte import ANIO_MAX, ANIO_MIN


@dataclass
class Rango:
    desde: date
    hasta: date

    @property
    def dias(self) -> int:
        return (self.hasta - self.desde).days + 1

    def anterior(self) -> "Rango":
        """El periodo inmediatamente anterior, del mismo tamano.

        Si el rango son meses completos (del dia 1 al ultimo dia), el anterior son
        los mismos meses de antes: septiembre se compara con agosto entero. Antes
        se restaban dias, y septiembre (30 dias) se comparaba con el 2 al 31 de
        agosto: se perdia el dia 1, que es cuando se cobra el sueldo y se paga el
        alquiler.
        """
        if self.desde.day == 1 and self.hasta == fin_de_mes(self.hasta):
            meses = (
                (self.hasta.year - self.desde.year) * 12
                + self.hasta.month - self.desde.month + 1
            )
            return Rango(primero_de_mes(self.desde, -meses), self.desde - timedelta(days=1))
        delta = timedelta(days=self.dias)
        return Rango(self.desde - delta, self.hasta - delta)


def fin_de_mes(d: date) -> date:
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def primero_de_mes(d: date, desplazamiento: int) -> date:
    """Dia 1 del mes que queda `desplazamiento` meses despues (o antes) del de `d`."""
    indice = d.year * 12 + d.month - 1 + desplazamiento
    return date(indice // 12, indice % 12 + 1, 1)


def rango_mes(anio: int, mes: int) -> Rango:
    ultimo = calendar.monthrange(anio, mes)[1]
    return Rango(date(anio, mes, 1), date(anio, mes, ultimo))


# calendar.month_abbr sale en ingles ("Sep 26") salvo que el sistema tenga el idioma
# en castellano, y ni Windows ni Docker lo tienen asi para Python. Se escriben a
# mano, con "Set" como se abrevia setiembre en Peru.
MESES_CORTOS = ("", "Ene", "Feb", "Mar", "Abr", "May", "Jun",
                 "Jul", "Ago", "Set", "Oct", "Nov", "Dic")


def etiqueta_mes(anio: int, mes: int) -> str:
    return f"{MESES_CORTOS[mes]} {str(anio)[2:]}"


def mismos_dias_del_anterior(rango: Rango, hoy: date) -> Rango | None:
    """El periodo anterior recortado a los mismos dias que lleva el actual.

    None si el periodo no esta en curso (ya termino, termina hoy o no ha empezado):
    entonces se compara con el anterior entero.
    """
    if not rango.desde <= hoy < rango.hasta:
        return None
    anterior = rango.anterior()
    llevados = timedelta(days=(hoy - rango.desde).days)
    return Rango(anterior.desde, min(anterior.desde + llevados, anterior.hasta))


def rango_por_defecto(primera: date | None, ultima: date | None, hoy: date) -> Rango:
    """Del primer movimiento al ultimo. El rango por defecto cuando no se pide uno."""
    if not primera:
        return Rango(date(hoy.year, 1, 1), hoy)
    # Un movimiento con una fecha imposible que se colara por fuera de la API (un
    # script, la base editada a mano) no puede estirar el historial a miles de meses.
    return Rango(
        max(primera, date(ANIO_MIN, 1, 1)),
        min(max(ultima, hoy), date(ANIO_MAX, 12, 31)),
    )
