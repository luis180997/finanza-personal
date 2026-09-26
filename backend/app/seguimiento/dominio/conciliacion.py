"""Seguimiento: tu dinero real en cada fecha contra lo que registraste.

Para cada par de cortes consecutivos:

    diferencia real  = total de este corte - total del anterior
    efecto del dolar = dolares del corte anterior x (tipo de cambio ahora - antes)
    registrado       = ingresos - gastos registrados entre las dos fechas
    descuadre        = diferencia real - efecto del dolar - registrado

Descuadre cero: registraste todo. Positivo: tu dinero crecio mas de lo que dicen
tus movimientos (un ingreso sin registrar, lo que gano una inversion). Negativo:
crecio menos (un gasto sin registrar).

El periodo va desde el dia siguiente al corte anterior hasta el dia del corte,
ambos incluidos: un corte es el saldo al final de su dia.

Sustituye a la columna "Suma Beneficios" del Excel, que era la suma a mano de
ingresos menos gastos: comprobado contra el historial (13/09/2026), su diferencia
coincidia al centimo con lo registrado en la app en casi todos los periodos.
"""
from __future__ import annotations

import calendar
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.compartido.corte import ANIO_MAX, ANIO_MIN
from app.compartido.dinero import parse_money, to_amount, to_cents
from app.seguimiento.dominio.entidades import SaldoCorte, SaldoCuenta

MONEDAS = ("PEN", "USD")
NOMBRE_TARJETA = "Tarjeta de crédito"
# Por encima de esto (S/ 1.00) el Total del Excel y la suma de sus cuentas no son
# el mismo numero: no es redondeo.
_TOLERANCIA_TOTAL_CENTS = 100


@dataclass
class Saldo:
    cuenta: str
    moneda: str
    es_deuda: bool
    monto_cents: int


