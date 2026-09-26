"""Peticiones que devolvian un 500, datos que se ignoraban en silencio y el corte
del 31/08/2026. Todo sobre la base temporal de conftest.py."""
from __future__ import annotations

import io
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.plataforma.db import engine
from app.main import app
from app.compartido.tipos import Direction, Source, TxStatus
from app.movimientos.dominio.entidades import Transaction
from app.analitica.dominio.periodos import Rango
from app.compartido import reloj


@pytest.fixture(scope="module")
def cliente():
    with TestClient(app) as c:
        yield c


def _manual(cliente, **extra) -> dict:
    datos = {"amount": 10, "direction": "gasto", "merchant": "validaciones",
             "occurred_at": "2026-09-10T12:00:00", **extra}
    r = cliente.post("/api/movimientos", json=datos)
    assert r.status_code == 201, r.text
    return r.json()


def test_un_null_en_un_campo_obligatorio_se_rechaza_en_vez_de_dar_500(cliente):
    mov = _manual(cliente)
    for campo in ("occurred_at", "direction", "status", "amount", "is_recurring"):
        r = cliente.patch(f"/api/movimientos/{mov['id']}", json={campo: None})
        assert r.status_code == 422, (campo, r.text)
    # Los que si admiten vacio se vacian bien
    r = cliente.patch(f"/api/movimientos/{mov['id']}", json={"tags": None, "notes": "   "})
    assert r.status_code == 200, r.text
    assert r.json()["tags"] == [] and r.json()["notes"] is None


def test_una_categoria_o_cuenta_que_no_existe_da_404(cliente):
    assert cliente.post("/api/movimientos", json={"amount": 5, "category_id": 999999}).status_code == 404
    assert cliente.post("/api/movimientos", json={"amount": 5, "account_id": 999999}).status_code == 404
    mov = _manual(cliente)
    assert cliente.patch(f"/api/movimientos/{mov['id']}", json={"category_id": 999999}).status_code == 404
    r = cliente.post("/api/movimientos/lote", json={"ids": [mov["id"]], "category_id": 999999})
    assert r.status_code == 404


def test_el_resumen_con_una_sola_fecha_avisa_en_vez_de_ignorarla(cliente):
    assert cliente.get("/api/resumen", params={"desde": "2026-09-01"}).status_code == 400
    assert cliente.get("/api/resumen", params={"hasta": "2026-09-30"}).status_code == 400
    r = cliente.get("/api/resumen", params={"desde": "2026-09-01", "hasta": "2026-09-30"})
    assert r.status_code == 200


def test_editar_una_cuenta_cambia_solo_lo_que_mandas(cliente):
    cuentas = cliente.get("/api/cuentas").json()
    efectivo = next(c for c in cuentas if c["name"] == "Efectivo")
    otra = next(c for c in cuentas if c["name"] != "Efectivo")

    r = cliente.patch(f"/api/cuentas/{efectivo['id']}", json={"last4": "1234"})
    assert r.status_code == 200, r.text
    assert r.json()["last4"] == "1234" and r.json()["type"] == "efectivo"
    assert cliente.patch(f"/api/cuentas/{efectivo['id']}", json={"name": otra["name"]}).status_code == 409
    assert cliente.patch(f"/api/cuentas/{efectivo['id']}", json={"type": None}).status_code == 422
    cliente.patch(f"/api/cuentas/{efectivo['id']}", json={"last4": None})


def test_una_categoria_repetida_o_con_padre_inexistente_da_un_error_claro(cliente):
    assert cliente.post("/api/categorias", json={"name": "Validacion repetida"}).status_code == 201
    assert cliente.post("/api/categorias", json={"name": "Validacion repetida"}).status_code == 409
    r = cliente.post("/api/categorias", json={"name": "Huerfana", "parent_id": 999999})
    assert r.status_code == 404


