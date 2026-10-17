"""Inversiones, dominio puro: correos de Hapi, calendario, cartera y metricas.

DATOS INVENTADOS: el titular ("Carlos"), los importes, cantidades, precios y
Message-ID son ficticios. Los cuerpos de correo conservan la redaccion y la
disposicion exactas de los correos reales de Hapi (etiqueta y valor en lineas
distintas, como sale del HTML), que es lo que lee el codigo. Las fechas son
reales cuando la prueba depende del calendario (festivos, cambio a T+1).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.inversiones.dominio import calendario, cartera, correo_hapi, libro, metricas
from app.inversiones.dominio.correo_hapi import CorreoHapi, TipoCorreo
from app.inversiones.dominio.entidades import EstadoOperacion, FuenteOperacion, Operacion, TipoOperacion
from app.inversiones.dominio.estado_cuenta import Seccion
from tests.test_inversiones_estados import estado_agosto, estado_setiembre, leer

T = TipoOperacion
UTC = timezone.utc


def correo(asunto: str, cuerpo: str, cuando=datetime(2026, 8, 4, 14, 30, tzinfo=UTC), mid="<a1@hapi>"):
    return CorreoHapi(message_id=mid, recibido=cuando, asunto=asunto, cuerpo=cuerpo)


EJECUTADA = """Hola Carlos,
 Tu orden ha sido completada. Puedes revisar los datos de tu orden a continuación:
 Tipo de orden:
 Orden de mercado
 Compra/Venta:
 {lado}
 Ticker:
 {ticker}
 Acciones:
 {acciones}
 Fee de Apex:
 US$ 0.15
 Precio promedio:
 US$ {precio}
 Venta total:
 US$ {total}
 Estado:
 Orden completada
 Tus fondos estarán disponibles después del periodo de liquidación T+1."""

EJECUTADA_2022 = """Hola Carlos,
 Tu orden ha sido completada. Puedes revisar los datos de tu orden a continuación:
 Tipo de orden:
 Orden de mercado
 Comprar/Vender:
 Vender
 Ticker:
 SPGI
 Acciónes:
 0.02345
 Comisión:
 US$ 0
 Precio promedio:
 US$ 301.1234
 Venta total:
 US$ 7.06
 Estado:
 Orden completada"""

DIVIDENDO = """Descubre cuánto recibiste
 ¡Tus dividendos de TSM ya están aquí! 💘
 ¡Hola, Carlos!
 ¡Buenas noticias! Has recibido un dividendo por tus acciones de TSM. 🎉
 Detalles de la reinversión:
 Monto recibido neto: $0.55
 Fecha de pago: 2026-10-09"""


# ----------------------------------------------------------------------------- correos


def test_lee_una_ejecucion_con_el_formato_actual():
    ev = correo_hapi.leer(correo("✅ Orden Ejecutada ", EJECUTADA.format(
        lado="Compra", ticker="VOO", acciones="0.3", precio="600.10000", total="180.18")))
    assert (ev.tipo, ev.ticker, ev.lado) == (TipoCorreo.ejecutada, "VOO", "compra")
    assert (ev.cantidad, ev.precio, ev.total, ev.comision) == (
        Decimal("0.3"), Decimal("600.10000"), Decimal("180.18"), Decimal("0.15"))
    assert ev.tipo_orden == "Orden de mercado"


def test_lee_una_venta_que_dice_venta_y_no_vender():
    ev = correo_hapi.leer(correo("✅ Orden Ejecutada ", EJECUTADA.format(
        lado="Venta", ticker="AMZN", acciones="1.2", precio="250.00000", total="299.85")))
    assert ev.lado == "venta"


def test_lee_una_ejecucion_con_las_etiquetas_de_2022():
    ev = correo_hapi.leer(correo("Orden Ejecutada ✅", EJECUTADA_2022))
    assert (ev.ticker, ev.lado, ev.cantidad, ev.comision) == ("SPGI", "venta", Decimal("0.02345"), Decimal("0"))


def test_lee_un_dividendo_sin_dos_puntos_en_el_asunto_ni_us_en_el_importe():
    ev = correo_hapi.leer(correo("💸 ¡Dividendo de TSM recibido!", DIVIDENDO))
    assert (ev.tipo, ev.ticker, ev.monto, ev.fecha_pago) == (
        TipoCorreo.dividendo, "TSM", Decimal("0.55"), date(2026, 10, 9))


@pytest.mark.parametrize("asunto, cuerpo, monto, pagado", [
    ("Tu solicitud de depósito  🏛️",
     "Hemos recibido tu solicitud de depósito con los siguientes detalles: Método de pago: Depósito "
     "Monto a pagar: 302.99 USD Monto a recibir: 300 USD", Decimal("300"), Decimal("302.99")),
    ("Link de pago para solicitud de depósito en Hapi",
     "tu solicitud de depósito con los siguientes detalles: Método de pago: Depósito Monto: 10 USD "
     "Para completar tu depósito ingresa al siguiente link", Decimal("10"), None),
])
def test_lee_las_solicitudes_de_deposito_de_ambas_epocas(asunto, cuerpo, monto, pagado):
    ev = correo_hapi.leer(correo(asunto, cuerpo))
    assert (ev.tipo, ev.monto, ev.monto_pagado) == (TipoCorreo.solicitud_deposito, monto, pagado)


def test_lee_fondos_agregados_y_retiro():
    fondos = correo_hapi.leer(correo("¡Fondos agregados a tu cuenta Hapi!",
                                     "¡Tu depósito de USD 250 ha llegado y está listo para ser utilizado!"))
    assert fondos.monto == Decimal("250")
    retiro = correo_hapi.leer(correo("Hemos recibido tu solicitud de retiro",
                                     "Monto a retirar:\n 300 USD\n Costo del retiro:\n 7.99 USD\n "
                                     "Monto a recibir:\n 292.01 USD"))
    assert (retiro.monto, retiro.costo) == (Decimal("300"), Decimal("7.99"))


def test_la_cripto_y_los_codigos_se_ignoran():
    cripto = correo_hapi.leer(correo("✅ Orden Ejecutada ", EJECUTADA.format(
        lado="Compra", ticker="ETHUSD", acciones="0.01", precio="2500.00000", total="25.30")))
    assert (cripto.tipo, cripto.motivo) == (TipoCorreo.ignorado, "criptomoneda")
    codigo = correo_hapi.leer(correo("Código de verificación Hapi", "Tu código de verificación hapi es: ABC123"))
    assert codigo.tipo is TipoCorreo.ignorado


def test_una_ejecucion_sin_ticker_es_ilegible():
    with pytest.raises(correo_hapi.CorreoIlegible, match="ticker"):
        correo_hapi.leer(correo("✅ Orden Ejecutada ", "Compra/Venta: Compra Acciones: 1"))


# ----------------------------------------------------------------------------- calendario


def test_dia_de_colon_no_se_liquida_aunque_la_bolsa_abra():
    assert calendario.es_habil(date(2022, 10, 10))
    assert calendario.liquidacion(date(2022, 10, 7)) == date(2022, 10, 12)
    assert calendario.operacion_desde_liquidacion(date(2022, 10, 12)) == date(2022, 10, 7)


def test_cierre_extraordinario_no_se_opera_pero_si_se_liquida():
    assert not calendario.es_habil(date(2025, 1, 9))
    assert calendario.liquidacion(date(2025, 1, 8)) == date(2025, 1, 9)


def test_el_paso_de_t2_a_t1_y_el_viernes_santo():
    assert calendario.liquidacion(date(2024, 5, 24)) == date(2024, 5, 29)   # T+2 sobre Memorial Day
    assert calendario.liquidacion(date(2024, 5, 28)) == date(2024, 5, 29)   # ya T+1
    assert calendario.operacion_desde_liquidacion(date(2024, 5, 29)) == date(2024, 5, 28)
    assert not calendario.es_habil(date(2026, 4, 3))                        # Viernes Santo


def test_el_horario_es_el_de_nueva_york_con_su_horario_de_verano():
    # 9:35 en Nueva York: 13:35 UTC en verano, 14:35 UTC en invierno
    assert calendario.abierta(datetime(2026, 7, 15, 13, 35, tzinfo=UTC))
    assert not calendario.abierta(datetime(2026, 12, 15, 13, 35, tzinfo=UTC))
    assert calendario.abierta(datetime(2026, 12, 15, 14, 35, tzinfo=UTC))


def test_una_orden_fuera_de_sesion_cuenta_el_dia_de_bolsa_siguiente():
    sabado = datetime(2026, 8, 8, 15, 0, tzinfo=UTC)
    assert calendario.dia_de_bolsa(sabado) == date(2026, 8, 10)


# ----------------------------------------------------------------------------- cartera


def op(tipo, fecha, monto, simbolo="VOO", cantidad=None, precio=None, comision=None, retencion=0,
       estado=EstadoOperacion.oficial):
    return Operacion(tipo=tipo, simbolo=simbolo, nombre=simbolo, fecha=fecha, monto_cents=monto,
                     cantidad_micro=cantidad, precio_micro=precio, comision_cents=comision,
                     retencion_cents=retencion, estado=estado, fuente=FuenteOperacion.estado_cuenta)


def test_costo_promedio_ganancia_realizada_y_split():
    ops = [
        op(T.deposito, date(2026, 1, 2), 100000, simbolo=None),
        op(T.compra, date(2026, 1, 5), -20015, cantidad=1_000_000, precio=200_000_000, comision=15),
        op(T.compra, date(2026, 2, 5), -30015, cantidad=1_000_000, precio=300_000_000, comision=15),
        op(T.split, date(2026, 3, 1), 0, cantidad=2_000_000),                  # 2x1: de 2 a 4 acciones
        op(T.venta, date(2026, 4, 1), 39985, cantidad=2_000_000, precio=200_000_000, comision=15),
    ]
    c = cartera.calcular(ops)
    p = c.posiciones["VOO"]
    assert p.cantidad_micro == 2_000_000
    # Costo total 500.30 de 4 acciones; se venden 2 -> sale la mitad del costo.
    assert p.costo_cents == Decimal("25015")
    assert p.realizada_cents == Decimal(39985 - 25015)
    assert p.costo_promedio_micro == 125_075_000
    assert c.efectivo_cents == 100000 - 20015 - 30015 + 39985
    assert c.comisiones_operacion_cents == 45


def test_dividendos_ajustes_y_aportes_con_cripto():
    ops = [
        op(T.deposito, date(2026, 1, 2), 50000, simbolo=None),
        op(T.retiro, date(2026, 1, 20), -10000, simbolo=None, comision=799),
        op(T.cripto_salida, date(2026, 2, 1), -4000, simbolo=None),
        op(T.cripto_entrada, date(2026, 3, 1), 3800, simbolo=None),
        op(T.dividendo, date(2026, 2, 10), 100, retencion=30),
        op(T.ajuste_impuesto, date(2026, 3, 10), 5),
        op(T.ajuste_saldo, date(2026, 1, 1), -150, simbolo=None),
    ]
    c = cartera.calcular(ops)
    assert c.aportes_cents == 50000 - 10000 - 200          # la cripto que no volvio, como retiro
    assert c.posiciones["VOO"].retenciones_cents == 25
    assert c.ajustes_cents == -150
    assert c.comisiones_retiro_cents == 799


def test_las_descartadas_no_cuentan_y_vender_de_mas_avisa():
    ops = [
        op(T.compra, date(2026, 1, 5), -10000, cantidad=1_000_000, precio=100_000_000),
        op(T.compra, date(2026, 1, 5), -10000, cantidad=1_000_000, precio=100_000_000,
           estado=EstadoOperacion.descartada),
        op(T.venta, date(2026, 2, 5), 30000, cantidad=2_000_000, precio=150_000_000),
    ]
    c = cartera.calcular(ops)
    assert c.posiciones["VOO"].cantidad_micro == 0
    assert len(c.avisos) == 1


def test_la_cartera_liquidada_usa_la_fecha_de_liquidacion():
    compra = op(T.compra, date(2026, 8, 31), -12015, cantidad=200_000, precio=600_000_000)
    assert cartera.calcular_liquidado([compra], date(2026, 8, 31)).abiertas() == []
    assert cartera.calcular_liquidado([compra], date(2026, 9, 1)).abiertas()[0].cantidad_micro == 200_000


# ----------------------------------------------------------------------------- metricas


def test_xirr_de_un_anio_con_diez_por_ciento():
    tasa = metricas.xirr([(date(2025, 1, 1), -100000), (date(2026, 1, 1), 110000)])
    assert tasa == pytest.approx(0.10, abs=1e-6)


def test_xirr_sin_solucion_o_con_poca_historia_es_none():
    assert metricas.xirr([(date(2026, 1, 1), -100), (date(2026, 1, 10), 110)]) is None
    assert metricas.xirr([(date(2025, 1, 1), 100), (date(2026, 1, 1), 110)]) is None


def test_referencia_compra_el_indice_con_cada_aporte():
    indice = metricas.SeriePrecios([(date(2026, 1, 2), 100_000_000), (date(2026, 6, 1), 120_000_000)])
    valor = metricas.valor_si_fuera_indice([(date(2026, 1, 1), 10000)], indice, date(2026, 6, 1))
    assert valor == 12000                         # 100 USD a 100 -> 1 parte a 120


def test_aporte_mensual_es_la_media_del_ultimo_anio_neta_de_retiros():
    flujos = [(date(2025, 6, 1), 500000),                         # hace mas de un anio: no cuenta
              (date(2025, 11, 3), 120000), (date(2026, 4, 2), 60000), (date(2026, 9, 1), -36000)]
    assert metricas.aporte_mensual(flujos, date(2026, 10, 9)) == (120000 + 60000 - 36000) / 12


def test_aporte_mensual_con_menos_de_un_anio_se_reparte_entre_los_meses_que_lleva():
    """Repartir siempre entre 12 daba 104 dolares de media a cinco meses de 250."""
    cada_dia_1 = [(date(2026, m, 1), 25000) for m in (6, 7, 8, 9, 10)]
    assert metricas.aporte_mensual(cada_dia_1, date(2026, 10, 16)) == 25000

    # Deposita el 25: el 16 de octubre aun no toco, octubre no cuenta todavia
    cada_dia_25 = [(date(2026, m, 25), 25000) for m in (6, 7, 8, 9)]
    assert metricas.aporte_mensual(cada_dia_25, date(2026, 10, 16)) == 25000

    # El primer deposito, este mismo mes
    assert metricas.aporte_mensual([(date(2026, 10, 2), 25000)], date(2026, 10, 16)) == 25000
    assert metricas.aporte_mensual([], date(2026, 10, 16)) == 0


def test_serie_diaria_usa_el_ultimo_precio_conocido():
    ops = [op(T.deposito, date(2026, 8, 3), 100000, simbolo=None),
           op(T.compra, date(2026, 8, 4), -50000, cantidad=1_000_000, precio=500_000_000)]
    precios = {"VOO": metricas.SeriePrecios([(date(2026, 8, 4), 500_000_000), (date(2026, 8, 6), 520_000_000)])}
    puntos = {p.fecha: p for p in metricas.serie_diaria(ops, precios, date(2026, 8, 7))}
    assert puntos[date(2026, 8, 5)].valor_cents == 100000          # sin precio nuevo: el del 4
    assert puntos[date(2026, 8, 7)].valor_cents == 102000
    assert puntos[date(2026, 8, 7)].aportes_cents == 100000


def _punto(dia, valor, aportes, ajustes=0):
    return metricas.Punto(dia, valor, 0, aportes, ajustes)


def test_un_deposito_no_es_rentabilidad():
    """10% de ganancia, un deposito diez veces mayor y otro 10%: 21%, no el 11% que
    saldria de dividir la ganancia entre todo lo aportado."""
    puntos = [_punto(date(2026, 3, 2), 100000, 100000),
              _punto(date(2026, 3, 3), 110000, 100000),
              _punto(date(2026, 3, 4), 1110000, 1100000),         # entra 10,000: no es ganancia
              _punto(date(2026, 3, 5), 1221000, 1100000)]
    dias = metricas.rentabilidad_diaria(puntos)
    assert [round(d.rentabilidad, 6) for d in dias] == [0, 0.10, 0, 0.10]
    (marzo,) = metricas.por_periodo(dias, lambda d: f"{d:%Y-%m}")
    assert marzo.rentabilidad == pytest.approx(0.21)
    assert (marzo.ganancia_cents, marzo.aportes_cents, marzo.valor_final_cents) == (121000, 1100000, 1221000)


def test_el_dinero_que_entra_cuenta_desde_el_inicio_del_dia_y_el_que_sale_hasta_el_final():
    puntos = [_punto(date(2026, 3, 2), 1000, 1000),
              _punto(date(2026, 3, 3), 102000, 101000),            # entra 1,000 y gana 10
              _punto(date(2026, 3, 4), 0, -1000),                  # se retira todo
              _punto(date(2026, 3, 5), 50000, 49000)]              # vuelve a entrar
    dias = metricas.rentabilidad_diaria(puntos)
    assert dias[1].rentabilidad == pytest.approx(1000 / 101000)    # no 1000 / 1000
    assert [d.rentabilidad for d in dias[2:]] == [0, 0]


def test_el_ajuste_del_saldo_resta_en_dolares_pero_no_en_el_porcentaje():
    puntos = [_punto(date(2026, 3, 30), 12000, 12000),
              _punto(date(2026, 3, 31), 10750, 12000, ajustes=-1250)]
    dias = metricas.rentabilidad_diaria(puntos)
    assert (dias[1].rentabilidad, dias[1].ganancia_cents) == (0, -1250)


def test_por_mes_por_anio_y_acumulada_con_el_indice_al_lado():
    puntos = [_punto(date(2026, 1, 29), 100000, 100000),
              _punto(date(2026, 1, 30), 110000, 100000),
              _punto(date(2026, 2, 2), 121000, 100000)]
    indice = metricas.SeriePrecios([(date(2026, 1, 29), 100_000_000), (date(2026, 1, 30), 105_000_000),
                                    (date(2026, 2, 2), 110_250_000)])
    dias = metricas.rentabilidad_diaria(puntos, indice)
    enero, febrero = metricas.por_periodo(dias, lambda d: f"{d:%Y-%m}")
    assert (enero.clave, enero.rentabilidad, enero.referencia) == ("2026-01", pytest.approx(0.10), pytest.approx(0.05))
    assert (febrero.rentabilidad, febrero.referencia) == (pytest.approx(0.10), pytest.approx(0.05))
    (anio,) = metricas.por_periodo(dias, lambda d: str(d.year))
    assert (anio.rentabilidad, anio.referencia) == (pytest.approx(0.21), pytest.approx(0.1025))
    assert metricas.acumulada(dias)[-1] == (date(2026, 2, 2), pytest.approx(0.21), pytest.approx(0.1025))


def test_sin_precios_del_indice_no_hay_referencia():
    dias = metricas.rentabilidad_diaria([_punto(date(2026, 1, 29), 1000, 1000),
                                         _punto(date(2026, 1, 30), 1100, 1000)])
    (p,) = metricas.por_periodo(dias, lambda _: "todo")
    assert p.referencia is None
    assert metricas.acumulada(dias)[-1][2] is None


def test_dividendos_provisionales_cuentan_su_neto_sin_inventar_bruto():
    ops = [op(T.dividendo, date(2026, 9, 10), 182, retencion=55),
           op(T.dividendo, date(2026, 10, 9), 55, estado=EstadoOperacion.provisional)]
    r = metricas.dividendos(ops)
    assert (r.total.bruto_cents, r.total.retencion_cents, r.total.neto_cents) == (182, 55, 182 - 55 + 55)
    assert r.por_mes["2026-10"].neto_sin_detalle_cents == 55


# ----------------------------------------------------------------------------- libro


def _simbolos():
    return {"VANGUARD S&P 500 ETF": "VOO", "TAIWAN SEMICONDUCTOR MFG CO": "TSM"}


def test_el_estado_se_traduce_y_cuadra_en_efectivo():
    e = leer(estado_agosto())
    filas = libro.del_estado(e, _simbolos())
    tipos = [(f.op.tipo, f.pendiente) for f in filas]
    assert tipos == [(T.compra, False), (T.compra, False), (T.dividendo, False), (T.deposito, False),
                     (T.compra, True), (T.interes, False)]
    voo = filas[0].op
    assert (voo.simbolo, voo.fecha, voo.fecha_estimada, voo.fecha_liquidacion) == (
        "VOO", date(2026, 8, 4), True, date(2026, 8, 5))
    assert voo.comision_cents == 15
    pendiente = filas[4].op
    assert (pendiente.fecha, pendiente.fecha_estimada, pendiente.fecha_liquidacion) == (date(2026, 8, 31), False, None)
    assert libro.cuadre_de_efectivo(e, filas) == 0


def test_el_split_y_el_prestamo_de_valores():
    filas = libro.del_estado(leer(estado_setiembre()), _simbolos())
    assert [f.op.tipo for f in filas] == [T.compra, T.split, T.venta]   # los JOURNAL de prestamo no
    assert filas[1].op.cantidad_micro == 1_000_000


def test_el_split_se_anota_el_dia_en_que_el_precio_cotiza_dividido():
    """Pago el viernes 07/06/2024: el precio cotiza dividido desde el lunes 10, no el
    11 en que lo anota el estado. Anotarlo tarde daba una caida falsa de un dia."""
    e = leer(estado_setiembre())
    split = next(m for m in e.movimientos if m.es_split)
    split.fecha = date(2024, 6, 11)
    split.detalle = ["STK SPLIT ON 0.30000 SHS", "REC 06/06/24 PAY 06/07/24"]
    assert libro.fecha_del_split(split) == date(2024, 6, 10)
    split.detalle = ["STK SPLIT ON 0.30000 SHS"]                      # sin PAY: la de la fila
    assert libro.fecha_del_split(split) == date(2024, 6, 11)


def test_una_fila_desconocida_detiene_la_traduccion():
    e = leer(estado_agosto())
    e.movimientos[3].codigo = "WIRE"
    with pytest.raises(libro.FilaDesconocida, match="WIRE"):
        libro.del_estado(e, _simbolos())


def test_la_retencion_en_fila_aparte_se_suma_a_su_dividendo():
    e = leer(estado_agosto())
    dividendo = next(m for m in e.movimientos if m.codigo == "DIVIDEND")
    retencion = type(dividendo)(seccion=Seccion.fondos, codigo="DIVIDEND", fecha=dividendo.fecha,
                                tipo_cuenta="C", descripcion=dividendo.descripcion, debito_cents=10)
    e.movimientos.insert(0, retencion)
    (div,) = [f.op for f in libro.del_estado(e, _simbolos()) if f.op.tipo is T.dividendo]
    assert (div.monto_cents, div.retencion_cents) == (185, 66)


def test_un_correo_y_su_fila_oficial_emparejan():
    e = leer(estado_agosto())
    filas = libro.del_estado(e, _simbolos())
    ev = correo_hapi.leer(correo("✅ Orden Ejecutada ", EJECUTADA.format(
        lado="Compra", ticker="VOO", acciones="1", precio="500.00000", total="500.15"),
        cuando=datetime(2026, 8, 4, 14, 30, tzinfo=UTC)))
    del_correo = libro.del_correo(ev)
    assert libro.emparejan(del_correo, filas[0].op, pendiente=False)
    assert not libro.emparejan(del_correo, filas[1].op, pendiente=False)
