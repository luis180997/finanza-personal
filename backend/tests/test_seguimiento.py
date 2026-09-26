"""Seguimiento: cortes de saldo real contra lo registrado. Sobre la base temporal."""
from __future__ import annotations

import io
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.seguimiento.dominio import conciliacion as seguimiento
from app.seguimiento.dominio.conciliacion import Saldo


@pytest.fixture(scope="module")
def cliente():
    with TestClient(app) as c:
        yield c


def _corte(cliente, fecha: str, tipo_cambio, saldos: list[dict], notas=None) -> int:
    r = cliente.post("/api/seguimiento/cortes", json={
        "fecha": fecha, "tipo_cambio": tipo_cambio, "notas": notas, "saldos": saldos,
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _cortes(cliente) -> dict[str, dict]:
    return {c["fecha"]: c for c in cliente.get("/api/seguimiento").json()["cortes"]}


def test_el_total_suma_soles_y_dolares_al_cambio_y_resta_las_deudas():
    saldos = [
        Saldo("BCP", "PEN", False, 100000),
        Saldo("Hapi", "USD", False, 10000),
        Saldo("Tarjeta de crédito", "PEN", True, 25050),
    ]
    tc = seguimiento.tipo_cambio_a_diezmil(3.71)
    assert tc == 37100
    assert seguimiento.total_cents(saldos, tc) == 100000 + 37100 - 25050
    assert seguimiento.dolares_netos_cents(saldos) == 10000


def test_el_descuadre_es_lo_que_no_explican_tus_movimientos(cliente):
    # 2031: ningun otro test usa ese año
    _corte(cliente, "2031-03-01", 3.50, [
        {"cuenta": "BCP", "moneda": "PEN", "monto": 1000},
        {"cuenta": "Hapi", "moneda": "USD", "monto": 100},
    ])
    for dia, monto, direccion in (("05", 800, "ingreso"), ("10", 300, "gasto"), ("01", 999, "gasto")):
        r = cliente.post("/api/movimientos", json={
            "amount": monto, "direction": direccion, "merchant": "seguimiento",
            "occurred_at": f"2031-03-{dia}T12:00:00",
        })
        assert r.status_code == 201, r.text
    _corte(cliente, "2031-03-31", 3.60, [
        {"cuenta": "BCP", "moneda": "PEN", "monto": 1450},
        {"cuenta": "Hapi", "moneda": "USD", "monto": 100},
    ])

    corte = _cortes(cliente)["2031-03-31"]
    periodo = corte["periodo"]
    assert corte["total"] == 1450 + 360
    assert periodo["dif_real"] == 460                   # 1810 - 1350
    assert periodo["efecto_dolar"] == 10                # 100 $ x (3.60 - 3.50)
    # El gasto del dia 1 es del periodo anterior: el corte es el saldo al final del dia
    assert periodo["ingresos"] == 800 and periodo["gastos"] == 300
    assert periodo["registrado"] == 500
    assert periodo["descuadre"] == -50                  # 50 soles gastados sin registrar
    assert periodo["sin_ingresos"] is False


def test_la_estimacion_sigue_la_tendencia_del_ultimo_anio():
    filas = [
        {"fecha": "2033-01-01", "total": 90000},   # hace mas de un año: no cuenta
        {"fecha": "2035-01-01", "total": 1000},
        {"fecha": "2035-01-31", "total": 1300},
        {"fecha": "2035-03-02", "total": 1600},
        {"fecha": "2035-04-01", "total": 1900},
    ]
    p = seguimiento.proyeccion(filas)
    assert p["desde"] == "2035-01-01" and p["cortes_usados"] == 4
    assert p["ritmo_mensual"] == 304.37                   # 10 soles al dia x 30.44 dias
    assert p["meses"][0] == {"fecha": "2035-04-30", "total": 2190.0}   # 1900 + 29 dias x 10
    assert p["meses"][8]["fecha"] == "2035-12-31"
    assert len(p["meses"]) == 12


def test_sin_cortes_suficientes_no_se_estima():
    assert seguimiento.proyeccion([]) is None
    dos = [{"fecha": "2035-01-01", "total": 1}, {"fecha": "2035-06-01", "total": 2}]
    assert seguimiento.proyeccion(dos) is None
    en_tres_dias = [{"fecha": f"2035-01-0{d}", "total": d} for d in (1, 2, 3)]
    assert seguimiento.proyeccion(en_tres_dias) is None


def test_un_corte_no_se_duplica_ni_acepta_datos_incoherentes(cliente):
    _corte(cliente, "2032-01-15", 3.4, [{"cuenta": "BCP", "monto": 10}])
    url = "/api/seguimiento/cortes"
    assert cliente.post(url, json={"fecha": "2032-01-15", "saldos": [{"cuenta": "BBVA", "monto": 5}]}).status_code == 409

    sin_cambio = cliente.post(url, json={
        "fecha": "2032-02-01", "saldos": [{"cuenta": "Hapi", "moneda": "USD", "monto": 5}],
    })
    assert sin_cambio.status_code == 422 and "tipo de cambio" in sin_cambio.text
    repetida = cliente.post(url, json={
        "fecha": "2032-02-02", "saldos": [{"cuenta": "BCP", "monto": 1}, {"cuenta": "bcp", "monto": 2}],
    })
    assert repetida.status_code == 422
    assert cliente.post(url, json={"fecha": "1999-12-31", "saldos": [{"cuenta": "BCP", "monto": 1}]}).status_code == 422
    assert cliente.post(url, json={"fecha": "2032-02-03", "saldos": [{"cuenta": "BCP", "monto": -5}]}).status_code == 422
    assert cliente.post(url, json={"fecha": "2032-02-04", "saldos": []}).status_code == 422


def test_editar_y_borrar_un_corte(cliente):
    corte_id = _corte(cliente, "2033-06-01", None, [{"cuenta": "BCP", "monto": 100}])
    r = cliente.put(f"/api/seguimiento/cortes/{corte_id}", json={
        "fecha": "2033-06-02", "tipo_cambio": None,
        "saldos": [{"cuenta": "BCP", "monto": 150}, {"cuenta": "Efectivo", "monto": 20}],
    })
    assert r.status_code == 200, r.text
    corte = next(c for c in _cortes(cliente).values() if c["id"] == corte_id)
    assert corte["fecha"] == "2033-06-02" and corte["total"] == 170
    assert [s["cuenta"] for s in corte["saldos"]] == ["BCP", "Efectivo"]

    assert cliente.delete(f"/api/seguimiento/cortes/{corte_id}").status_code == 204
    assert all(c["id"] != corte_id for c in _cortes(cliente).values())
    assert cliente.delete(f"/api/seguimiento/cortes/{corte_id}").status_code == 404


def _excel_saldos() -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Registro cts. bancarias"
    ws.append(["Fecha", "Dólar", "Hapi ($)", "Pichincha ($)", "BCP (S/)", "Efectivo (S/)",
               "Credito (S/)", "Total", "Dif. Total", "Suma Beneficios"])
    # El Total de enero deja fuera Pichincha ($), como hacia el Excel real
    ws.append([datetime(2034, 1, 15), 3.5, 100, 10, 1000, None, 200, 1150, None, 900])
    ws.append([datetime(2034, 2, 15), 3.6, 100, 10, 1200, 50, 0, 1646, 496, 950])
    ws.append([datetime(2034, 1, 31), 3.55, 100, 10, 1100, 20, 100, 1410.5, None, 920])   # fuera de orden
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_importar_el_historial_de_saldos_sin_duplicar(cliente):
    archivo = {"archivo": ("saldos.xlsx", _excel_saldos(), "application/octet-stream")}
    r = cliente.post("/api/seguimiento/importar", files=archivo)
    assert r.status_code == 201, r.text
    resultado = r.json()
    assert resultado["hoja"] == "Registro cts. bancarias"
    assert resultado["creados"] == 3 and resultado["ya_existian"] == 0
    assert any("va despues" in a for a in resultado["avisos"])
    assert any("1 corte(s) el Total del Excel no coincide" in a for a in resultado["avisos"])

    cortes = _cortes(cliente)
    enero = cortes["2034-01-15"]
    assert enero["origen"] == "excel"
    assert enero["total"] == 1185                       # 110 $ x 3.5 + 1000 - 200
    # Efectivo estaba vacio: esa cuenta no existia en esa fecha
    assert {s["cuenta"] for s in enero["saldos"]} == {"Hapi", "Pichincha", "BCP", "Tarjeta de crédito"}
    assert next(s for s in enero["saldos"] if s["cuenta"] == "Tarjeta de crédito")["es_deuda"] is True

    otra_vez = cliente.post("/api/seguimiento/importar", files=archivo).json()
    assert otra_vez["creados"] == 0 and otra_vez["ya_existian"] == 3


def test_un_excel_sin_columnas_de_cuentas_se_rechaza_diciendo_por_que(cliente):
    from openpyxl import Workbook

    wb = Workbook()
    wb.active.append(["Fecha", "Importe"])
    buf = io.BytesIO()
    wb.save(buf)
    r = cliente.post("/api/seguimiento/importar",
                     files={"archivo": ("otro.xlsx", buf.getvalue(), "application/octet-stream")})
    assert r.status_code == 400 and "BCP (S/)" in r.json()["detail"]