def _redondear(valor: Decimal) -> int:
    return int(valor.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def tipo_cambio_a_diezmil(valor: float | str | Decimal) -> int:
    return _redondear(Decimal(str(valor)) * 10000)


def a_soles_cents(monto_cents: int, moneda: str, tipo_cambio_diezmil: int) -> int:
    if moneda != "USD":
        return monto_cents
    return _redondear(Decimal(monto_cents) * tipo_cambio_diezmil / 10000)


def total_cents(saldos, tipo_cambio_diezmil: int) -> int:
    """Todas las cuentas en soles, restando las deudas. Siempre la misma formula:
    el Excel dejaba fuera Pichincha ($) en la mitad de los cortes."""
    return sum(
        (-1 if s.es_deuda else 1) * a_soles_cents(s.monto_cents, s.moneda, tipo_cambio_diezmil)
        for s in saldos
    )


def dolares_netos_cents(saldos) -> int:
    return sum((-1 if s.es_deuda else 1) * s.monto_cents for s in saldos if s.moneda == "USD")


# ---------------------------------------------------------------------------- serie
def serie(
    cortes: list[SaldoCorte],
    saldos_por_corte: dict[int, list[SaldoCuenta]],
    totales_registrados: Callable[[date, date], tuple[int, int]],
) -> list[dict]:
    """Todos los cortes, del mas antiguo al mas reciente, con su comparacion.

    `cortes` llega ordenado por fecha. `totales_registrados(desde_excluido, hasta)` da
    (ingresos, gastos) en soles registrados en ese periodo.
    """
    salida: list[dict] = []
    anterior: tuple[SaldoCorte, int, int] | None = None
    for corte in cortes:
        saldos = saldos_por_corte.get(corte.id, [])
        total = total_cents(saldos, corte.tipo_cambio_diezmil)
        dolares = dolares_netos_cents(saldos)
        fila = {
            "id": corte.id,
            "fecha": corte.fecha.isoformat(),
            "tipo_cambio": corte.tipo_cambio_diezmil / 10000,
            "origen": corte.origen,
            "notas": corte.notas,
            "total": to_amount(total),
            "saldos": [
                {"cuenta": s.cuenta, "moneda": s.moneda, "es_deuda": s.es_deuda,
                 "monto": to_amount(s.monto_cents)}
                for s in saldos
            ],
            "periodo": None,
        }
        if anterior is not None:
            corte_ant, total_ant, dolares_ant = anterior
            ingresos, gastos = totales_registrados(corte_ant.fecha, corte.fecha)
            # Sin tipo de cambio en alguno de los dos cortes no hay con que medirlo:
            # lo que pasara con los dolares queda dentro de la diferencia real.
            efecto = (
                _redondear(
                    Decimal(dolares_ant)
                    * (corte.tipo_cambio_diezmil - corte_ant.tipo_cambio_diezmil) / 10000
                )
                if corte.tipo_cambio_diezmil and corte_ant.tipo_cambio_diezmil else 0
            )
            dif_real = total - total_ant
            registrado = ingresos - gastos
            fila["periodo"] = {
                "desde": corte_ant.fecha.isoformat(),
                "dias": (corte.fecha - corte_ant.fecha).days,
                "dif_real": to_amount(dif_real),
                "ingresos": to_amount(ingresos),
                "gastos": to_amount(gastos),
                "registrado": to_amount(registrado),
                "efecto_dolar": to_amount(efecto),
                "descuadre": to_amount(dif_real - efecto - registrado),
                # Desde setiembre de 2026 los ingresos no llegan por correo: un periodo
                # sin ingresos casi siempre es un sueldo sin registrar.
                "sin_ingresos": ingresos == 0,
            }
        salida.append(fila)
        anterior = (corte, total, dolares)
    return salida


def resumen(filas: list[dict]) -> dict:
    periodos = [f["periodo"] for f in filas if f["periodo"]]
    ultimos = periodos[-6:]
    return {
        "cortes": len(filas),
        "total_actual": filas[-1]["total"] if filas else None,
        "fecha_actual": filas[-1]["fecha"] if filas else None,
        "descuadre_ultimo": ultimos[-1]["descuadre"] if ultimos else None,
        "descuadre_medio_6": (
            round(sum(abs(p["descuadre"]) for p in ultimos) / len(ultimos), 2) if ultimos else None
        ),
    }


def cuentas_sugeridas(filas: list[dict]) -> list[dict]:
    """Las cuentas del ultimo corte: con ellas arranca el formulario del siguiente."""
    if not filas:
        return []
    return [
        {"cuenta": s["cuenta"], "moneda": s["moneda"], "es_deuda": s["es_deuda"]}
        for s in filas[-1]["saldos"]
    ]


# ------------------------------------------------------------------------ estimacion
VENTANA_TENDENCIA_DIAS = 365
MESES_ESTIMADOS = 12
_DIAS_POR_MES = Decimal("30.436875")   # 365.2425 / 12


def _fin_de_mes(anio: int, mes: int) -> date:
    return date(anio, mes, calendar.monthrange(anio, mes)[1])


def _mes_siguiente(anio: int, mes: int) -> tuple[int, int]:
    return (anio + 1, 1) if mes == 12 else (anio, mes + 1)


def proyeccion(filas: list[dict]) -> dict | None:
    """Estimacion simple de cuanto tendras a fin de cada uno de los proximos meses.

    El ritmo es la recta que mejor pasa por tus cortes del ultimo año (minimos
    cuadrados), y la estimacion lo sigue desde el ultimo corte. Un año entero
    compensa los meses buenos y los malos (gratificaciones, un gasto grande); con
    menos de 3 cortes, o todos en menos de dos meses, no hay tendencia que valga.
    Es una guia: supone que todo sigue igual.
    """
    if not filas:
        return None
    ultima = date.fromisoformat(filas[-1]["fecha"])
    puntos = []
    for f in filas:
        dia = date.fromisoformat(f["fecha"])
        if (ultima - dia).days <= VENTANA_TENDENCIA_DIAS:
            puntos.append((dia, to_cents(f["total"])))
    if len(puntos) < 3 or (ultima - puntos[0][0]).days < 60:
        return None

    xs = [Decimal((dia - puntos[0][0]).days) for dia, _ in puntos]
    ys = [Decimal(c) for _, c in puntos]
    media_x = sum(xs) / len(xs)
    media_y = sum(ys) / len(ys)
    centimos_por_dia = sum((x - media_x) * (y - media_y) for x, y in zip(xs, ys)) / sum(
        (x - media_x) ** 2 for x in xs
    )

    base = puntos[-1][1]
    anio, mes = ultima.year, ultima.month
    if _fin_de_mes(anio, mes) == ultima:
        anio, mes = _mes_siguiente(anio, mes)
    meses = []
    for _ in range(MESES_ESTIMADOS):
        fin = _fin_de_mes(anio, mes)
        estimado = base + _redondear(centimos_por_dia * (fin - ultima).days)
        meses.append({"fecha": fin.isoformat(), "total": to_amount(estimado)})
        anio, mes = _mes_siguiente(anio, mes)
    return {
        "desde": puntos[0][0].isoformat(),
        "cortes_usados": len(puntos),
        "ritmo_mensual": to_amount(_redondear(centimos_por_dia * _DIAS_POR_MES)),
        "meses": meses,
    }


# --------------------------------------------------------------------------- escribir
def actualizar_corte(
    corte: SaldoCorte,
    *,
    fecha: date,
    tipo_cambio_diezmil: int,
    notas: str | None,
    origen: str | None,
    ahora: datetime,
) -> None:
    """Los datos del propio corte. Sus saldos se reemplazan enteros (`saldos_de`)."""
    corte.fecha = fecha
    corte.tipo_cambio_diezmil = tipo_cambio_diezmil
    corte.notas = (notas or "").strip() or None
    if origen:
        corte.origen = origen
    corte.updated_at = ahora


def saldos_de(corte_id: int, saldos: list[Saldo]) -> list[SaldoCuenta]:
    """Una fila por cuenta, en el orden en que llegaron (el del formulario)."""
    return [
        SaldoCuenta(
            corte_id=corte_id, cuenta=s.cuenta, moneda=s.moneda, es_deuda=s.es_deuda,
            monto_cents=s.monto_cents, orden=orden,
        )
        for orden, s in enumerate(saldos)
    ]


# ------------------------------------------------------------------------- importar
_COLUMNA_CUENTA = re.compile(
    r"^(?P<nombre>.+?)\s*\(\s*(?P<moneda>us\$|\$|usd|s/\.?|pen)\s*\)$", re.IGNORECASE,
)


def _norm(texto: Any) -> str:
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFD", str(texto or ""))
        if unicodedata.category(c) != "Mn"
    )
    return " ".join(sin_tildes.lower().split())


