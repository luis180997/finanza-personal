"""Tus registros y tus correcciones no se pierden: ni por borrados ni por reprocesos.

Corre sobre la base temporal de conftest.py, que tiene los mismos triggers que la
real (los instala init_db).
"""
from __future__ import annotations

from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.plataforma.db import engine
from app.main import app
from app.compartido.tipos import Direction, Source, TxStatus
from app.movimientos.dominio.entidades import Transaction


@pytest.fixture(scope="module")
def cliente():
    with TestClient(app) as c:
        yield c


def _manual(cliente, monto: float, comercio: str) -> dict:
    r = cliente.post("/api/movimientos", json={
        "amount": monto, "direction": "gasto", "merchant": comercio,
        "occurred_at": "2026-09-05T12:00:00",
    })
    assert r.status_code == 201, r.text
    return r.json()


def _correo(gmail_id: str, monto: str, comercio: str, operacion: str, dia: int):
    from app.correo.dominio.correo import RawEmail

    return RawEmail(
        gmail_id=gmail_id,
        sender="notificaciones@notificacionesbcp.com.pe",
        subject="Realizaste un consumo con tu Tarjeta de Debito BCP",
        body=(
            f"Realizaste un consumo de S/ {monto} con tu Tarjeta de Debito BCP en {comercio}.\n"
            "Fecha y hora\n"
            f"{dia:02d} de setiembre de 2026 - 10:00 AM\n"
            "Empresa\n"
            f"{comercio}\n"
            "Numero de operacion\n"
            f"{operacion}"
        ),
        received_at=datetime(2026, 9, dia, 18, 0),
    )


def _ingerir(raw):
    from app.correo.adaptadores import fabrica as correo_fabrica
    from app.correo.aplicacion.sincronizacion import ResultadoSync

    with Session(engine) as s:
        r = ResultadoSync()
        correo_fabrica.sincronizador(s).ingerir(raw, r)
        return r


def _movs(operacion: str) -> list[Transaction]:
    with Session(engine) as s:
        return list(s.exec(select(Transaction).where(Transaction.operation_number == operacion)))


def _id_categoria(cliente, nombre: str) -> int:
    return next(c["id"] for c in cliente.get("/api/categorias").json() if c["name"] == nombre)


def test_un_registro_manual_no_se_puede_borrar_a_escondidas(cliente):
    mov = _manual(cliente, 12.5, "Mercado a mano")
    assert mov["locked_by_user"] is True

    with Session(engine) as s:
        with pytest.raises(IntegrityError, match="protegido"):
            s.execute(text('DELETE FROM "transaction" WHERE id = :id'), {"id": mov["id"]})
        s.rollback()

        # Un borrado masivo como el de un script de limpieza: no borra "lo demas",
        # se aborta entero.
        antes = s.execute(text('SELECT COUNT(*) FROM "transaction"')).scalar_one()
        with pytest.raises(IntegrityError):
            s.execute(text('DELETE FROM "transaction"'))
        s.rollback()
        assert s.execute(text('SELECT COUNT(*) FROM "transaction"')).scalar_one() == antes


def test_borrar_tu_registro_manual_desde_la_app_lo_manda_a_la_papelera(cliente):
    mov = _manual(cliente, 33.3, "Error de tipeo")
    assert cliente.delete(f"/api/movimientos/{mov['id']}").status_code == 204
    buscar = {"buscar": "error de tipeo"}
    assert cliente.get("/api/movimientos", params=buscar).json()["items"] == []

    entrada = next(p for p in cliente.get("/api/papelera").json() if p["tx_id"] == mov["id"])
    assert entrada["monto"] == 33.3 and entrada["origen"] == "manual"

    assert cliente.post(f"/api/papelera/{entrada['id']}/restaurar").status_code == 201
    vuelto = cliente.get("/api/movimientos", params=buscar).json()["items"]
    assert [m["amount"] for m in vuelto] == [33.3]
    assert vuelto[0]["locked_by_user"] is True
    # Restaurar dos veces no lo duplica
    assert cliente.post(f"/api/papelera/{entrada['id']}/restaurar").status_code == 404