def test_un_movimiento_del_correo_no_puede_moverse_antes_del_corte(cliente):
    with Session(engine) as s:
        tx = Transaction(
            occurred_at=datetime(2026, 9, 2, 12), booking_date=date(2026, 9, 2),
            amount_cents=777, direction=Direction.gasto, source=Source.gmail,
            status=TxStatus.confirmada, dedupe_hash="validaciones-corte",
        )
        s.add(tx)
        s.commit()
        tx_id = tx.id
    r = cliente.patch(f"/api/movimientos/{tx_id}", json={"occurred_at": "2026-07-20T12:00:00"})
    assert r.status_code == 400
    assert "01/09/2026" in r.json()["detail"]


@pytest.mark.parametrize("desde, hasta, esperado", [
    (date(2026, 9, 1), date(2026, 9, 30), (date(2026, 8, 1), date(2026, 8, 31))),
    (date(2026, 10, 1), date(2026, 10, 31), (date(2026, 9, 1), date(2026, 9, 30))),
    (date(2026, 3, 1), date(2026, 3, 31), (date(2026, 2, 1), date(2026, 2, 28))),
    (date(2026, 1, 1), date(2026, 1, 31), (date(2025, 12, 1), date(2025, 12, 31))),
    (date(2026, 7, 1), date(2026, 9, 30), (date(2026, 4, 1), date(2026, 6, 30))),
    # Un rango que no son meses completos sigue restando dias
    (date(2026, 9, 5), date(2026, 9, 14), (date(2026, 8, 26), date(2026, 9, 4))),
])
def test_el_periodo_anterior_de_un_mes_es_el_mes_anterior_entero(desde, hasta, esperado):
    anterior = Rango(desde, hasta).anterior()
    assert (anterior.desde, anterior.hasta) == esperado


