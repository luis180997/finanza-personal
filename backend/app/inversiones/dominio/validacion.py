"""Comprobaciones de un estado de cuenta contra sus propios totales.

Es lo que permite fiarse de un lector de PDF sin un LLM: cada cifra leida tiene
que cuadrar con otra que el documento imprime por separado. Todo tipo de fila
afecta al menos a una comprobacion, asi que una fila mal leida u omitida no pasa
desapercibida:

    compras y ventas     -> total de la seccion, caja, posiciones del mes
    dividendos           -> total de la seccion, caja
    depositos y retiros  -> total de la seccion, caja
    entregas de acciones -> posiciones del mes
    deposito asegurado   -> saldo fila a fila, saldo final, portada

Un documento con cualquier error no se importa. No hay "casi cuadra".
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from app.inversiones.dominio.estado_cuenta import EstadoDeCuenta, Movimiento, Seccion

# Comision de Apex (hasta 0.15) mas las tasas regulatorias de las ventas (centavos).
_TOLERANCIA_COMISION_CENTS = 50
# Las posiciones muestran el precio con dos decimales: el valor puede diferir de
# cantidad x precio en media unidad del ultimo decimal por accion.
_MEDIO_CENTAVO = Decimal("0.005")

# Actividades del deposito asegurado. SWEEP mete la caja sobrante y REDEEMED la
# devuelve: mueven dinero entre caja y deposito. INTEREST y DIV REINV son el
# interes del propio deposito: no tocan la caja.
_ENTRE_CAJA_Y_FDIC = frozenset({"SWEEP", "REDEEMED"})
_SOLO_FDIC = frozenset({"INTEREST", "DIV"})

_TOTAL_DE_SECCION = {
    Seccion.compraventa: "Total Buy / Sell Transactions",
    Seccion.pendientes: "Total Executed Trades Pending Settlement",
    Seccion.dividendos: "Total Dividends And Interest",
    Seccion.fondos: "Total Funds Paid And Received",
}


@dataclass(frozen=True)
class Error:
    codigo: str
    mensaje: str

    def __str__(self) -> str:
        return f"{self.codigo} {self.mensaje}"


def _usd(cents: int) -> str:
    return f"{cents / 100:,.2f}"


def validar(estado: EstadoDeCuenta) -> list[Error]:
    """Comprobaciones dentro de un mismo documento."""
    errores: list[Error] = []
    errores += _posiciones(estado)
    errores += _totales_de_actividad(estado)
    errores += _compraventas(estado)
    errores += _barrido(estado)
    errores += _portada_y_caja(estado)
    return errores


def _posiciones(estado: EstadoDeCuenta) -> list[Error]:
    errores = []
    for p in estado.posiciones:
        calculado = p.cantidad * p.precio * 100
        tolerancia = 1 + p.cantidad * _MEDIO_CENTAVO * 100
        if abs(calculado - p.valor_cents) > tolerancia:
            errores.append(Error(
                "POSICION", f"{p.simbolo}: {p.cantidad} x {p.precio} no da {_usd(p.valor_cents)}",
            ))
    suma = sum(p.valor_cents for p in estado.posiciones)
    total = estado.totales_cartera.get("Total Equities")
    if total is None:
        if estado.posiciones:
            errores.append(Error("CARTERA", "falta la linea 'Total Equities'"))
    elif total != suma:
        errores.append(Error(
            "CARTERA", f"Total Equities {_usd(total)} != suma de posiciones {_usd(suma)}",
        ))
    return errores


def _totales_de_actividad(estado: EstadoDeCuenta) -> list[Error]:
    errores = []
    for seccion, nombre in _TOTAL_DE_SECCION.items():
        movs = [m for m in estado.movimientos if m.seccion is seccion]
        if not movs:
            continue
        if nombre not in estado.totales_actividad:
            errores.append(Error("TOTAL", f"{seccion.value}: falta '{nombre}'"))
            continue
        debito, credito = estado.totales_actividad[nombre]
        filas_d = sum(m.debito_cents + m.retencion_cents for m in movs)
        filas_c = sum(m.credito_cents for m in movs)
        if (debito, credito) != (filas_d, filas_c):
            errores.append(Error(
                "TOTAL",
                f"{seccion.value}: el documento dice debito {_usd(debito)} / "
                f"credito {_usd(credito)}, las filas suman {_usd(filas_d)} / {_usd(filas_c)}",
            ))
    return errores


def _compraventas(estado: EstadoDeCuenta) -> list[Error]:
    errores = []
    for m in estado.movimientos:
        if m.codigo not in ("BOUGHT", "SOLD") or m.es_split:
            continue
        importe = m.debito_cents or m.credito_cents
        if m.cantidad is None or m.precio is None or not importe:
            errores.append(Error(
                "OPERACION",
                f"{m.codigo} {m.fecha} {m.descripcion}: falta cantidad, precio o importe",
            ))
            continue
        if abs(m.cantidad * m.precio * 100 - importe) > _TOLERANCIA_COMISION_CENTS:
            errores.append(Error(
                "OPERACION",
                f"{m.codigo} {m.fecha} {m.descripcion}: "
                f"{m.cantidad} x {m.precio} no da {_usd(importe)}",
            ))
    return errores


def _barrido(estado: EstadoDeCuenta) -> list[Error]:
    if estado.barrido_apertura_cents is None:
        if estado.barrido:
            return [Error("FDIC", "hay movimientos del deposito asegurado sin saldo inicial")]
        return []
    errores = []
    saldo = estado.barrido_apertura_cents
    for b in estado.barrido:
        if b.actividad not in _ENTRE_CAJA_Y_FDIC | _SOLO_FDIC:
            errores.append(Error("FDIC", f"{b.fecha}: actividad desconocida '{b.actividad}'"))
        if b.mueve_saldo:
            saldo += b.importe_cents
        if saldo != b.saldo_cents:
            errores.append(Error(
                "FDIC", f"{b.fecha} {b.actividad}: saldo {_usd(saldo)} != {_usd(b.saldo_cents)}",
            ))
            saldo = b.saldo_cents
    if estado.barrido_cierre_cents is None:
        errores.append(Error("FDIC", "falta el saldo final del deposito asegurado"))
    elif saldo != (cierre := estado.barrido_cierre_cents):
        errores.append(Error("FDIC", f"saldo final {_usd(cierre)} != calculado {_usd(saldo)}"))
    elif cierre != estado.fdic_cents:
        errores.append(Error(
            "FDIC", f"saldo final {_usd(cierre)} != posicion {_usd(estado.fdic_cents)}",
        ))
    return errores


def _portada_y_caja(estado: EstadoDeCuenta) -> list[Error]:
    errores = []
    portada = estado.portada
    if "caja" not in portada:
        return [Error("PORTADA", "falta el saldo de caja (NET ACCOUNT BALANCE) de la portada")]
    # Sin acciones o sin deposito asegurado, la portada omite la linea: vale cero.
    suma = sum(p.valor_cents for p in estado.posiciones)
    valores = portada.get("valores", (0, 0))[1]
    if valores != suma:
        errores.append(Error(
            "PORTADA", f"valores al cierre {_usd(valores)} != posiciones {_usd(suma)}",
        ))
    fdic = portada.get("fdic", (0, 0))[1]
    if fdic != estado.fdic_cents:
        errores.append(Error(
            "PORTADA", f"deposito asegurado {_usd(fdic)} != {_usd(estado.fdic_cents)}",
        ))
    # Caja: apertura + abonos - cargos - lo barrido al deposito asegurado = cierre.
    # Lo pendiente de liquidar todavia no ha tocado la caja.
    apertura, cierre = portada["caja"]
    neto = sum(
        m.credito_cents - m.debito_cents - m.retencion_cents
        for m in estado.movimientos
        if m.tipo_cuenta in ("C", "M") and m.seccion is not Seccion.pendientes
    )
    barrido = sum(b.importe_cents for b in estado.barrido if b.actividad in _ENTRE_CAJA_Y_FDIC)
    if apertura + neto - barrido != cierre:
        errores.append(Error(
            "CAJA",
            f"apertura {_usd(apertura)} + movimientos {_usd(neto)} - barrido {_usd(barrido)} "
            f"= {_usd(apertura + neto - barrido)}, pero el cierre es {_usd(cierre)}",
        ))
    return errores


# ----------------------------------------------------------------------------- serie


def validar_serie(estados: list[EstadoDeCuenta]) -> list[Error]:
    """Comprobaciones entre meses. `estados` en orden cronologico."""
    errores: list[Error] = []
    simbolos = _simbolos_por_nombre(estados)
    for previo, actual in zip(estados, estados[1:]):
        if actual.inicio != previo.fin + timedelta(days=1):
            errores.append(Error("SERIE", f"falta el periodo entre {previo.fin} y {actual.inicio}"))
            continue
        errores += _cadena_de_posiciones(previo, actual, simbolos)
        errores += _pendientes_liquidadas(previo, actual)
    return errores


def _simbolos_por_nombre(estados: list[EstadoDeCuenta]) -> dict[str, str]:
    """Los movimientos traen el nombre del valor; las posiciones, nombre y simbolo."""
    simbolos = {}
    for e in estados:
        for p in e.posiciones:
            simbolos[p.nombre] = p.simbolo
    return simbolos


def simbolo_de(mov: Movimiento, simbolos: dict[str, str]) -> str:
    if mov.descripcion in simbolos:
        return simbolos[mov.descripcion]
    for nombre, simbolo in simbolos.items():
        if nombre.startswith(mov.descripcion) or mov.descripcion.startswith(nombre):
            return simbolo
    return mov.descripcion


def _cadena_de_posiciones(
    previo: EstadoDeCuenta, actual: EstadoDeCuenta, simbolos: dict[str, str],
) -> list[Error]:
    """Posiciones del mes anterior + lo liquidado este mes = posiciones de este mes."""
    esperado: dict[str, Decimal] = {}
    for p in previo.posiciones:
        esperado[p.simbolo] = esperado.get(p.simbolo, Decimal(0)) + p.cantidad
    for m in actual.movimientos:
        if m.seccion is Seccion.pendientes or m.cantidad is None:
            continue
        if m.codigo in ("BOUGHT", "SOLD") or m.seccion is Seccion.valores:
            cantidad = -m.cantidad if m.codigo == "SOLD" else m.cantidad
            s = simbolo_de(m, simbolos)
            esperado[s] = esperado.get(s, Decimal(0)) + cantidad
    real: dict[str, Decimal] = {}
    for p in actual.posiciones:
        real[p.simbolo] = real.get(p.simbolo, Decimal(0)) + p.cantidad
    errores = []
    for s in sorted(set(esperado) | set(real)):
        a, b = esperado.get(s, Decimal(0)), real.get(s, Decimal(0))
        if a != b:
            errores.append(Error(
                "POSICIONES",
                f"{actual.periodo} {s}: el mes anterior mas lo operado da {a.normalize()}, "
                f"el estado dice {b.normalize()}",
            ))
    return errores


def _pendientes_liquidadas(previo: EstadoDeCuenta, actual: EstadoDeCuenta) -> list[Error]:
    """Lo que quedo pendiente a fin de mes aparece liquidado, una vez, en el siguiente."""
    errores = []
    for m in previo.movimientos:
        if m.seccion is not Seccion.pendientes:
            continue
        iguales = [
            x for x in actual.movimientos
            if x.seccion is Seccion.compraventa and x.codigo == m.codigo
            and x.cantidad == m.cantidad and x.fecha >= m.fecha
            and (x.debito_cents, x.credito_cents) == (m.debito_cents, m.credito_cents)
        ]
        if len(iguales) != 1:
            errores.append(Error(
                "PENDIENTE",
                f"{m.codigo} {m.fecha} {m.descripcion} pendiente en {previo.periodo} aparece "
                f"{len(iguales)} veces liquidada en {actual.periodo}",
            ))
    return errores