def test_descartar_un_movimiento_del_banco_no_lo_resucita_el_siguiente_sincronizado(cliente):
    correo = _correo("proteccion-descartar", "45.00", "FERRETERIA DESCARTE", "700001", 3)
    assert _ingerir(correo).transacciones_creadas == 1
    (tx,) = _movs("700001")

    assert cliente.delete(f"/api/movimientos/{tx.id}").status_code == 204
    (tx,) = _movs("700001")                         # sigue ahi, descartado
    assert tx.status == TxStatus.ignorada and tx.locked_by_user

    # El mismo correo otra vez, y otro aviso distinto del mismo movimiento
    assert _ingerir(correo).transacciones_creadas == 0
    otro_aviso = _correo("proteccion-descartar-2", "45.00", "FERRETERIA DESCARTE", "700001", 3)
    assert _ingerir(otro_aviso).transacciones_creadas == 0
    assert len(_movs("700001")) == 1


def test_tu_correccion_sobrevive_aunque_un_script_borre_el_movimiento_y_se_reprocese(cliente):
    correo = _correo("proteccion-correccion", "80.00", "TIENDA SIN NOMBRE", "700002", 4)
    assert _ingerir(correo).transacciones_creadas == 1
    (tx,) = _movs("700002")
    regalos = _id_categoria(cliente, "Regalos")
    r = cliente.patch(f"/api/movimientos/{tx.id}", json={
        "category_id": regalos, "necessity": "evitable", "notes": "cumple de mama",
    })
    assert r.json()["locked_by_user"] is True

    with Session(engine) as s:
        with pytest.raises(IntegrityError):         # borrado a ciegas: rechazado
            s.execute(text('DELETE FROM "transaction" WHERE id = :id'), {"id": tx.id})
        s.rollback()
        # Un script que se salta la proteccion a proposito
        s.execute(text('UPDATE "transaction" SET locked_by_user = 0 WHERE id = :id'),
                  {"id": tx.id})
        s.execute(text('DELETE FROM "transaction" WHERE id = :id'), {"id": tx.id})
        s.commit()
    assert _movs("700002") == []

    # El correo se reprocesa... y el movimiento vuelve con TU clasificacion
    assert _ingerir(correo).transacciones_creadas == 1
    (vuelto,) = _movs("700002")
    assert vuelto.category_id == regalos
    assert vuelto.necessity.value == "evitable"
    assert vuelto.notes == "cumple de mama"
    assert vuelto.locked_by_user and vuelto.confidence == 1.0


def test_un_movimiento_automatico_borrado_vuelve_clasificado_desde_cero(cliente):
    correo = _correo("proteccion-automatico", "19.90", "PLAZA VEA", "700003", 5)
    assert _ingerir(correo).transacciones_creadas == 1
    (tx,) = _movs("700003")
    assert not tx.locked_by_user

    with Session(engine) as s:                      # sin decisiones tuyas: se puede borrar
        s.execute(text('DELETE FROM "transaction" WHERE id = :id'), {"id": tx.id})
        s.commit()
    papelera = cliente.get("/api/papelera").json()
    assert any(p["tx_id"] == tx.id and not p["editado_por_usuario"] for p in papelera)

    assert _ingerir(correo).transacciones_creadas == 1
    (vuelto,) = _movs("700003")
    assert not vuelto.locked_by_user and vuelto.confidence < 1.0


def test_confirmar_desde_por_revisar_tambien_protege(cliente):
    _ingerir(_correo("proteccion-lote", "7.00", "COMERCIO RARO XYZ", "700004", 6))
    (tx,) = _movs("700004")
    r = cliente.post("/api/movimientos/lote", json={"ids": [tx.id], "status": "confirmada"})
    assert r.json()["afectados"] == 1
    (tx,) = _movs("700004")
    assert tx.locked_by_user


def test_ninguna_regla_ni_reclasificacion_pisa_lo_protegido(cliente):
    from app.clasificacion.adaptadores import fabrica as clasificacion

    regalos = _id_categoria(cliente, "Regalos")
    tx = Transaction(
        occurred_at=datetime(2026, 9, 6, 12), booking_date=date(2026, 9, 6),
        amount_cents=1000, direction=Direction.gasto, merchant="rappi",
        source=Source.gmail, status=TxStatus.confirmada, dedupe_hash="proteccion-regla",
        category_id=regalos, locked_by_user=True, confidence=1.0,
    )
    with Session(engine) as s:
        clasificacion.clasificador(s).aplicar(tx, {})     # sin la proteccion, la regla lo mandaria a Delivery
    assert tx.category_id == regalos
    assert tx.status == TxStatus.confirmada and tx.confidence == 1.0