def _excel(filas: list[list]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Ingresos y gastos"
    ws.append(["Fecha", "Ingresos", "Alimentos", "Observaciones"])
    for fila in filas:
        ws.append(fila)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_el_importador_nunca_trae_filas_despues_del_corte(cliente):
    contenido = _excel([
        [date(2026, 8, 31), 0, 12.34, None],
        [date(2026, 9, 1), 0, 56.78, None],
        [date(2026, 10, 3), 0, 90.12, None],
    ])
    archivo = {"archivo": ("corte.xlsx", contenido, "application/octet-stream")}

    analisis = cliente.post("/api/importar/excel/analizar", files=archivo).json()
    assert analisis["movimientos"] == 1 and analisis["hasta"] == "2026-08-31"
    assert any("31/08/2026" in a for a in analisis["avisos"])

    # Ni aunque se pida expresamente una fecha posterior
    r = cliente.post("/api/importar/excel", files=archivo, data={"fecha_hasta": "2026-12-31"})
    assert r.status_code == 201, r.text
    lote = r.json()
    assert lote["created_count"] == 1
    assert cliente.delete(f"/api/importar/lotes/{lote['id']}").json()["borrados"] == 1


def test_el_importador_puede_traer_solo_un_mes(cliente):
    """Para anadir agosto sin volver a leer lo ya importado: si una fila vieja se
    hubiera retocado en el Excel, su huella cambiaria y entraria duplicada."""
    contenido = _excel([
        [date(2026, 7, 31), 0, 11.11, None],
        [date(2026, 8, 1), 0, 22.22, None],
        [date(2026, 8, 31), 0, 33.33, None],
    ])
    archivo = {"archivo": ("agosto.xlsx", contenido, "application/octet-stream")}
    desde = {"fecha_desde": "2026-08-01"}

    analisis = cliente.post("/api/importar/excel/analizar", files=archivo, data=desde).json()
    assert analisis["movimientos"] == 2
    assert (analisis["desde"], analisis["hasta"]) == ("2026-08-01", "2026-08-31")
    assert any("anteriores al 01/08/2026" in a for a in analisis["avisos"])

    r = cliente.post("/api/importar/excel", files=archivo, data=desde)
    assert r.status_code == 201, r.text
    lote = r.json()
    assert lote["created_count"] == 2
    assert (lote["desde"], lote["hasta"]) == ("2026-08-01", "2026-08-31")
    assert cliente.delete(f"/api/importar/lotes/{lote['id']}").json()["borrados"] == 2


def test_un_importe_con_formato_europeo_en_texto_no_se_lee_mal():
    from app.excel.dominio.mapeo import numero as _num

    assert _num("1.234,56") == 1234.56
    assert _num("1,234.56") == 1234.56
    assert _num("S/ 39.63") == 39.63
    assert _num(15) == 15.0
    assert _num("") == 0.0


def test_a_mitad_de_mes_se_compara_con_los_mismos_dias_del_mes_anterior(cliente, monkeypatch):
    """El 13/09 el Panel decia -82 % (13 dias contra agosto entero) y era +67 %."""
    for fecha, monto in (("2030-10-05", 100), ("2030-10-25", 900), ("2030-11-03", 200)):
        _manual(cliente, amount=monto, merchant="comparacion a la fecha",
                occurred_at=f"{fecha}T12:00:00")
    monkeypatch.setattr(reloj, "hoy", lambda: date(2030, 11, 10))

    k = cliente.get("/api/resumen", params={"desde": "2030-11-01", "hasta": "2030-11-30"}).json()["kpis"]
    assert k["gastos"] == 200
    assert k["gastos_periodo_anterior"] == 1000      # octubre entero, para el grafico
    assert k["gastos_anterior_comparable"] == 100    # octubre del 1 al 10
    assert k["variacion_gastos"] == 100.0 and k["comparacion_parcial"] is True

    # Un mes ya cerrado se sigue comparando con el anterior entero
    k = cliente.get("/api/resumen", params={"desde": "2030-10-01", "hasta": "2030-10-31"}).json()["kpis"]
    assert k["comparacion_parcial"] is False
    assert k["gastos_anterior_comparable"] == k["gastos_periodo_anterior"]


def test_una_fecha_imposible_se_rechaza_al_registrar_o_editar(cliente):
    for fecha in ("0001-01-01T00:00:00", "9999-12-31T23:59:59", "1999-12-31T12:00:00"):
        r = cliente.post("/api/movimientos", json={"amount": 5, "occurred_at": fecha})
        assert r.status_code == 422, (fecha, r.text)
    mov = _manual(cliente)
    r = cliente.patch(f"/api/movimientos/{mov['id']}", json={"occurred_at": "0202-09-10T12:00:00"})
    assert r.status_code == 422


def test_un_movimiento_con_fecha_imposible_no_estira_el_historial(cliente):
    """Si se cuela por fuera de la API (un script), Tendencia no pide 24.000 meses."""
    with Session(engine) as s:
        raro = Transaction(
            occurred_at=datetime(1, 1, 1, 12), booking_date=date(1, 1, 1), amount_cents=100,
            direction=Direction.gasto, source=Source.manual, status=TxStatus.confirmada,
            dedupe_hash="fecha-imposible",
        )
        s.add(raro)
        s.commit()
        raro_id = raro.id
    try:
        serie = cliente.get("/api/resumen/periodos", params={"agrupar": "mes"}).json()
        assert serie["rango"]["desde"] >= "2000-01-01"
        assert len(serie["periodos"]) <= (2100 - 2000 + 1) * 12
    finally:
        with Session(engine) as s:
            s.delete(s.get(Transaction, raro_id))
            s.commit()


def test_el_importador_ignora_filas_con_fechas_imposibles():
    from app.excel.dominio.mapeo import fecha_de as _fecha

    assert _fecha(date(1900, 1, 1)) is None
    assert _fecha("15/03/2025") == date(2025, 3, 15)


def test_los_meses_salen_en_castellano(cliente):
    serie = cliente.get("/api/resumen/periodos", params={
        "agrupar": "mes", "desde": "2026-01-01", "hasta": "2026-12-31",
    }).json()
    etiquetas = [p["etiqueta"] for p in serie["periodos"]]
    assert etiquetas[:3] == ["Ene 26", "Feb 26", "Mar 26"]
    assert etiquetas[8] == "Set 26" and etiquetas[11] == "Dic 26"
