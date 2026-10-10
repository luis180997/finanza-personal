"""Inversiones, casos de uso: importar estados, conciliar con correos, precios y API.

DATOS INVENTADOS: los estados de cuenta son los de test_inversiones_estados.py
(titular "Carlos Alberto Quispe Mamani", importes ficticios) y los correos de Hapi
reproducen la redaccion real con importes, Message-ID y nombres inventados. Cada
prueba usa su propia base SQLite en memoria: nunca la de la app.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import httpx
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.compartido.errores import DatoInvalido
from app.inversiones.adaptadores.salida.alpaca import PreciosAlpaca
from app.inversiones.adaptadores.salida.sqlite import InversionesSqlite
from app.inversiones.aplicacion.consultas import ServicioConsultas
from app.inversiones.aplicacion.correos import ServicioCorreosHapi
from app.inversiones.aplicacion.estados import ServicioEstados
from app.inversiones.aplicacion.precios import ServicioPrecios
from app.inversiones.aplicacion.puertos import Cierre, ErrorDePrecios
from app.inversiones.dominio.correo_hapi import CorreoHapi
from app.inversiones.dominio.entidades import EstadoOperacion, FuenteOperacion, Operacion, TipoOperacion
from app.plataforma import db as app_db
from app.plataforma.db import UnidadDeTrabajoSqlite
from tests.test_inversiones_dominio import EJECUTADA
from tests.test_inversiones_estados import estado_agosto, estado_setiembre

T = TipoOperacion
UTC = timezone.utc


@pytest.fixture()
def sesion():
    app_db.registrar_tablas()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
    engine.dispose()


class LectorFalso:
    DOCS = {b"ago": estado_agosto, b"set": estado_setiembre}

    def paginas(self, contenido: bytes):
        return self.DOCS[contenido]()


class BuzonFalso:
    configurado = True

    def __init__(self, correos: list[CorreoHapi]):
        self._correos = correos

    def correos(self, desde: date) -> list[CorreoHapi]:
        return [c for c in self._correos if c.recibido.date() >= desde]


def ejecutada(mid, cuando, lado, ticker, acciones, precio, total):
    cuerpo = EJECUTADA.format(lado=lado, ticker=ticker, acciones=acciones, precio=precio, total=total)
    return CorreoHapi(mid, cuando, "✅ Orden Ejecutada ", cuerpo)


def colocada(mid, cuando, lado, ticker, acciones):
    cuerpo = (f"Tu orden ha sido colocada. Tipo de orden:\n Orden de mercado\n Compra/Venta:\n {lado}\n "
              f"Ticker:\n {ticker}\n Cantidad:\n {acciones} acciones")
    return CorreoHapi(mid, cuando, "⏳ Orden Colocada", cuerpo)


def dividendo(mid, cuando, ticker, neto, pago):
    cuerpo = (f"Has recibido un dividendo por tus acciones de {ticker}. Detalles de la reinversión:\n "
              f"Monto recibido neto: ${neto}\n Fecha de pago: {pago}")
    return CorreoHapi(mid, cuando, f"💸 ¡Dividendo de {ticker} recibido!", cuerpo)


def fondos(mid, cuando, monto):
    return CorreoHapi(mid, cuando, "¡Fondos agregados a tu cuenta Hapi!",
                      f"¡Tu depósito de USD {monto} ha llegado y está listo para ser utilizado!")


def correos_del_mes() -> list[CorreoHapi]:
    """Lo que Hapi mando en agosto y setiembre de la cuenta inventada (con un aviso repetido)."""
    return [
        fondos("<f1@hapi>", datetime(2026, 8, 3, 15, 0, tzinfo=UTC), "850"),
        colocada("<c1@hapi>", datetime(2026, 8, 4, 14, 29, 50, tzinfo=UTC), "Compra", "VOO", "1"),
        ejecutada("<e1@hapi>", datetime(2026, 8, 4, 14, 30, tzinfo=UTC), "Compra", "VOO", "1", "500.00000", "500.15"),
        # Hapi repite el aviso de la misma ejecucion
        ejecutada("<e1b@hapi>", datetime(2026, 8, 4, 14, 41, tzinfo=UTC), "Compra", "VOO", "1", "500.00000", "500.15"),
        ejecutada("<e2@hapi>", datetime(2026, 8, 11, 15, 0, tzinfo=UTC), "Compra", "TSM", "1", "300.00000", "300.15"),
        dividendo("<d1@hapi>", datetime(2026, 8, 21, 12, 0, tzinfo=UTC), "VOO", "1.29", "2026-08-20"),
        ejecutada("<e3@hapi>", datetime(2026, 8, 31, 15, 0, tzinfo=UTC), "Compra", "VOO", "0.2", "600.00000", "120.15"),
        ejecutada("<e4@hapi>", datetime(2026, 9, 14, 15, 0, tzinfo=UTC), "Venta", "VOO", "0.5", "610.00000", "305.00"),
        # despues del ultimo estado: queda provisional
        dividendo("<d2@hapi>", datetime(2026, 10, 9, 12, 0, tzinfo=UTC), "TSM", "0.55", "2026-10-09"),
    ]


def servicios(s: Session, correos: list[CorreoHapi]):
    repo, uow = InversionesSqlite(s), UnidadDeTrabajoSqlite(s)
    return (ServicioEstados(LectorFalso(), repo, uow), ServicioCorreosHapi(BuzonFalso(correos), repo, uow), repo)


def firma(repo) -> list:
    return sorted(
        (o.tipo.value, o.simbolo or "", o.fecha.isoformat(), o.cantidad_micro or 0, o.monto_cents,
         o.retencion_cents, o.estado.value, o.correo_id or "")
        for o in repo.operaciones() if o.estado is not EstadoOperacion.descartada
    )


DOCS = [("ago.pdf", b"ago"), ("set.pdf", b"set")]


# ----------------------------------------------------------------------------- conciliacion


def test_correos_y_luego_estados_concilian_y_quitan_el_aviso_repetido(sesion):
    estados, correos, repo = servicios(sesion, correos_del_mes())
    r = correos.sincronizar()
    assert (r.operaciones, r.repetidos) == (7, 1)

    importacion = estados.importar(DOCS)
    assert importacion.importables == 2
    agosto = importacion.documentos[0]
    assert (agosto.conciliadas_con_correo, agosto.operaciones_nuevas, agosto.correos_descartados) == (5, 1, 0)

    ops = repo.operaciones()
    voo = next(o for o in ops if o.correo_id == "<e1@hapi>")
    # Del correo: la fecha real y la hora. Del estado: importe y liquidacion.
    assert (voo.estado, voo.fecha, voo.fecha_estimada, voo.fecha_liquidacion) == (
        EstadoOperacion.oficial, date(2026, 8, 4), False, date(2026, 8, 5))
    assert voo.ejecutada_at == datetime(2026, 8, 4, 14, 30)
    div = next(o for o in ops if o.correo_id == "<d1@hapi>")
    assert (div.monto_cents, div.retencion_cents) == (185, 56)        # bruto y retencion del estado
    # La venta del correo (305.00) pasa a lo que dice el estado (304.83, con tasas)
    venta = next(o for o in ops if o.tipo is T.venta)
    assert venta.monto_cents == 30483
    # El dividendo de octubre aun no tiene estado: sigue provisional
    assert next(o for o in ops if o.correo_id == "<d2@hapi>").estado is EstadoOperacion.provisional


def test_el_resultado_no_depende_del_orden(sesion):
    estados, correos, repo = servicios(sesion, correos_del_mes())
    correos.sincronizar()
    estados.importar(DOCS)
    primero_correos = firma(repo)

    app_db.registrar_tablas()
    otro = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(otro)
    with Session(otro) as s2:
        estados2, correos2, repo2 = servicios(s2, correos_del_mes())
        estados2.importar(DOCS)
        r = correos2.sincronizar()
        assert (r.completadas, r.operaciones, r.repetidos) == (6, 1, 1)
        assert firma(repo2) == primero_correos


def test_la_compra_pendiente_se_liquida_en_el_mes_siguiente_sin_duplicarse(sesion):
    estados, correos, repo = servicios(sesion, [])
    estados.importar(DOCS)
    compras_02 = [o for o in repo.operaciones() if o.tipo is T.compra and o.cantidad_micro == 200_000]
    assert len(compras_02) == 1
    assert (compras_02[0].fecha, compras_02[0].fecha_liquidacion) == (date(2026, 8, 31), date(2026, 9, 1))


def test_un_correo_de_una_orden_que_el_estado_no_recoge_se_descarta(sesion):
    fantasma = ejecutada("<x@hapi>", datetime(2026, 8, 18, 15, 0, tzinfo=UTC), "Compra", "VXUS", "2",
                         "70.00000", "140.15")
    estados, correos, repo = servicios(sesion, [fantasma])
    correos.sincronizar()
    r = estados.importar(DOCS[:1])
    assert r.documentos[0].correos_descartados == 1
    (op,) = [o for o in repo.operaciones() if o.correo_id == "<x@hapi>"]
    assert op.estado is EstadoOperacion.descartada and "2026-08" in op.nota


def test_la_vista_previa_no_guarda_nada_y_compara_con_lo_que_sabia_la_app(sesion):
    estados, correos, repo = servicios(sesion, correos_del_mes())
    correos.sincronizar()
    previa = estados.previsualizar(DOCS)
    assert previa.importables == 2 and not previa.confirmado
    assert repo.estados() == []
    agosto = previa.documentos[0].comparacion
    assert agosto.seguido_por_correo
    # La cuenta inventada ya tenia 1 VOO y 20.00 antes de agosto, sin ningun correo:
    # la app no podia saberlo y la comparacion lo muestra antes de corregirlo.
    assert [(d.simbolo, d.segun_app_micro, d.segun_estado_micro) for d in agosto.acciones] == [
        ("VOO", 1_000_000, 2_000_000)]
    assert agosto.efectivo_cents != 0


def test_no_se_puede_saltar_un_mes_y_lo_ya_importado_se_salta(sesion):
    estados, _, _ = servicios(sesion, [])
    estados.importar(DOCS[:1])
    with pytest.raises(DatoInvalido, match="todos estaban ya importados"):
        estados.importar(DOCS[:1])
    r = estados.importar(DOCS)                          # agosto se salta, entra setiembre
    assert [d.estado for d in r.documentos] == ["ya_importado", "nuevo"]


def test_un_mes_que_no_sigue_al_ultimo_no_entra(sesion):
    estados, _, _ = servicios(sesion, [])
    estados.importar(DOCS[:1])
    LectorFalso.DOCS[b"oct"] = lambda: estado_setiembre(periodo="October 1, 2026 - October 31, 2026")
    try:
        with pytest.raises(DatoInvalido, match="2026-09-01"):
            estados.importar([("oct.pdf", b"oct")])
    finally:
        del LectorFalso.DOCS[b"oct"]


def test_el_saldo_inicial_es_deposito_sin_historia_y_ajuste_con_correos(sesion):
    estados, correos, repo = servicios(sesion, [])
    estados.importar(DOCS[:1])
    # El estado inventado de agosto empieza con 20.00 en el deposito asegurado y con
    # 1 VOO (las 2 del cierre menos la comprada en el mes), que valia 1,000.00 al
    # empezar el mes segun la columna del mes anterior.
    (inicial,) = [o for o in repo.operaciones() if o.nombre == "Saldo inicial"]
    assert (inicial.tipo, inicial.monto_cents) == (T.deposito, 2000)
    (accion,) = [o for o in repo.operaciones() if o.tipo is T.posicion_inicial]
    assert (accion.simbolo, accion.cantidad_micro, accion.precio_micro, accion.monto_cents) == (
        "VOO", 1_000_000, 1_000_000_000, 0)

    # Llega un correo de julio (antes del primer estado) que explica 15.00 de ese saldo.
    correos.buzon = BuzonFalso([fondos("<f0@hapi>", datetime(2026, 7, 20, 15, 0, tzinfo=UTC), "15")])
    correos.sincronizar(desde=date(2026, 7, 1))
    (inicial,) = [o for o in repo.operaciones() if o.nombre == "Saldo inicial"]
    assert (inicial.tipo, inicial.monto_cents) == (T.ajuste_saldo, 500)


def test_las_consultas_cuadran_con_el_ultimo_estado(sesion):
    estados, correos, repo = servicios(sesion, correos_del_mes())
    correos.sincronizar()
    estados.importar(DOCS)
    consultas = ServicioConsultas(repo, precios_configurados=False, correo_configurado=True,
                                  ahora=lambda: datetime(2026, 10, 10, 15, 0, tzinfo=UTC))
    resumen = consultas.resumen()
    assert resumen["ultimo_estado"]["cuadra"] is True
    assert resumen["acciones"] == 1374.00                       # precios de cierre de setiembre
    assert resumen["efectivo"] == round(1.10 + 254.58 + 0.55, 2)   # + dividendo de octubre (correo)
    assert {p["simbolo"]: p["cantidad"] for p in consultas.posiciones()} == {"VOO": 1.7, "TSM": 2.0}
    assert consultas.accion("TSM")["posicion"]["cantidad"] == 2.0
    assert [e["periodo"] for e in consultas.estados_importados()] == ["2026-09", "2026-08"]


# ----------------------------------------------------------------------------- precios


def _alpaca(respuestas: list[httpx.Response]) -> tuple[PreciosAlpaca, list[httpx.Request]]:
    pedidas: list[httpx.Request] = []

    def manejar(request: httpx.Request) -> httpx.Response:
        pedidas.append(request)
        return respuestas.pop(0)

    return PreciosAlpaca("clave", "secreto", httpx.Client(transport=httpx.MockTransport(manejar))), pedidas


def test_alpaca_junta_los_tres_ajustes_y_sigue_las_paginas():
    barra = lambda dia, c: {"t": f"{dia}T04:00:00Z", "c": c}  # noqa: E731
    respuestas = [
        httpx.Response(200, json={"bars": {"NVDA": [barra("2024-06-07", 1200.0)]}, "next_page_token": "p2"}),
        httpx.Response(200, json={"bars": {"NVDA": [barra("2024-06-10", 121.5)]}, "next_page_token": None}),
        httpx.Response(200, json={"bars": {"NVDA": [barra("2024-06-07", 120.0), barra("2024-06-10", 121.5)]}}),
        httpx.Response(200, json={"bars": {"NVDA": [barra("2024-06-07", 119.9), barra("2024-06-10", 121.4)]}}),
    ]
    fuente, pedidas = _alpaca(respuestas)
    cierres = fuente.cierres(["NVDA"], date(2024, 6, 7), date(2024, 6, 10))["NVDA"]
    assert cierres == [
        Cierre(date(2024, 6, 7), 1_200_000_000, 120_000_000, 119_900_000),
        Cierre(date(2024, 6, 10), 121_500_000, 121_500_000, 121_400_000),
    ]
    assert pedidas[1].url.params["page_token"] == "p2"
    assert pedidas[0].headers["APCA-API-KEY-ID"] == "clave"


def test_alpaca_nunca_pide_los_ultimos_15_minutos_del_sip():
    """Con fecha sola, "hasta hoy" incluye los ultimos minutos y Alpaca rechaza la consulta."""
    ahora = datetime(2026, 10, 9, 21, 0, tzinfo=UTC)                  # viernes, bolsa cerrada
    pedidas: list[httpx.Request] = []

    def manejar(request: httpx.Request) -> httpx.Response:
        pedidas.append(request)
        return httpx.Response(200, json={"bars": {}})

    fuente = PreciosAlpaca("clave", "secreto", httpx.Client(transport=httpx.MockTransport(manejar)),
                           ahora=lambda: ahora)
    fuente.cierres(["VOO"], date(2026, 10, 1), date(2026, 10, 9))
    assert pedidas[0].url.params["end"] == "2026-10-09T20:44:00+00:00"
    fuente.cierres(["VOO"], date(2026, 10, 1), date(2026, 10, 8))     # dia ya cerrado: hasta su fin
    assert pedidas[-1].url.params["end"] == "2026-10-09T04:00:00+00:00"


def test_alpaca_distingue_claves_malas_de_consultas_fuera_del_plan():
    fuente, _ = _alpaca([httpx.Response(403, json={"message": "subscription does not permit querying recent SIP data"})])
    with pytest.raises(ErrorDePrecios, match="plan: subscription does not permit"):
        fuente.cierres(["VOO"], date(2026, 9, 1), date(2026, 9, 2))


def test_alpaca_con_claves_malas_no_muestra_las_claves():
    fuente, _ = _alpaca([httpx.Response(401, json={"message": "forbidden"})])
    with pytest.raises(ErrorDePrecios) as exc:
        fuente.cierres(["VOO"], date(2026, 9, 1), date(2026, 9, 2))
    assert "secreto" not in str(exc.value) and "ALPACA_SECRET_KEY" in str(exc.value)


class FuenteFalsa:
    configurada = True

    def __init__(self):
        self.pedidas: list[tuple] = []

    def cierres(self, simbolos, desde, hasta):
        self.pedidas.append((tuple(simbolos), desde, hasta))
        return {s: [Cierre(hasta, 100_000_000, 100_000_000, 100_000_000)] for s in simbolos}

    def barras(self, simbolos, desde, minutos):
        return {s: [(datetime(2026, 10, 9, 14, 0), 101_000_000)] for s in simbolos}


def test_los_precios_se_piden_una_vez_y_solo_lo_que_falta(sesion):
    estados, _, repo = servicios(sesion, [])
    estados.importar(DOCS)
    fuente = FuenteFalsa()
    ahora = datetime(2026, 10, 9, 23, 0, tzinfo=UTC)                 # viernes, bolsa cerrada
    servicio = ServicioPrecios(fuente, repo, UnidadDeTrabajoSqlite(sesion), ahora=lambda: ahora)
    r = servicio.actualizar()
    assert r.cierres == 2 and r.intradia == 0                          # TSM y VOO (que es tambien la referencia)
    assert {s for p in fuente.pedidas for s in p[0]} == {"TSM", "VOO"}
    assert servicio.actualizar().cierres == 0                          # ya esta al dia


def test_con_la_bolsa_abierta_se_guarda_el_intradia(sesion):
    estados, _, repo = servicios(sesion, [])
    estados.importar(DOCS)
    abierta = datetime(2026, 10, 9, 14, 5, tzinfo=UTC)                # 10:05 en Nueva York
    r = ServicioPrecios(FuenteFalsa(), repo, UnidadDeTrabajoSqlite(sesion), ahora=lambda: abierta).actualizar()
    assert r.intradia == 2


def test_sin_claves_no_se_pide_nada(sesion):
    _, _, repo = servicios(sesion, [])
    sin_claves = PreciosAlpaca("", "")
    r = ServicioPrecios(sin_claves, repo, UnidadDeTrabajoSqlite(sesion)).actualizar()
    assert (r.configurado, r.cierres) == (False, 0)


# ----------------------------------------------------------------------------- API


class FuenteConSplit(FuenteFalsa):
    """La segunda vez, el precio ajustado del ultimo dia guardado ya es otro: hubo un split."""

    def __init__(self):
        super().__init__()
        self.ajuste = 100_000_000

    def cierres(self, simbolos, desde, hasta):
        self.pedidas.append((tuple(simbolos), desde, hasta))
        dias = [desde, hasta] if desde != hasta else [desde]
        return {s: [Cierre(d, 100_000_000, self.ajuste, self.ajuste) for d in dias] for s in simbolos}


def test_un_split_nuevo_rehace_la_historia_ajustada(sesion):
    estados, _, repo = servicios(sesion, [])
    estados.importar(DOCS)
    fuente = FuenteConSplit()
    viernes = datetime(2026, 10, 9, 23, 0, tzinfo=UTC)
    ServicioPrecios(fuente, repo, UnidadDeTrabajoSqlite(sesion), ahora=lambda: viernes).actualizar()
    fuente.ajuste = 50_000_000                                     # split 2x1 en la historia
    fuente.pedidas.clear()
    lunes = datetime(2026, 10, 12, 23, 0, tzinfo=UTC)
    ServicioPrecios(fuente, repo, UnidadDeTrabajoSqlite(sesion), ahora=lambda: lunes).actualizar()
    # Se vuelve a pedir el ultimo dia guardado; como cambio, se baja todo otra vez.
    assert any(d == date(2026, 10, 9) for _, d, _ in fuente.pedidas)
    assert any(len(s) == 1 and d < date(2026, 8, 1) for s, d, _ in fuente.pedidas)
    viejo = repo.cierre("VOO", date(2026, 10, 9))
    assert viejo.cierre_split_micro == 50_000_000


def test_lo_vendido_hace_tiempo_no_se_vuelve_a_pedir(sesion):
    estados, _, repo = servicios(sesion, [])
    estados.importar(DOCS)
    # Un valor vendido entero en 2023: ya no cotiza y Alpaca no devuelve nada.
    for tipo, monto in ((T.compra, -10015), (T.venta, 9985)):
        repo.agregar(Operacion(tipo=tipo, simbolo="ZZZQ", nombre="ZZZQ", fecha=date(2023, 3, 1),
                               cantidad_micro=1_000_000, precio_micro=100_000_000, monto_cents=monto,
                               estado=EstadoOperacion.oficial, fuente=FuenteOperacion.estado_cuenta))
    sesion.commit()
    fuente = FuenteFalsa()
    ahora = datetime(2026, 10, 9, 23, 0, tzinfo=UTC)
    ServicioPrecios(fuente, repo, UnidadDeTrabajoSqlite(sesion), ahora=lambda: ahora).actualizar()
    (pedida,) = [p for p in fuente.pedidas if "ZZZQ" in p[0]]
    assert pedida[2] == date(2023, 3, 11)                          # solo hasta poco despues de venderlo
    fuente.pedidas.clear()
    ServicioPrecios(fuente, repo, UnidadDeTrabajoSqlite(sesion), ahora=lambda: ahora).actualizar()
    assert not [p for p in fuente.pedidas if "ZZZQ" in p[0]]


def _consultas(repo, ahora):
    return ServicioConsultas(repo, precios_configurados=True, correo_configurado=True, ahora=lambda: ahora)


def test_1d_sin_intradia_son_los_dos_ultimos_cierres_no_toda_la_historia(sesion):
    estados, _, repo = servicios(sesion, [])
    estados.importar(DOCS)
    for dia, precio in ((date(2026, 10, 8), 600_000_000), (date(2026, 10, 9), 610_000_000)):
        for s in ("VOO", "TSM"):
            repo.guardar_cierre(s, Cierre(dia, precio, precio, precio))
    sesion.commit()
    consultas = _consultas(repo, datetime(2026, 10, 10, 15, 0, tzinfo=UTC))
    assert [p["t"] for p in consultas.serie("1D")["puntos"]] == ["2026-10-08", "2026-10-09"]
    assert len(consultas.precios_de("VOO", "1D")["puntos"]) == 2
    assert len(consultas.serie("TODO")["puntos"]) > 2


def test_lo_que_va_del_anio_parte_del_ultimo_cierre_del_anterior():
    from app.inversiones.aplicacion.consultas import _recortar

    dias = [date(2025, 12, 30), date(2025, 12, 31), date(2026, 1, 2), date(2026, 1, 30), date(2026, 2, 2),
            date(2026, 2, 3)]
    hoy = date(2026, 2, 3)
    assert _recortar(dias, "YTD", hoy, lambda d: d)[0] == date(2025, 12, 31)
    assert _recortar(dias, "TODO", hoy, lambda d: d) == dias


def test_la_rentabilidad_por_mes_suma_la_ganancia_total(sesion):
    estados, _, repo = servicios(sesion, [])
    estados.importar(DOCS)
    for dia, precio in ((date(2026, 7, 31), 500_000_000), (date(2026, 8, 31), 550_000_000),
                        (date(2026, 9, 30), 540_000_000)):
        repo.guardar_cierre("VOO", Cierre(dia, precio, precio, precio))
    sesion.commit()
    consultas = _consultas(repo, datetime(2026, 10, 9, 21, 0, tzinfo=UTC))
    r = consultas.rentabilidad()
    assert [m["mes"] for m in r["por_mes"]][-1] == "2026-10"
    assert round(sum(m["ganancia"] for m in r["por_mes"]), 2) == consultas.resumen()["ganancia"]
    (anio,) = r["por_anio"]
    assert (anio["anio"], anio["en_curso"]) == (2026, True)
    assert r["total"]["rentabilidad"] == pytest.approx(r["acumulada"][-1]["tuya"])
    ytd = consultas.serie("YTD")
    assert ytd["periodo"]["ganancia"] == anio["ganancia"]


def test_la_variacion_del_dia_cuenta_lo_comprado_hoy(sesion):
    estados, _, repo = servicios(sesion, [])
    estados.importar(DOCS)                                         # 1.7 VOO al cierre de setiembre
    repo.guardar_cierre("VOO", Cierre(date(2026, 10, 8), 600_000_000, 600_000_000, 600_000_000))
    repo.guardar_cierre("VOO", Cierre(date(2026, 10, 9), 610_000_000, 610_000_000, 610_000_000))
    # Hoy (9/10) se compra 1 VOO a 608: gana 2 desde su compra, no 10 desde ayer.
    repo.agregar(Operacion(tipo=T.compra, simbolo="VOO", nombre="VOO", fecha=date(2026, 10, 9),
                           cantidad_micro=1_000_000, precio_micro=608_000_000, monto_cents=-60800,
                           estado=EstadoOperacion.provisional, fuente=FuenteOperacion.correo))
    sesion.commit()
    voo = next(p for p in _consultas(repo, datetime(2026, 10, 9, 21, 0, tzinfo=UTC)).posiciones()
               if p["simbolo"] == "VOO")
    assert voo["variacion_dia"] == round(1.7 * 10 + 2, 2)


def test_un_correo_ilegible_se_reintenta_cuando_cambia_el_lector(sesion, monkeypatch):
    from app.inversiones.aplicacion import correos as modulo

    hace_un_mes = datetime(2026, 9, 9, 15, 0, tzinfo=UTC)
    roto = CorreoHapi("<r@hapi>", hace_un_mes, "✅ Orden Ejecutada ", "Compra/Venta: Compra Acciones: 1")
    reciente = fondos("<f@hapi>", datetime(2026, 10, 9, 15, 0, tzinfo=UTC), "100")
    _, correos, repo = servicios(sesion, [roto, reciente])
    assert len(correos.sincronizar().ilegibles) == 1

    # Mismo lector: no se reintenta ni obliga a releer desde hace un mes.
    pedido = []
    correos.buzon = BuzonFalso([roto])
    correos.buzon.correos = lambda desde: pedido.append(desde) or []
    correos.sincronizar()
    assert pedido[0] > hace_un_mes.date()

    # Lector nuevo (se corrigio): se reintenta y la operacion aparece.
    monkeypatch.setattr(modulo, "_MARCA_LECTOR", "[lector otro]")
    arreglado = ejecutada("<r@hapi>", hace_un_mes, "Compra", "VOO", "1", "600.00000", "600.15")
    correos.buzon = BuzonFalso([arreglado])
    r = correos.sincronizar()
    assert (r.operaciones, r.ilegibles) == (1, [])
    assert repo.correo("<r@hapi>").resultado == "operacion"


def test_el_nombre_guardado_del_estado_no_lleva_el_numero_de_cuenta(sesion):
    estados, _, repo = servicios(sesion, [])
    estados.importar([("Doc_STATEMENT_5XX01010_ago.pdf", b"ago")])
    assert [e.archivo for e in repo.estados()] == ["estado_2026-08.pdf"]


def test_la_migracion_corrige_la_fecha_de_un_split_ya_importado(sesion):
    from app.plataforma import migraciones

    repo = InversionesSqlite(sesion)
    repo.agregar(Operacion(tipo=T.split, simbolo="NVDA", nombre="NVIDIA CORP", fecha=date(2024, 6, 11),
                           cantidad_micro=2_700_000, estado=EstadoOperacion.oficial,
                           fuente=FuenteOperacion.estado_cuenta))
    for dia, crudo, ajustado in ((date(2024, 6, 6), 1_200_000_000, 120_000_000),
                                 (date(2024, 6, 7), 1_210_000_000, 121_000_000),
                                 (date(2024, 6, 10), 122_000_000, 122_000_000),
                                 (date(2024, 6, 11), 121_000_000, 121_000_000)):
        repo.guardar_cierre("NVDA", Cierre(dia, crudo, ajustado, ajustado))
    sesion.commit()
    assert "NVDA 2024-06-11 -> 2024-06-10" in migraciones._inversiones_fecha_de_los_splits(sesion)
    (split,) = [o for o in repo.operaciones() if o.tipo is T.split]
    # Vale desde el dia del cambio de precio; cuadra con el estado el dia de su fila.
    assert (split.fecha, split.fecha_liquidacion) == (date(2024, 6, 10), date(2024, 6, 11))


def test_actualizar_mientras_otra_escritura_esta_en_curso_responde_409():
    from fastapi.testclient import TestClient

    from app.inversiones.adaptadores import fabrica
    from app.main import app

    with TestClient(app) as cliente, fabrica.en_exclusiva() as libre:
        assert libre
        respuesta = cliente.post("/api/inversiones/sincronizar")
        assert respuesta.status_code == 409


def test_la_api_responde_con_la_base_vacia_y_rechaza_lo_que_no_es_pdf():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as cliente:
        resumen = cliente.get("/api/inversiones/resumen")
        assert resumen.status_code == 200
        assert resumen.json()["valor"] == 0.0
        assert cliente.get("/api/inversiones/serie?rango=1A").json()["puntos"] == []
        assert cliente.get("/api/inversiones/serie?rango=5X").status_code == 422
        assert cliente.get("/api/inversiones/serie?rango=YTD").json()["periodo"] is None
        assert cliente.get("/api/inversiones/rentabilidad").json()["por_mes"] == []
        malo = cliente.post("/api/inversiones/estados/previsualizar",
                            files=[("archivos", ("notas.txt", b"hola", "text/plain"))])
        assert malo.status_code == 400
        assert cliente.get("/api/inversiones/acciones/NADA").status_code == 404