def test_la_papelera_avisa_si_el_movimiento_ya_volvio_y_no_deja_duplicarlo(cliente):
    correo = _correo("proteccion-papelera-vuelto", "23.00", "LIBRERIA VUELTA", "700005", 7)
    _ingerir(correo)
    (tx,) = _movs("700005")
    with Session(engine) as s:
        s.execute(text('DELETE FROM "transaction" WHERE id = :id'), {"id": tx.id})
        s.commit()

    entrada = next(p for p in cliente.get("/api/papelera").json() if p["tx_id"] == tx.id)
    assert entrada["tx_actual_id"] is None
    assert entrada["borrado_en"].endswith("+00:00")     # con zona: no sale corrido 5 horas

    _ingerir(correo)                                     # vuelve al reprocesar su correo
    (vuelto,) = _movs("700005")
    entrada = next(p for p in cliente.get("/api/papelera").json() if p["id"] == entrada["id"])
    assert entrada["tx_actual_id"] == vuelto.id
    assert cliente.post(f"/api/papelera/{entrada['id']}/restaurar").status_code == 409


def test_volver_a_contar_un_descartado(cliente):
    _ingerir(_correo("proteccion-volver", "9.50", "KIOSKO VOLVER", "700006", 8))
    (tx,) = _movs("700006")
    assert cliente.delete(f"/api/movimientos/{tx.id}").status_code == 204

    buscar = {"buscar": "kiosko volver"}
    ignorados = cliente.get("/api/movimientos", params={**buscar, "estado": "ignorada"}).json()
    assert [m["id"] for m in ignorados["items"]] == [tx.id]
    assert cliente.get("/api/movimientos", params=buscar).json()["items"] == []

    cliente.patch(f"/api/movimientos/{tx.id}", json={"status": "confirmada"})
    activos = cliente.get("/api/movimientos", params=buscar).json()["items"]
    assert [m["id"] for m in activos] == [tx.id]
    assert activos[0]["locked_by_user"] is True


def test_un_insert_or_replace_tampoco_pisa_un_registro_protegido(cliente):
    """Un REPLACE borra la fila por dentro. Sin PRAGMA recursive_triggers no saltaba
    ningun trigger: el registro se sobrescribia sin dejar copia en la papelera."""
    mov = _manual(cliente, 14.0, "Pisado a escondidas")
    with Session(engine) as s:
        with pytest.raises(IntegrityError, match="protegido"):
            s.execute(text(
                'INSERT OR REPLACE INTO "transaction" (id, occurred_at, booking_date, '
                "amount_cents, currency, direction, source, status, confidence, dedupe_hash, "
                "tags, is_recurring, locked_by_user, created_at, updated_at) VALUES (:id, "
                "'2026-09-05 12:00:00', '2026-09-05', 1, 'PEN', 'gasto', 'manual', "
                "'confirmada', 1, 'pisado', '[]', 0, 0, '2026-09-05 12:00:00', "
                "'2026-09-05 12:00:00')"
            ), {"id": mov["id"]})
        s.rollback()
    (vivo,) = cliente.get("/api/movimientos", params={"buscar": "pisado a escondidas"}).json()["items"]
    assert vivo["amount"] == 14.0


def test_borrar_una_categoria_no_deja_sin_categoria_a_tus_registros(cliente):
    cat = cliente.post("/api/categorias", json={"name": "Con registros tuyos"}).json()["id"]
    destino = cliente.post("/api/categorias", json={"name": "Destino de registros"}).json()["id"]
    r = cliente.post("/api/movimientos", json={
        "amount": 8, "direction": "gasto", "merchant": "registro con categoria",
        "category_id": cat, "occurred_at": "2026-09-05T12:00:00",
    })
    assert r.status_code == 201, r.text

    r = cliente.delete(f"/api/categorias/{cat}")
    assert r.status_code == 409 and "registraste o corregiste" in r.json()["detail"]
    assert cliente.delete(f"/api/categorias/{cat}", params={"mover_a": destino}).status_code == 204
    (vivo,) = cliente.get("/api/movimientos", params={"buscar": "registro con categoria"}).json()["items"]
    assert vivo["category_id"] == destino and vivo["locked_by_user"] is True


