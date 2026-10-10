"""Lector y validacion de los estados de cuenta de Apex (Hapi).

DATOS INVENTADOS: el titular ("Carlos Alberto Quispe Mamani"), el numero de
cuenta, las cantidades, precios e importes de este archivo son ficticios. Lo que
si reproduce el formato real es la redaccion de las lineas y la posicion de las
columnas, que es lo que lee el codigo. Las cifras estan elegidas para que cada
estado cuadre consigo mismo y con el siguiente; las pruebas que rompen algo lo
hacen a proposito.

Los estados se construyen linea a linea con `fila()`, que coloca cada importe
bajo su columna como hace el PDF real (alineado a la derecha).
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from app.inversiones.adaptadores.salida.pdf import lineas_desde_palabras
from app.inversiones.aplicacion.revision import ServicioRevision
from app.inversiones.dominio import estado_cuenta, validacion
from app.inversiones.dominio.estado_cuenta import (
    Linea, NoEsEstadoDeCuenta, Pagina, Palabra, Seccion,
)

TITULAR = "CARLOS ALBERTO QUISPE MAMANI"
CUENTA = "ACCOUNT NUMBER 5XX-01010-10 RR AAA"

# Bordes (x0, x1) de las cabeceras numericas, como en el PDF real.
COLUMNAS = {
    "QUANTITY": (405.1, 431.1), "PRICE": (475.7, 492.2),
    "DEBIT": (555.8, 571.7), "CREDIT": (616.6, 636.3),
}
_COLUMNA_DE = {"cantidad": "QUANTITY", "precio": "PRICE", "debito": "DEBIT", "credito": "CREDIT"}


def fila(texto: str = "", wh: str | None = None, **importes: str) -> Linea:
    """Texto desde el margen izquierdo; cada importe alineado a la derecha de su columna."""
    palabras, x = [], 40.0
    for tok in texto.split():
        palabras.append(Palabra(tok, x, x + 5 * len(tok)))
        x += 5 * len(tok) + 3
    if wh is not None:  # la retencion: "WH" y su importe en la columna de debito
        palabras.append(Palabra("WH", 520.0, 530.0))
        palabras.append(Palabra(wh, COLUMNAS["DEBIT"][1] - 5 * len(wh), COLUMNAS["DEBIT"][1]))
    for nombre, valor in importes.items():
        x1 = COLUMNAS[_COLUMNA_DE[nombre]][1]
        palabras.append(Palabra(valor, x1 - 5 * len(valor), x1))
    return Linea(palabras)


def cabecera_de_movimientos() -> Linea:
    izquierda = fila("TRANSACTION DATE TYPE DESCRIPTION").palabras
    return Linea(izquierda + [Palabra(c, x0, x1) for c, (x0, x1) in COLUMNAS.items()])


def pagina(numero: int, periodo: str, *lineas: Linea | str) -> Pagina:
    cuerpo = [l if isinstance(l, Linea) else fila(l) for l in lineas]
    return Pagina(numero, [fila(periodo), fila(CUENTA), fila(TITULAR), *cuerpo])


# ----------------------------------------------------------------------------- agosto


AGOSTO = "August 1, 2026 - August 31, 2026"


def estado_agosto(**cambios) -> list[Pagina]:
    """Deposito de 850, dos compras, un dividendo con retencion y una compra pendiente."""
    c = {
        "valor_voo": "$1,200.00", "total_dividendos": ("$0.56", "$1.85"), "liquidada_extra": None,
    } | cambios
    portada = pagina(
        1, AGOSTO,
        "OPENING BALANCE CLOSING BALANCE",
        "Cash Cash account $0.00 $1.10",
        # la leyenda del grafico cae en la misma linea, como en el PDF real
        "NET ACCOUNT BALANCE 0.00 1.10 FDIC Insured Deposits",
        "FDIC Insured Deposits 20.00 69.90 4.4%",
        "Securities 1,000.00 1,512.00",
        "Total Equity Holdings $1,020.00 $1,583.00",
    )
    cartera = pagina(
        2, AGOSTO,
        "PORTFOLIO SUMMARY",
        "DESCRIPTION CUSIP TYPE QUANTITY PRICE VALUE MARKET VALUE % CHANGE INCOME PORTFOLIO",
        "FDIC INSURED DEPOSITS",
        "THE INSURED DEPOSIT PROGRAM ISPAZ C 69.90 $1.00 $69.90 $20.00 250% 4.4%",
        "Total FDIC Insured Deposits $69.90 4.4%",
        "EQUITIES / OPTIONS",
        f"VANGUARD S&P 500 ETF VOO C 2 $600.00 {c['valor_voo']} $1,000.00 20% 18 75.8%",
        "TAIWAN SEMICONDUCTOR MFG CO TSM C 1 312.00 312.00 N/A 3 19.7",
        "LTD-SPONSORED ADR REPSTG 5 COM",
        "Total Equities $1,512.00 $21 95.5%",
        "Total Cash (Net Portfolio Balance) $1.10 0.1%",
        "TOTAL PRICED PORTFOLIO $1,583.00 $21",
        "ACCOUNT",
        cabecera_de_movimientos(),
        "BUY / SELL TRANSACTIONS",
        fila("BOUGHT 08/05/26 C VANGUARD S&P 500 ETF",
             cantidad="1", precio="$500.00", debito="$500.15"),
        "CUSIP: 922908363",
        fila("BOUGHT 08/12/26 C TAIWAN SEMICONDUCTOR MFG CO",
             cantidad="1", precio="300.00", debito="300.15"),
        "LTD-SPONSORED ADR REPSTG 5 COM",
        "CUSIP: 874039100",
        fila("Total Buy / Sell Transactions", debito="$800.30"),
        "DIVIDENDS AND INTEREST",
        fila("DIVIDEND 08/20/26 C VANGUARD S&P 500 ETF", precio="$1.85", credito="$1.85"),
        fila("CASH DIV ON 1 SHS", wh="0.56"),
        "REC 08/15/26 PAY 08/20/26",
        "NON-RES TAX WITHHELD",
        "CUSIP: 922908363",
        fila("Total Dividends And Interest",
             debito=c["total_dividendos"][0], credito=c["total_dividendos"][1]),
        "FUNDS PAID AND RECEIVED",
        fila("JOURNAL 08/03/26 C Journal from", credito="$850.00"),
        "HAPI",
        fila("Total Funds Paid And Received", credito="$850.00"),
        "TRADE SETTLEMENT ACCOUNT",
        fila("BOUGHT 08/31/26 C VANGUARD S&P 500 ETF",
             cantidad="0.2", precio="600.00", debito="120.15"),
        "CUSIP: 922908363",
        fila("Total Executed Trades Pending Settlement", debito="$120.15"),
    )
    barrido = pagina(
        3, AGOSTO,
        "FDIC INSURED DEPOSITS BANK ACTIVITY",
        "DATE ACTIVITY DESCRIPTION AMOUNT DEBIT CREDIT BALANCE",
        "Opening Balance 20.00",
        "08/04/26 SWEEP THE INSURED DEPOSIT PROGRAM 349.85 349.85 369.85",
        "FROM CASH ACCOUNT BALANCE",
        "08/12/26 REDEEMED THE INSURED DEPOSIT PROGRAM -300.15 300.15 69.70",
        "FUNDS REDEEMED",
        "08/17/26 INTEREST THE INSURED DEPOSIT PROGRAM 0.01 69.70",
        "INTEREST",
        "08/17/26 DIV REINV THE INSURED DEPOSIT PROGRAM 0.01 0.01 69.71",
        "INTEREST REINVESTMENT",
        "08/21/26 SWEEP THE INSURED DEPOSIT PROGRAM 0.19 0.19 69.90",
        "FROM CASH ACCOUNT BALANCE",
        "Closing Balance 69.90",
        "IMPORTANT INFORMATIO N",
        "Texto legal que no es un dato y que el lector tiene que saltarse sin mas.",
    )
    return [portada, cartera, barrido]


# ----------------------------------------------------------------------------- setiembre


SETIEMBRE = "September 1, 2026 - September 30, 2026"


def estado_setiembre(periodo: str = SETIEMBRE, con_liquidacion: bool = True) -> list[Pagina]:
    """Se liquida la pendiente, se vende media accion, TSM hace split 2x1 y se presta una accion."""
    liquidacion = (
        [fila("BOUGHT 09/01/26 C VANGUARD S&P 500 ETF",
              cantidad="0.2", precio="600.00", debito="120.15")]
        if con_liquidacion else []
    )
    portada = pagina(
        1, periodo,
        "OPENING BALANCE CLOSING BALANCE",
        "NET ACCOUNT BALANCE 1.10 1.10",
        "FDIC Insured Deposits 69.90 254.58",
        "Securities 1,512.00 1,374.00 92.4%",
        "Total Equity Holdings $1,583.00 $1,629.68",
    )
    cuerpo = pagina(
        2, periodo,
        "PORTFOLIO SUMMARY",
        "FDIC INSURED DEPOSITS",
        "THE INSURED DEPOSIT PROGRAM ISPAZ C 254.58 $1.00 $254.58 $69.90 264% 15.6%",
        "EQUITIES / OPTIONS",
        "VANGUARD S&P 500 ETF VOO C 1.7 $620.00 $1,054.00 $1,200.00 -12% 15 64.7%",
        "TAIWAN SEMICONDUCTOR MFG CO TSM C 2 160.00 320.00 312.00 3 3 19.6",
        "Total Equities $1,374.00 $18 84.3%",
        "ACCOUNT ACTIVITY (CONTINUED)",
        cabecera_de_movimientos(),
        "BUY / SELL TRANSACTIONS",
        *liquidacion,
        fila("BOUGHT 09/10/26 C TAIWAN SEMICONDUCTOR MFG CO", cantidad="1"),
        "STK SPLIT ON 1 SHS",
        "REC 09/08/26 PAY 09/09/26",
        "CUSIP: 874039100",
        # los estados antiguos ponen la cantidad vendida en negativo
        fila("SOLD 09/15/26 C VANGUARD S&P 500 ETF",
             cantidad="-0.5", precio="610.00", credito="304.83"),
        "CUSIP: 922908363",
        fila("Total Buy / Sell Transactions", debito="$120.15", credito="$304.83"),
        "SECURITIES RECEIVED AND DELIVERED",
        fila("JOURNAL 09/23/26 O VANGUARD S&P 500 ETF", cantidad="1"),
        "TO TYPE 7 FROM TYPE 1",
        fila("JOURNAL 09/23/26 C VANGUARD S&P 500 ETF", cantidad="-1"),
        "FROM TYPE 1 TO TYPE 7",
        fila("JOURNAL 09/24/26 C VANGUARD S&P 500 ETF", cantidad="1"),
        "TO TYPE 1 FROM TYPE 7",
        fila("JOURNAL 09/24/26 O VANGUARD S&P 500 ETF", cantidad="-1"),
        "FROM TYPE 7 TO TYPE 1",
        "Total Securities Received And Delivered",
        "Opening Balance 69.90",
        "09/16/26 SWEEP THE INSURED DEPOSIT PROGRAM 184.68 184.68 254.58",
        "FROM CASH ACCOUNT BALANCE",
        "Closing Balance 254.58",
    )
    return [portada, cuerpo]


def leer(paginas: list[Pagina]):
    return estado_cuenta.leer(paginas)


# ----------------------------------------------------------------------------- un mes


def test_un_mes_inventado_se_lee_entero_y_cuadra():
    e = leer(estado_agosto())

    assert (e.inicio, e.fin) == (date(2026, 8, 1), date(2026, 8, 31))
    assert [(p.simbolo, p.cantidad, p.valor_cents) for p in e.posiciones] == [
        ("VOO", Decimal("2"), 120000), ("TSM", Decimal("1"), 31200),
    ]
    assert e.fdic_cents == 6990
    assert e.portada["caja"] == (0, 110)
    assert validacion.validar(e) == []
    assert e.no_reconocidas == []


def test_compras_dividendo_deposito_y_pendiente_quedan_en_su_seccion():
    e = leer(estado_agosto())
    por_seccion = {s: [m for m in e.movimientos if m.seccion is s] for s in Seccion}

    voo, tsm = por_seccion[Seccion.compraventa]
    assert (voo.codigo, voo.cantidad, voo.precio, voo.debito_cents) == (
        "BOUGHT", Decimal("1"), Decimal("500.00"), 50015,
    )
    assert voo.cusip == "922908363"
    assert tsm.descripcion == "TAIWAN SEMICONDUCTOR MFG CO"

    (dividendo,) = por_seccion[Seccion.dividendos]
    assert (dividendo.credito_cents, dividendo.retencion_cents) == (185, 56)
    assert dividendo.debito_cents == 0

    (deposito,) = por_seccion[Seccion.fondos]
    assert (deposito.codigo, deposito.credito_cents) == ("JOURNAL", 85000)
    assert deposito.detalle == ["HAPI"]

    (pendiente,) = por_seccion[Seccion.pendientes]
    assert (pendiente.fecha, pendiente.cantidad) == (date(2026, 8, 31), Decimal("0.2"))


def test_el_500_del_nombre_es_descripcion_y_no_cantidad():
    e = leer(estado_agosto())
    voo = e.movimientos[0]
    assert voo.descripcion == "VANGUARD S&P 500 ETF"
    assert voo.cantidad == Decimal("1")


def test_el_titular_no_aparece_en_nada_de_lo_leido():
    e = leer(estado_agosto())
    textos = [p.nombre for p in e.posiciones] + [x for p in e.posiciones for x in p.detalle]
    textos += [m.descripcion for m in e.movimientos] + [d for m in e.movimientos for d in m.detalle]
    textos += e.no_reconocidas + list(e.portada)
    assert not any("QUISPE" in t or "5XX-01010" in t for t in textos)


def test_el_barrido_al_deposito_asegurado_se_lee_fila_a_fila():
    e = leer(estado_agosto())
    assert (e.barrido_apertura_cents, e.barrido_cierre_cents) == (2000, 6990)
    assert [(b.actividad, b.importe_cents, b.mueve_saldo) for b in e.barrido] == [
        ("SWEEP", 34985, True), ("REDEEMED", -30015, True), ("INTEREST", 1, False),
        ("DIV", 1, True), ("SWEEP", 19, True),
    ]


# ----------------------------------------------------------------------------- lo que debe fallar


def test_un_total_de_seccion_que_no_cuadra_es_error():
    e = leer(estado_agosto(total_dividendos=("$0.56", "$1.95")))
    assert [x.codigo for x in validacion.validar(e)] == ["TOTAL"]


def test_una_posicion_mal_leida_es_error_y_descuadra_la_cartera():
    e = leer(estado_agosto(valor_voo="$1,210.00"))
    codigos = {x.codigo for x in validacion.validar(e)}
    assert {"POSICION", "CARTERA"} <= codigos


def test_un_movimiento_de_caja_omitido_descuadra_la_caja():
    e = leer(estado_agosto())
    e.movimientos = [m for m in e.movimientos if m.seccion is not Seccion.fondos]
    assert "CAJA" in {x.codigo for x in validacion.validar(e)}


def test_una_actividad_desconocida_del_deposito_es_error():
    e = leer(estado_agosto())
    e.barrido[0] = replace(e.barrido[0], actividad="TRANSFER")
    assert "FDIC" in {x.codigo for x in validacion.validar(e)}


def test_un_documento_sin_paginas_de_estado_no_se_lee():
    avisos = Pagina(1, [fila("NOTICE OF CHANGES"), fila("APEX CONSUMER PRIVACY NOTICES")])
    with pytest.raises(NoEsEstadoDeCuenta):
        estado_cuenta.leer([avisos])


def test_las_paginas_de_avisos_previas_se_ignoran():
    avisos = Pagina(1, [fila("Disclosure - Annual Disclosure Statement"), fila("Page 1 of 12")])
    e = leer([avisos, *estado_agosto()])
    assert validacion.validar(e) == []


# ----------------------------------------------------------------------------- dos meses


def test_dos_meses_encadenan_con_split_venta_y_prestamo_de_valores():
    agosto, setiembre = leer(estado_agosto()), leer(estado_setiembre())

    assert validacion.validar(setiembre) == []
    assert validacion.validar_serie([agosto, setiembre]) == []

    split = next(m for m in setiembre.movimientos if m.es_split)
    assert (split.cantidad, split.precio, split.debito_cents) == (Decimal("1"), None, 0)
    venta = next(m for m in setiembre.movimientos if m.codigo == "SOLD")
    assert venta.cantidad == Decimal("0.5")
    prestamo = [m.cantidad for m in setiembre.movimientos if m.seccion is Seccion.valores]
    assert prestamo == [Decimal("1"), Decimal("-1"), Decimal("1"), Decimal("-1")]


def test_una_pendiente_que_no_aparece_liquidada_es_error():
    agosto = leer(estado_agosto())
    setiembre = leer(estado_setiembre(con_liquidacion=False))
    codigos = {x.codigo for x in validacion.validar_serie([agosto, setiembre])}
    assert {"PENDIENTE", "POSICIONES"} <= codigos


def test_un_mes_que_falta_en_la_serie_es_error():
    agosto = leer(estado_agosto())
    octubre = leer(estado_setiembre(periodo="October 1, 2026 - October 31, 2026"))
    (error,) = validacion.validar_serie([agosto, octubre])
    assert error.codigo == "SERIE"


# ----------------------------------------------------------------------------- adaptador y revision


def test_el_titulo_vertical_del_margen_no_se_cuela_en_las_filas():
    palabras = [
        {"text": "BOUGHT", "x0": 70, "x1": 100, "top": 300.4, "upright": True},
        {"text": "T", "x0": 40.9, "x1": 45, "top": 300.0, "upright": False},
        {"text": "08/05/26", "x0": 110, "x1": 140, "top": 300.9, "upright": True},
        {"text": "CUSIP:", "x0": 70, "x1": 95, "top": 310.0, "upright": True},
    ]
    assert [l.texto for l in lineas_desde_palabras(palabras)] == ["BOUGHT 08/05/26", "CUSIP:"]


class _LectorFalso:
    def __init__(self, documentos: dict[bytes, list[Pagina]]):
        self.documentos = documentos

    def paginas(self, contenido: bytes) -> list[Pagina]:
        return self.documentos[contenido]


def test_la_revision_acepta_una_serie_que_cuadra_y_marca_duplicados():
    lector = _LectorFalso({b"ago": estado_agosto(), b"set": estado_setiembre()})
    informe = ServicioRevision(lector).revisar(
        [("ago.pdf", b"ago"), ("set.pdf", b"set"), ("copia.pdf", b"ago")],
    )

    assert [d.valido for d in informe.documentos] == [True, True, False]
    assert informe.documentos[2].errores[0].codigo == "DUPLICADO"
    assert [e.periodo for e in informe.estados] == ["2026-08", "2026-09"]
    assert informe.errores_de_serie == []
    assert not informe.todo_cuadra  # por el duplicado


def test_la_revision_no_da_por_buena_una_serie_con_un_mes_roto():
    roto = estado_agosto(total_dividendos=("$0.56", "$9.99"))
    lector = _LectorFalso({b"ago": roto, b"set": estado_setiembre()})
    informe = ServicioRevision(lector).revisar([("ago.pdf", b"ago"), ("set.pdf", b"set")])
    assert [d.valido for d in informe.documentos] == [False, True]
    assert not informe.todo_cuadra
