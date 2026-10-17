"""Interruptores, respaldos por API, fechas imposibles y ciclos de categorias."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.plataforma.config import PROJECT_DIR
from app.main import app


@pytest.fixture(scope="module")
def cliente():
    with TestClient(app) as c:
        yield c


def test_la_comparativa_excel_ya_no_existe(cliente):
    assert cliente.get("/api/comparativa").status_code == 404


def test_no_se_lee_el_correo_dos_veces_a_la_vez(cliente, monkeypatch):
    """Pulsar "Sincronizar" mientras corria la automatica leia los mismos correos a
    la vez. Ahora el segundo espera su turno: la interfaz avisa, la tarea se salta."""
    from app.correo.adaptadores import fabrica as correo
    from app.plataforma import programador

    def no_deberia_leer(*_):
        raise AssertionError("se leyo el correo con otra lectura en curso")

    with correo.en_exclusiva() as libre:
        assert libre
        for ruta in ("/api/gmail/sincronizar", "/api/gmail/reparsear"):
            r = cliente.post(ruta)
            assert r.status_code == 409 and "en curso" in r.json()["detail"], ruta
        monkeypatch.setattr(correo, "sincronizador", no_deberia_leer)
        programador._sincronizar_correo()          # la automatica se salta su turno
        monkeypatch.undo()

    # Terminada la otra, se puede volver a leer
    assert cliente.post("/api/gmail/reparsear").status_code == 200


def test_la_importacion_del_excel_ya_no_existe(cliente):
    """Retirada el 17/10/2026: el Excel ya estaba entero dentro (hasta el 31/08/2026)."""
    assert cliente.get("/api/importar/lotes").status_code == 404
    assert cliente.post("/api/importar/excel/analizar").status_code == 404
    assert cliente.get("/api/config").status_code == 404


def test_un_ano_imposible_se_rechaza_diciendo_por_que(cliente):
    # Lo que emite el navegador mientras se teclea "2022" en el campo de fecha
    r = cliente.get("/api/resumen", params={"desde": "0002-09-01", "hasta": "2026-09-30"})
    assert r.status_code == 400
    assert "2000" in r.json()["detail"]
    r = cliente.get("/api/resumen/periodos", params={"desde": "0202-01-01"})
    assert r.status_code == 400


def test_una_categoria_no_puede_colgar_de_si_misma_ni_de_su_hija(cliente):
    padre = cliente.post("/api/categorias", json={"name": "Ciclo padre"}).json()["id"]
    hija = cliente.post(
        "/api/categorias", json={"name": "Ciclo hija", "parent_id": padre},
    ).json()["id"]

    r = cliente.patch(f"/api/categorias/{padre}", json={"name": "Ciclo padre", "parent_id": hija})
    assert r.status_code == 400
    r = cliente.patch(f"/api/categorias/{padre}", json={"name": "Ciclo padre", "parent_id": padre})
    assert r.status_code == 400
    # Un cambio legitimo sigue funcionando
    r = cliente.patch(f"/api/categorias/{hija}", json={"name": "Ciclo hija renombrada",
                                                        "parent_id": padre})
    assert r.status_code == 200
    assert cliente.get("/api/resumen").status_code == 200


def test_respaldo_manual_por_api_en_la_carpeta_temporal(cliente):
    r = cliente.post("/api/respaldos")
    assert r.status_code == 201, r.text
    estado = cliente.get("/api/respaldos").json()
    assert estado["ultimo"]["archivo"] == r.json()["archivo"]
    assert estado["activo"] is False            # RESPALDO_CADA_DIAS=0 en conftest
    # Nunca la carpeta de respaldos reales
    assert Path(estado["carpeta"]).resolve() != (PROJECT_DIR / "data" / "respaldos").resolve()


@pytest.mark.parametrize("comercio, esperada", [
    ("tambo", "Snacks"),
    ("oxxo", "Snacks"),
    ("starbucks", "Cafe"),
])
def test_tiendas_y_cafeterias_se_clasifican_solas(cliente, comercio, esperada):
    from datetime import date, datetime

    from sqlmodel import Session

    from app.plataforma.db import engine
    from app.clasificacion.dominio.entidades import Category
    from app.compartido.tipos import Direction, Source, TxStatus
    from app.movimientos.dominio.entidades import Transaction
    from app.clasificacion.adaptadores import fabrica as clasificacion

    with Session(engine) as s:
        tx = Transaction(
            occurred_at=datetime(2026, 8, 18, 12), booking_date=date(2026, 8, 18),
            amount_cents=899, direction=Direction.gasto, merchant=comercio,
            source=Source.gmail, status=TxStatus.confirmada, dedupe_hash=f"clasif-{comercio}",
        )
        resultado = clasificacion.clasificador(s).clasificar(tx)
        assert s.get(Category, resultado.category_id).name == esperada