def test_deshacer_una_importacion_pregunta_antes_de_borrar_tus_correcciones(cliente):
    """Y no revienta si otro movimiento apuntaba a una de sus filas como duplicado."""
    import io

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Ingresos y gastos"
    ws.append(["Fecha", "Ingresos", "Alimentos", "Observaciones"])
    for dia in range(1, 13):         # 12 filas: un borrado que el aviso de copias notaria
        ws.append([date(2025, 3, dia), 0, 20 + dia + 0.5, None])
    buf = io.BytesIO()
    wb.save(buf)
    archivo = {"archivo": ("proteccion.xlsx", buf.getvalue(), "application/octet-stream")}
    lote = cliente.post("/api/importar/excel", files=archivo).json()
    assert lote["created_count"] == 12

    marzo = {"desde": "2025-03-01", "hasta": "2025-03-31", "origen": "excel"}
    corregida, otra = cliente.get("/api/movimientos", params=marzo).json()["items"][:2]
    cliente.patch(f"/api/movimientos/{corregida['id']}", json={"notes": "la corregi yo"})
    apunta = cliente.post("/api/movimientos", json={
        "amount": 32.5, "direction": "gasto", "merchant": "apunta al excel",
        "occurred_at": "2025-03-04T13:00:00",
    }).json()
    with Session(engine) as s:
        tx = s.get(Transaction, apunta["id"])
        tx.duplicate_of_id = otra["id"]
        s.add(tx)
        s.commit()

    r = cliente.delete(f"/api/importar/lotes/{lote['id']}")
    assert r.status_code == 409 and "corregiste" in r.json()["detail"]
    assert len(cliente.get("/api/movimientos", params=marzo).json()["items"]) == 12

    r = cliente.delete(f"/api/importar/lotes/{lote['id']}", params={"incluir_protegidos": True})
    assert r.status_code == 200, r.text
    assert r.json()["borrados"] == 12
    with Session(engine) as s:
        assert s.get(Transaction, apunta["id"]).duplicate_of_id is None
    # Deshacer fue una orden tuya: el aviso de copias no lo toma por una perdida
    assert cliente.get("/api/respaldos").json()["perdida_sin_aceptar"] is False


def test_un_cobro_en_dolares_espera_a_que_escribas_los_soles(cliente):
    """El BCP avisa "$ 8.85" y debita soles, pero el correo no dice cuantos."""
    from app.correo.dominio.correo import RawEmail

    correo = RawEmail(
        gmail_id="dolares-netflix",
        sender="notificaciones@notificacionesbcp.com.pe",
        subject="Realizaste un consumo con tu Tarjeta de Debito BCP",
        body=(
            "Realizaste un consumo de $ 8.85 con tu Tarjeta de Debito BCP en NETFLIX.COM.\n"
            "Fecha y hora\n12 de setiembre de 2026 - 03:30 AM\nEmpresa\nNETFLIX.COM\n"
            "Numero de operacion\n700099"
        ),
        received_at=datetime(2026, 9, 12, 3, 30),
    )
    assert _ingerir(correo).transacciones_creadas == 1
    (tx,) = _movs("700099")
    assert tx.currency == "USD" and tx.status == TxStatus.por_revisar

    ficha = next(m for m in cliente.get("/api/movimientos/revision").json() if m["id"] == tx.id)
    assert ficha["motivos"][0]["clave"] == "moneda_extranjera"

    r = cliente.patch(f"/api/movimientos/{tx.id}", json={"amount": 31.2, "currency": "pen"})
    assert r.status_code == 200, r.text
    corregido = r.json()
    assert corregido["currency"] == "PEN" and corregido["amount"] == 31.2
    assert corregido["locked_by_user"] is True
    assert all(m["clave"] != "moneda_extranjera" for m in corregido["motivos"])
    assert cliente.patch(f"/api/movimientos/{tx.id}", json={"currency": None}).status_code == 422


def test_un_correo_que_no_genera_movimiento_no_se_reprocesa_en_cada_sincronizacion(cliente):
    from app.correo.dominio.entidades import EmailMessage

    original = _correo("reproceso-a", "31.00", "BODEGA REPROCESO", "700007", 9)
    segundo_aviso = _correo("reproceso-b", "31.00", "BODEGA REPROCESO", "700007", 9)
    assert _ingerir(original).transacciones_creadas == 1
    assert _ingerir(segundo_aviso).duplicados == 1      # el mismo movimiento, otro correo
    assert _ingerir(segundo_aviso).duplicados == 0      # ya decidido: no se cuenta otra vez
    assert len(_movs("700007")) == 1
    with Session(engine) as s:
        correo = s.exec(select(EmailMessage).where(EmailMessage.gmail_id == "reproceso-b")).one()
        assert "mismo" in correo.error