def _numero(valor: Any) -> float | None:
    if valor is None or valor == "" or isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    leido = parse_money(str(valor))
    return float(leido) if leido is not None else None


@dataclass
class CorteLeido:
    fila: int
    fecha: date
    tipo_cambio_diezmil: int
    saldos: list[Saldo]
    total_excel_cents: int | None


@dataclass
class LecturaExcel:
    hoja: str
    cortes: list[CorteLeido] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)


def _mapear_cabecera(cabecera) -> dict:
    """Fecha, tipo de cambio ("Dólar"), Total y una columna por cuenta, como
    "BCP (S/)" o "Hapi ($)". "Dif. Total" y "Suma Beneficios" se ignoran: la app
    las calcula."""
    mapa: dict = {"fecha": None, "tipo_cambio": None, "total": None, "cuentas": []}
    for i, crudo in enumerate(cabecera):
        texto = " ".join(str(crudo or "").split())
        clave = _norm(texto)
        if not clave:
            continue
        if clave == "fecha":
            mapa["fecha"] = i
        elif clave in ("dolar", "tipo de cambio", "tc"):
            mapa["tipo_cambio"] = i
        elif clave == "total":
            mapa["total"] = i
        elif m := _COLUMNA_CUENTA.match(texto):
            nombre = m.group("nombre").strip()
            moneda = "USD" if ("$" in m.group("moneda") or "us" in m.group("moneda").lower()) else "PEN"
            es_deuda = _norm(nombre).startswith(("credito", "tarjeta"))
            mapa["cuentas"].append((i, NOMBRE_TARJETA if es_deuda else nombre, moneda, es_deuda))
    return mapa


