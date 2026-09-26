"""Series por categoria de Tendencia (y del Panel): agrupadas por id, no por nombre."""
from __future__ import annotations

from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.main import app

SERIES = "/api/resumen/periodos"


@pytest.fixture(scope="module")
def cliente():
    with TestClient(app) as c:
        yield c


def _categoria(cliente, nombre: str, padre: int | None = None) -> int:
    r = cliente.post("/api/categorias", json={"name": nombre, "parent_id": padre,
                                               "color": "#2a78d6"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _id_categoria(cliente, nombre: str) -> int:
    return next(c["id"] for c in cliente.get("/api/categorias").json() if c["name"] == nombre)


def _gasto(cliente, fecha_iso: str, categoria: int, monto: float, comercio="prueba series"):
    r = cliente.post("/api/movimientos", json={
        "occurred_at": f"{fecha_iso}T10:00:00", "amount": monto, "direction": "gasto",
        "category_id": categoria, "merchant": comercio,
    })
    assert r.status_code in (200, 201), r.text


def test_la_pila_suma_las_hijas_y_nunca_pasa_de_ocho_series(cliente):
    # Categorias propias: el test no depende de cuantas trae la semilla.
    raices = [_categoria(cliente, f"Pila {i}") for i in range(9)]
    hija = _categoria(cliente, "Pila hija", raices[0])
    # 2024 no lo toca ningun otro test
    _gasto(cliente, "2024-06-05", hija, 500)
    _gasto(cliente, "2024-07-05", hija, 100)
    for i, cat in enumerate(raices[1:]):            # 90, 80, ..., 20
        _gasto(cliente, "2024-07-10", cat, 90 - i * 10)

    serie = cliente.get(SERIES, params={
        "agrupar": "mes", "desde": "2024-06-01", "hasta": "2024-07-31",
    }).json()

    cats = serie["categorias"]
    assert cats[0]["id"] == raices[0] and cats[0]["monto"] == 600   # la hija suma en su raiz
    assert len(cats) == 8 and cats[-1]["clave"] == "otras"
    assert cats[-1]["monto"] == 30 + 20
    junio, julio = serie["periodos"]
    assert junio["por_categoria"] == {str(raices[0]): 500}
    assert julio["por_categoria"]["otras"] == 50
    assert sum(julio["por_categoria"].values()) == julio["gasto"]   # cada barra cuadra
    assert serie["categoria_id"] is None


def test_una_categoria_llamada_sin_clasificar_no_se_mezcla_con_los_gastos_sin_categoria(cliente):
    from app.plataforma.db import engine
    from app.compartido.tipos import Direction, Source, TxStatus
    from app.movimientos.dominio.entidades import Transaction

    sin_clasificar = _id_categoria(cliente, "Sin clasificar")
    _gasto(cliente, "2023-05-03", sin_clasificar, 30)
    with Session(engine) as s:                      # un gasto que no tiene categoria
        s.add(Transaction(
            occurred_at=datetime(2023, 5, 4, 12), booking_date=date(2023, 5, 4),
            amount_cents=1200, direction=Direction.gasto, category_id=None,
            source=Source.excel, status=TxStatus.confirmada, dedupe_hash="test-sin-categoria",
        ))
        s.commit()

    rango = {"desde": "2023-05-01", "hasta": "2023-05-31"}
    series = {c["clave"]: c for c in cliente.get(SERIES, params=rango).json()["categorias"]}
    assert series[str(sin_clasificar)]["monto"] == 30
    assert series["sin"]["monto"] == 12 and series["sin"]["nombre"] == "Sin categoria"

    # El filtro por la categoria real cuenta solo lo suyo, y cuadra con su serie
    solo = cliente.get(SERIES, params={**rango, "categoria": sin_clasificar}).json()
    assert solo["totales"]["gasto"] == 30

    # En el Panel, lo mismo
    panel = cliente.get("/api/resumen", params=rango).json()["por_categoria"]
    assert {(c["id"], c["clave"], c["monto"]) for c in panel} == {
        (sin_clasificar, str(sin_clasificar), 30), (None, "sin", 12),
    }


def test_una_subcategoria_llamada_otras_no_pisa_el_grupo_otras(cliente):
    raiz = _categoria(cliente, "Con una Otras")
    otras_real = _categoria(cliente, "Otras", raiz)
    hijas = [_categoria(cliente, f"Hija {i}", raiz) for i in range(8)]
    _gasto(cliente, "2022-03-01", otras_real, 100)
    for i, h in enumerate(hijas):                   # 90, 80, ..., 20
        _gasto(cliente, "2022-03-02", h, 90 - i * 10)

    serie = cliente.get(SERIES, params={
        "desde": "2022-03-01", "hasta": "2022-03-31", "categoria": raiz,
    }).json()

    cats = serie["categorias"]
    assert len({c["clave"] for c in cats}) == len(cats)          # sin claves repetidas
    assert next(c for c in cats if c["id"] == otras_real)["monto"] == 100
    assert next(c for c in cats if c["clave"] == "otras")["monto"] == 30 + 20
    marzo = serie["periodos"][0]
    assert marzo["por_categoria"][str(otras_real)] == 100
    assert marzo["por_categoria"]["otras"] == 50


def test_filtrar_por_categoria_desglosa_sus_subcategorias(cliente):
    # 2023 (marzo y abril) no lo toca ningun otro test.
    alimentacion = _id_categoria(cliente, "Alimentacion")
    delivery = _id_categoria(cliente, "Delivery")
    almuerzo = _id_categoria(cliente, "Almuerzo")
    for fecha_iso, cat, monto in [
        ("2023-03-02", delivery, 40), ("2023-03-09", delivery, 10),
        ("2023-03-15", almuerzo, 15), ("2023-03-20", alimentacion, 5),
        ("2023-04-01", _id_categoria(cliente, "Vivienda"), 900),
    ]:
        _gasto(cliente, fecha_iso, cat, monto, comercio="prueba filtro")

    params = {"agrupar": "mes", "desde": "2023-03-01", "hasta": "2023-04-30"}
    serie = cliente.get(SERIES, params={**params, "categoria": alimentacion}).json()

    assert serie["categoria_id"] == alimentacion       # la interfaz titula con esto
    marzo, abril = serie["periodos"]
    assert marzo["gasto"] == 70
    assert abril["gasto"] == 0                          # Vivienda no es de la rama
    assert marzo["por_categoria"] == {str(delivery): 50, str(almuerzo): 15, str(alimentacion): 5}
    assert [c["nombre"] for c in serie["categorias"]] == [
        "Delivery", "Almuerzo", "Alimentacion (sin subcategoria)",
    ]
    assert serie["totales"]["movimientos"] == 4

    # Una subcategoria elegida sola lleva su nombre tal cual
    solo_delivery = cliente.get(SERIES, params={**params, "categoria": delivery}).json()
    assert [c["nombre"] for c in solo_delivery["categorias"]] == ["Delivery"]
    assert solo_delivery["periodos"][0]["gasto"] == 50

    # Opciones del filtro: solo lo que tiene gasto en el rango, de mayor a menor
    sin_filtro = cliente.get(SERIES, params=params).json()
    arbol = sin_filtro["arbol_categorias"]
    assert [n["nombre"] for n in arbol] == ["Vivienda", "Alimentacion"]
    assert arbol[0]["subcategorias"] == []
    assert arbol[1]["monto"] == 70
    assert [s["nombre"] for s in arbol[1]["subcategorias"]] == ["Delivery", "Almuerzo"]

    assert cliente.get(SERIES, params={**params, "categoria": 999999}).status_code == 404