def leer_libro(libro, hoja: str | None = None) -> LecturaExcel:
    """Lee el historial de saldos de un libro ya abierto (`hojas` y `filas(hoja)`).
    No escribe nada."""
    candidatas = [hoja] if hoja in libro.hojas else libro.hojas
    for nombre in candidatas:
        filas = libro.filas(nombre)
        cabecera = next(filas, None)
        if not cabecera:
            continue
        mapa = _mapear_cabecera(cabecera)
        if mapa["fecha"] is not None and mapa["cuentas"]:
            return _leer_filas(nombre, filas, mapa)
    raise ValueError(
        "No hay ninguna hoja con una columna Fecha y columnas de cuentas como "
        "'BCP (S/)' o 'Hapi ($)'."
    )


def _leer_filas(hoja: str, filas, mapa: dict) -> LecturaExcel:
    lectura = LecturaExcel(hoja=hoja)
    celda = lambda fila, i: fila[i] if i is not None and i < len(fila) else None  # noqa: E731

    for numero, fila in enumerate(filas, start=2):
        valor = celda(fila, mapa["fecha"])
        fecha = valor.date() if isinstance(valor, datetime) else valor if isinstance(valor, date) else None
        if fecha is None:
            continue
        if not ANIO_MIN <= fecha.year <= ANIO_MAX:
            lectura.avisos.append(f"Fila {numero}: la fecha {fecha} no es posible y se salta.")
            continue

        saldos = []
        for i, cuenta, moneda, es_deuda in mapa["cuentas"]:
            monto = _numero(celda(fila, i))
            if monto is None:
                continue          # celda vacia: esa cuenta no existia en esa fecha
            if monto < 0:         # un saldo negativo es una deuda, y al reves
                monto, es_deuda = -monto, not es_deuda
            saldos.append(Saldo(cuenta, moneda, es_deuda, to_cents(round(monto, 2))))
        if not saldos:
            continue

        tipo_cambio = _numero(celda(fila, mapa["tipo_cambio"]))
        if any(s.moneda == "USD" for s in saldos) and not tipo_cambio:
            lectura.avisos.append(
                f"Fila {numero} ({fecha:%d/%m/%Y}): tiene saldos en dolares pero no tipo de "
                "cambio. Se salta."
            )
            continue
        total_excel = _numero(celda(fila, mapa["total"]))
        lectura.cortes.append(CorteLeido(
            fila=numero, fecha=fecha,
            tipo_cambio_diezmil=tipo_cambio_a_diezmil(tipo_cambio) if tipo_cambio else 0,
            saldos=saldos,
            total_excel_cents=to_cents(round(total_excel, 2)) if total_excel is not None else None,
        ))

    for previo, actual in zip(lectura.cortes, lectura.cortes[1:]):
        if actual.fecha <= previo.fecha:
            lectura.avisos.append(
                f"Fila {actual.fila}: la fecha {actual.fecha:%d/%m/%Y} va despues de la del "
                f"{previo.fecha:%d/%m/%Y} (fila {previo.fila}). Si esta mal escrita, corrigela "
                "en Seguimiento."
            )

    distintos = [
        c for c in lectura.cortes
        if c.total_excel_cents is not None
        and abs(total_cents(c.saldos, c.tipo_cambio_diezmil) - c.total_excel_cents)
        > _TOLERANCIA_TOTAL_CENTS
    ]
    if distintos:
        ultimo = max(distintos, key=lambda c: c.fecha)
        lectura.avisos.append(
            f"En {len(distintos)} corte(s) el Total del Excel no coincide con la suma de sus "
            f"cuentas (el mas reciente, {ultimo.fecha:%d/%m/%Y}: Excel "
            f"S/ {to_amount(ultimo.total_excel_cents):,.2f}, suma S/ "
            f"{to_amount(total_cents(ultimo.saldos, ultimo.tipo_cambio_diezmil)):,.2f}). La app "
            "usa siempre la suma de todas las cuentas."
        )
    return lectura
