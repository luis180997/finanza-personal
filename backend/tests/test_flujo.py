"""Pruebas de flujo completo sobre una base de datos temporal.

DATOS INVENTADOS: los nombres, cuentas, importes y correos de este archivo son
ficticios a proposito (ver AGENTS.md, seccion "Pruebas con datos inventados").
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

# La base temporal la fija conftest.py antes de importar nada de la app. Aqui se
# volvia a cambiar DATABASE_URL con la configuracion ya cargada: no tenia ningun
# efecto y hacia creer que este archivo usaba otra base.
from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import select  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def cliente():
    with TestClient(app) as c:
        yield c


def _id_categoria(cliente, nombre: str) -> int:
    for c in cliente.get("/api/categorias").json():
        if c["name"] == nombre:
            return c["id"]
    raise AssertionError(f"no existe la categoria {nombre}")


def _id_cuenta(cliente, nombre: str) -> int:
    for c in cliente.get("/api/cuentas").json():
        if c["name"] == nombre:
            return c["id"]
    raise AssertionError(f"no existe la cuenta {nombre}")


def _marcar_duplicado(tx_id: int, original_id: int) -> None:
    """Apunta un movimiento a otro como duplicado, saltandose la API.

    `duplicate_of_id` no esta en TransactionPatch, y no lo esta a proposito: lo
    escribe el pipeline cuando detecta una sospecha cruzada. Mandarlo por PATCH
    no da error, simplemente se ignora, asi que un test que lo hiciera pasaria
    sin comprobar nada.
    """
    from sqlmodel import Session

    from app.plataforma.db import engine
    from app.movimientos.dominio.entidades import Transaction

    with Session(engine) as s:
        tx = s.get(Transaction, tx_id)
        tx.duplicate_of_id = original_id
        s.add(tx)
        s.commit()


def test_semilla_crea_catalogo(cliente):
    # Yape ya no es cuenta: es medio de pago sobre BCP Debito
    cuentas = [c["name"] for c in cliente.get("/api/cuentas").json()]
    assert len(cuentas) == 5
    assert "Yape" not in cuentas
    assert len(cliente.get("/api/categorias").json()) > 40
    assert len(cliente.get("/api/reglas").json()) >= 9


def test_gasto_en_efectivo_se_registra_y_clasifica(cliente):
    """El caso que hoy anotas a mano en el Excel."""
    r = cliente.post("/api/movimientos", json={
        "amount": 12.5,
        "direction": "gasto",
        "merchant": "Menu del dia",
        "description": "Almuerzo cerca de la oficina",
        "category_id": _id_categoria(cliente, "Almuerzo"),
        "necessity": "esencial",
        "occurred_at": datetime(2026, 9, 2, 13, 0).isoformat(),
    })
    assert r.status_code == 201, r.text
    tx = r.json()
    assert tx["amount"] == 12.5
    assert tx["account_name"] == "Efectivo"      # cuenta por defecto
    assert tx["status"] == "confirmada"
    assert tx["source"] == "manual"


def test_regla_semilla_clasifica_rappi_como_delivery_evitable(cliente):
    r = cliente.post("/api/movimientos", json={
        "amount": 36.9,
        "direction": "gasto",
        "merchant": "RAPPI*RAPPI PERU",
        "account_id": _id_cuenta(cliente, "BCP Credito"),
        "occurred_at": datetime(2026, 9, 3, 20, 30).isoformat(),
    })
    tx = r.json()
    assert tx["category_name"] == "Delivery"
    assert tx["necessity"] == "evitable"


def test_transferencia_no_cuenta_como_gasto(cliente):
    cliente.post("/api/movimientos", json={
        "amount": 500,
        "direction": "transferencia",
        "description": "Pago de tarjeta desde BCP",
        "account_id": _id_cuenta(cliente, "BCP Debito"),
        "counter_account_id": _id_cuenta(cliente, "BCP Credito"),
        "occurred_at": datetime(2026, 9, 3, 9, 0).isoformat(),
    })
    r = cliente.get("/api/resumen", params={"desde": "2026-09-01", "hasta": "2026-09-30"}).json()
    # 12.5 + 36.9 = 49.4  (los 500 de la transferencia NO suman)
    assert r["kpis"]["gastos"] == 49.4


def test_ingreso_y_tasa_de_ahorro(cliente):
    cliente.post("/api/movimientos", json={
        "amount": 3000,
        "direction": "ingreso",
        "description": "Sueldo setiembre",
        "category_id": _id_categoria(cliente, "Sueldo"),
        "account_id": _id_cuenta(cliente, "BCP Debito"),
        "occurred_at": datetime(2026, 9, 1, 10, 0).isoformat(),
    })
    k = cliente.get("/api/resumen", params={"desde": "2026-09-01", "hasta": "2026-09-30"}).json()["kpis"]
    assert k["ingresos"] == 3000
    assert k["neto"] == round(3000 - 49.4, 2)
    assert k["tasa_ahorro"] > 98


def test_resumen_trae_todos_los_cortes(cliente):
    r = cliente.get("/api/resumen", params={"desde": "2026-09-01", "hasta": "2026-09-30"}).json()
    for clave in ("kpis", "serie_diaria", "por_categoria", "por_subcategoria",
                  "por_necesidad", "por_cuenta", "top_comercios", "alertas"):
        assert clave in r, f"falta {clave}"
    assert len(r["serie_diaria"]) == 30
    assert r["por_categoria"][0]["monto"] > 0
    evitable = [x for x in r["por_necesidad"] if x["clave"] == "evitable"]
    assert evitable and evitable[0]["monto"] == 36.9


def test_correccion_manual_alimenta_la_memoria_de_comercio(cliente):
    """Corriges una vez -> el sistema aprende para el mismo comercio."""
    primero = cliente.post("/api/movimientos", json={
        "amount": 22.0, "direction": "gasto", "merchant": "SANGUCHERIA DONA ELVIRA",
        "occurred_at": datetime(2026, 9, 4, 13, 0).isoformat(),
    }).json()
    assert primero["category_name"] in (None, "Sin clasificar")

    restaurante = _id_categoria(cliente, "Restaurante")
    cliente.patch(f"/api/movimientos/{primero['id']}", json={"category_id": restaurante})

    segundo = cliente.post("/api/movimientos", json={
        "amount": 25.0, "direction": "gasto", "merchant": "SANGUCHERIA DONA ELVIRA",
        "occurred_at": datetime(2026, 9, 5, 13, 0).isoformat(),
    }).json()
    assert segundo["category_name"] == "Restaurante"


def test_filtros_y_paginado(cliente):
    r = cliente.get("/api/movimientos", params={
        "desde": "2026-09-01", "hasta": "2026-09-30",
        "direccion": "gasto", "tamano": 2,
    }).json()
    assert r["tamano"] == 2
    assert len(r["items"]) <= 2
    assert r["total"] >= 3
    assert all(i["direction"] == "gasto" for i in r["items"])

    busqueda = cliente.get("/api/movimientos", params={"buscar": "rappi"}).json()
    assert busqueda["total"] == 1


def test_edicion_en_lote(cliente):
    ids = [i["id"] for i in cliente.get("/api/movimientos", params={"tamano": 3}).json()["items"]]
    r = cliente.post("/api/movimientos/lote", json={"ids": ids, "necessity": "discrecional"})
    assert r.json()["afectados"] == len(ids)


def test_laboratorio_de_parsers(cliente):
    r = cliente.post("/api/parsers/probar", json={
        "sender": "notificaciones@notificacionesbcp.com.pe",
        "subject": "Realizaste un consumo con tu Tarjeta de Debito BCP",
        "body": """Realizaste un consumo de S/ 18.60 con tu Tarjeta de Debito BCP en TAMBO.
Fecha y hora
09 de agosto de 2026 - 07:15 PM
Empresa
TAMBO
Numero de operacion
778899""",
    }).json()
    assert r["reconocido"] is True
    assert r["parser"] == "bcp_consumo_debito"
    assert r["resultado"]["monto"] == 18.6
    assert r["resultado"]["comercio_normalizado"] == "tambo"


def test_ingesta_de_correo_es_idempotente():
    """Ingerir dos veces el mismo correo no duplica el movimiento."""
    from sqlmodel import Session

    from app.plataforma.db import engine
    from app.correo.dominio.correo import RawEmail
    from app.correo.adaptadores import fabrica as correo_fabrica
    from app.correo.aplicacion.sincronizacion import ResultadoSync

    correo = RawEmail(
        gmail_id="msg-unico-1",
        sender="notificaciones@notificacionesbcp.com.pe",
        subject="Realizaste un consumo con tu Tarjeta de Debito BCP",
        body="""Realizaste un consumo de S/ 99.90 con tu Tarjeta de Debito BCP en PLAZA VEA.
Fecha y hora
06 de setiembre de 2026 - 10:00 AM
Empresa
PLAZA VEA
Numero de operacion
123456""",
        received_at=datetime(2026, 9, 6, 18, 0),
    )
    with Session(engine) as s:
        r1 = ResultadoSync()
        correo_fabrica.sincronizador(s).ingerir(correo, r1)
        assert r1.transacciones_creadas == 1

        r2 = ResultadoSync()
        correo_fabrica.sincronizador(s).ingerir(correo, r2)
        assert r2.correos_nuevos == 0
        assert r2.transacciones_creadas == 0


def test_duplicado_cruzado_se_marca_para_revision(cliente):
    """El riesgo real de doble conteo: anotas el gasto a mano y luego llega el
    correo del banco por lo mismo. Se avisa, no se borra."""
    from sqlmodel import Session

    from app.plataforma.db import engine
    from app.correo.dominio.correo import RawEmail
    from app.correo.adaptadores import fabrica as correo_fabrica
    from app.correo.aplicacion.sincronizacion import ResultadoSync

    base = datetime(2026, 9, 7, 12, 0)
    cliente.post("/api/movimientos", json={
        "amount": 45.0,
        "direction": "gasto",
        "merchant": "Cevicheria del barrio",
        "occurred_at": base.isoformat(),
    })

    correo = RawEmail(
        gmail_id="msg-bcp-dup",
        sender="notificaciones@notificacionesbcp.com.pe",
        subject="Realizaste un consumo con tu Tarjeta de Debito BCP",
        body="""Realizaste un consumo de S/ 45.00 con tu Tarjeta de Debito BCP en CEVICHERIA DEL BARRIO.
Fecha y hora
07 de setiembre de 2026 - 02:00 PM
Empresa
CEVICHERIA DEL BARRIO
Numero de operacion
556677""",
        received_at=base + timedelta(hours=2),
    )
    with Session(engine) as s:
        r = ResultadoSync()
        correo_fabrica.sincronizador(s).ingerir(correo, r)
        assert r.transacciones_creadas == 1
        assert r.por_revisar == 1

    pendientes = cliente.get("/api/movimientos/revision").json()
    assert any("Posible duplicado" in (p["notes"] or "") for p in pendientes)


def test_yape_se_carga_a_bcp_debito(cliente):
    """Un yapeo no crea una cuenta "Yape": es un gasto de BCP Debito pagado por
    Yape. Asi el gasto sale de donde realmente sale."""
    from sqlmodel import Session

    from app.plataforma.db import engine
    from app.correo.dominio.correo import RawEmail
    from app.correo.adaptadores import fabrica as correo_fabrica
    from app.correo.aplicacion.sincronizacion import ResultadoSync

    correo = RawEmail(
        gmail_id="msg-yape-real",
        sender="YAPE Notificaciones <notificaciones@yape.pe>",
        subject="Por tu seguridad, te notificaremos por cada yapeo que realices",
        body="""¡Acabas de yapear exitosamente!
Monto de yapeo*
S/ 33.00
Fecha y Hora de la operación
08 septiembre 2026 - 07:20 p. m.
Nombre del Beneficiario
Rosa Mer*
N° de operación
99887766""",
        received_at=datetime(2026, 9, 8, 19, 20),
    )
    with Session(engine) as s:
        correo_fabrica.sincronizador(s).ingerir(correo, ResultadoSync())

    movs = cliente.get("/api/movimientos", params={"buscar": "rosa"}).json()["items"]
    assert len(movs) == 1
    assert movs[0]["account_name"] == "BCP Debito"
    assert movs[0]["payment_method"] == "yape"
    assert movs[0]["amount"] == 33.0


def test_laboratorio_reintenta_sin_remitente(cliente):
    """Pegar solo el cuerpo (sin saber el remitente) tambien debe funcionar."""
    r = cliente.post("/api/parsers/probar", json={
        "sender": "",
        "subject": "",
        "body": "Realizaste un consumo por S/ 18.60 en TAMBO el 09/08/2026",
    }).json()
    assert r["reconocido"] is True
    assert "ignorando el remitente" in (r["motivo"] or "")


def test_produccion_si_exige_remitente():
    """Pero en la ingesta real el remitente sigue siendo obligatorio."""
    from datetime import datetime as dt

    from app.correo.dominio.correo import RawEmail
    from app.correo.adaptadores.salida.patrones import parse_email

    correo = RawEmail(
        gmail_id="x", sender="cualquiera@ejemplo.com", subject="Aviso",
        body="Realizaste un consumo por S/ 18.60 en TAMBO el 09/08/2026",
        received_at=dt(2026, 8, 9),
    )
    parsed, motivo = parse_email(correo)
    assert parsed is None
    assert motivo


# ------------------------------------------------------------------ presupuesto
def test_tope_por_categoria_padre_suma_las_hijas(cliente):
    """Un tope en "Alimentacion" tiene que contar lo gastado en "Delivery":
    si no, poner tope a la categoria padre no serviria de nada."""
    alimentacion = _id_categoria(cliente, "Alimentacion")
    delivery = _id_categoria(cliente, "Delivery")

    cliente.post("/api/movimientos", json={
        "amount": 80.0, "direction": "gasto", "category_id": delivery,
        "merchant": "Delivery de prueba",
        "occurred_at": datetime(2026, 9, 10, 20, 0).isoformat(),
    })
    r = cliente.put("/api/presupuestos", json={"category_id": alimentacion, "amount": 100})
    assert r.status_code == 200

    resumen = cliente.get(
        "/api/resumen", params={"desde": "2026-09-01", "hasta": "2026-09-30"}
    ).json()
    tope = next(p for p in resumen["presupuestos"] if p["categoria"] == "Alimentacion")
    assert tope["tope"] == 100.0
    assert tope["gastado"] >= 80.0


def test_pasarse_del_tope_genera_alerta(cliente):
    entretenimiento = _id_categoria(cliente, "Entretenimiento")
    cliente.put("/api/presupuestos", json={"category_id": entretenimiento, "amount": 20})
    cliente.post("/api/movimientos", json={
        "amount": 150.0, "direction": "gasto", "category_id": entretenimiento,
        "merchant": "Concierto", "occurred_at": datetime(2026, 9, 11, 21, 0).isoformat(),
    })

    resumen = cliente.get(
        "/api/resumen", params={"desde": "2026-09-01", "hasta": "2026-09-30"}
    ).json()
    tope = next(p for p in resumen["presupuestos"] if p["categoria"] == "Entretenimiento")
    assert tope["estado"] == "excedido"
    assert tope["restante"] < 0
    assert any(a["tipo"] == "presupuesto" for a in resumen["alertas"])


def test_sin_topes_no_se_inventa_ninguno(cliente):
    """Lista vacia, no topes por defecto: una alarma que no significa nada
    ensena a ignorar las alarmas."""
    for p in cliente.get("/api/presupuestos").json():
        cliente.delete(f"/api/presupuestos/{p['id']}")
    resumen = cliente.get("/api/resumen").json()
    assert resumen["presupuestos"] == []


def test_no_se_pone_tope_a_una_categoria_de_ingreso(cliente):
    sueldo = _id_categoria(cliente, "Sueldo")
    r = cliente.put("/api/presupuestos", json={"category_id": sueldo, "amount": 100})
    assert r.status_code == 400


def test_meta_de_ahorro(cliente):
    cliente.put("/api/meta-ahorro", json={"amount": 1000})
    resumen = cliente.get(
        "/api/resumen", params={"desde": "2026-09-01", "hasta": "2026-09-30"}
    ).json()
    meta = resumen["meta_ahorro"]
    assert meta is not None
    assert meta["meta"] == 1000.0
    assert "ahorro_proyectado" in meta
    assert "disponible_diario" in meta

    cliente.put("/api/meta-ahorro", json={"amount": 0})
    assert cliente.get("/api/resumen").json()["meta_ahorro"] is None


def test_medio_de_pago_en_el_resumen(cliente):
    resumen = cliente.get(
        "/api/resumen", params={"desde": "2026-09-01", "hasta": "2026-09-30"}
    ).json()
    medios = {m["clave"] for m in resumen["por_medio_pago"]}
    assert "yape" in medios or "efectivo" in medios


def test_sin_historial_no_se_inventa_proyeccion(cliente):
    """Con pocos dias de datos, proyectar es adivinar. Mejor callar: el dia 5,
    extrapolando linealmente, el alquiler ya pagado multiplicaria el gasto
    mensual por seis y dispararia todas las alarmas a la vez."""
    from sqlmodel import Session

    from app.plataforma.db import engine
    from app.analitica.dominio.entidades import Budget
    from app.movimientos.dominio.entidades import Transaction

    with Session(engine) as s:
        movs = s.exec(select(Transaction)).all()
        # duplicate_of_id apunta a otra fila de la misma tabla: hay que soltar
        # la referencia antes de borrar, o salta la clave foranea.
        for tx in movs:
            tx.duplicate_of_id = None
            # Borrarlo TODO solo es posible quitando antes la proteccion de lo
            # que registraste a mano: justo lo que un borrado a ciegas no hace.
            tx.locked_by_user = False
            s.add(tx)
        s.commit()
        for tx in movs:
            s.delete(tx)
        for b in s.exec(select(Budget)).all():
            s.delete(b)
        s.commit()

    hoy = date.today()
    delivery = _id_categoria(cliente, "Delivery")
    cliente.put("/api/presupuestos", json={"category_id": delivery, "amount": 150})
    cliente.post("/api/movimientos", json={
        "amount": 40.0, "direction": "gasto", "category_id": delivery,
        "merchant": "Delivery de hoy",
        "occurred_at": datetime(hoy.year, hoy.month, hoy.day, 20, 0).isoformat(),
    })

    r = cliente.get("/api/resumen").json()
    tope = next(p for p in r["presupuestos"] if p["categoria"] == "Delivery")
    assert tope["proyeccion"] is None
    assert tope["estado"] == "en_curso"       # no "en_riesgo" por una sola compra
    assert r["meta_ahorro"] is None or r["meta_ahorro"]["ahorro_proyectado"] is None


# ------------------------------------------------------------------- importador
def _excel_de_prueba() -> bytes:
    """Reproduce la estructura real del Excel del usuario, incluidas las erratas de
    la columna Observaciones."""
    import io

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Ingresos y gastos"
    ws.append(["Fecha", "Ingresos", "Alimentos", "Transporte", "Taxi",
               "Deliverry", "Otros gastos", "Gastos totales", "Observaciones", "Beneficios"])
    ws.append([date(2026, 1, 5), 0, 15, 0, None, None, 0, 15, "Café", 15])
    ws.append([date(2026, 1, 6), 0, 0, 0, None, None, 63, 63, "Gastos inncesarios", -63])
    ws.append([date(2026, 1, 7), 0, 0, 0, None, None, 305, 305, "Pago del ICPNA", -305])
    ws.append([date(2026, 1, 8), 0, 0, 0, None, None, 44.7, 44.7, "Compras en Plaza Vea", -44.7])
    ws.append([date(2026, 1, 9), 1722.45, 0, 0, None, None, 0, 0, "Pago del mes", 1722.45])
    ws.append([date(2026, 1, 10), 0, 13, 13.5, 20, 35, 0, 81.5, None, -81.5])
    ws.append([date(2026, 1, 11), 0, 0, 0, None, None, 0, 0, None, 0])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_analizar_no_escribe_nada(cliente):
    antes = cliente.get("/api/movimientos", params={"tamano": 1}).json()["total"]
    r = cliente.post(
        "/api/importar/excel/analizar",
        files={"archivo": ("prueba.xlsx", _excel_de_prueba(),
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    ).json()
    assert r["hoja"] == "Ingresos y gastos"
    assert r["filas_con_fecha"] == 7
    assert cliente.get("/api/movimientos", params={"tamano": 1}).json()["total"] == antes


def test_las_columnas_derivadas_no_se_importan(cliente):
    """'Gastos totales' y 'Beneficios' se calculan solas. Importarlas duplicaria
    todos los importes: en el archivo real cuadran al centimo."""
    r = cliente.post(
        "/api/importar/excel/analizar",
        files={"archivo": ("prueba.xlsx", _excel_de_prueba(), "application/octet-stream")},
    ).json()
    assert set(r["columnas_derivadas"]) == {"gastos totales", "beneficios"}
    for m in r["muestra"]:
        assert m["columna"] not in ("gastos totales", "beneficios")


def test_las_observaciones_rescatan_otros_gastos(cliente):
    """El 75% del gasto historico esta en 'Otros gastos'. Las notas dicen que fue."""
    r = cliente.post(
        "/api/importar/excel/analizar",
        files={"archivo": ("prueba.xlsx", _excel_de_prueba(), "application/octet-stream")},
    ).json()
    por_nota = {m["observacion"]: m for m in r["muestra"] if m["origen_categoria"] == "observacion"}
    assert por_nota["Pago del ICPNA"]["categoria"] == "Cursos"
    assert por_nota["Compras en Plaza Vea"]["categoria"] == "Mercado y supermercado"
    assert por_nota["Pago del mes"]["categoria"] == "Sueldo"
    assert r["rescatados_por_observacion"] >= 3


def test_erratas_de_gasto_innecesario(cliente):
    """En el archivo real aparece como 'Gastos inncesarios', 'Gasto Innecesario',
    'gastos innecesarios'... Todas tienen que marcar evitable."""
    from app.excel.dominio.mapeo import clasificar_observacion

    for texto in ["Gasto innecesario", "Gastos inncesarios", "gastos innecesarios",
                  "Gasto Innecesario", "Gasto inncesario", "Café, Gastos inncesarios"]:
        _, necesidad = clasificar_observacion(texto)
        assert necesidad is not None and necesidad.value == "evitable", texto


def test_importar_y_deshacer(cliente):
    contenido = _excel_de_prueba()
    r = cliente.post(
        "/api/importar/excel",
        files={"archivo": ("prueba.xlsx", contenido, "application/octet-stream")},
    )
    assert r.status_code == 201, r.text
    lote = r.json()
    assert lote["created_count"] > 0
    assert lote["desde"] == "2026-01-05"
    assert lote["hasta"] == "2026-01-11"

    enero = cliente.get(
        "/api/movimientos", params={"desde": "2026-01-01", "hasta": "2026-01-31", "tamano": 100}
    ).json()
    assert enero["total"] == lote["created_count"]
    # el ingreso "Pago del mes" entra como ingreso, no como gasto
    assert enero["suma_ingresos"] == 1722.45

    # re-importar el mismo archivo no duplica
    r2 = cliente.post(
        "/api/importar/excel",
        files={"archivo": ("prueba.xlsx", contenido, "application/octet-stream")},
    ).json()
    assert r2["created_count"] == 0
    assert r2["duplicated_count"] == lote["created_count"]

    cliente.delete(f"/api/importar/lotes/{r2['id']}")
    borrados = cliente.delete(f"/api/importar/lotes/{lote['id']}").json()["borrados"]
    assert borrados == lote["created_count"]
    despues = cliente.get(
        "/api/movimientos", params={"desde": "2026-01-01", "hasta": "2026-01-31"}
    ).json()
    assert despues["total"] == 0


def test_rechaza_formatos_que_no_son_excel(cliente):
    r = cliente.post(
        "/api/importar/excel/analizar",
        files={"archivo": ("notas.txt", b"hola", "text/plain")},
    )
    assert r.status_code == 400


def test_purga_de_cuerpos_antiguos():
    """Pasados 90 dias se vacia el texto pero se conserva la ficha: si se borrara
    la fila entera, el correo se volveria a procesar en la siguiente sync."""
    from datetime import timedelta as td
    from datetime import timezone as tz

    from sqlmodel import Session

    from app.plataforma.db import engine
    from app.correo.adaptadores import fabrica as correo_fabrica
    from app.correo.dominio.entidades import EmailMessage, ParseStatus

    ahora = datetime.now(tz.utc)
    with Session(engine) as s:
        s.add(EmailMessage(
            gmail_id="viejo-1", sender="notificaciones@notificacionesbcp.com.pe",
            subject="Consumo antiguo", received_at=ahora - td(days=120),
            snippet="algo", body_text="CUERPO SENSIBLE ANTIGUO",
            parse_status=ParseStatus.parseado,
        ))
        s.add(EmailMessage(
            gmail_id="reciente-1", sender="notificaciones@notificacionesbcp.com.pe",
            subject="Consumo reciente", received_at=ahora - td(days=10),
            snippet="algo", body_text="CUERPO RECIENTE",
            parse_status=ParseStatus.parseado,
        ))
        s.commit()

        assert correo_fabrica.sincronizador(s).purgar_cuerpos_antiguos(dias=90) == 1

        viejo = s.exec(select(EmailMessage).where(EmailMessage.gmail_id == "viejo-1")).one()
        reciente = s.exec(select(EmailMessage).where(EmailMessage.gmail_id == "reciente-1")).one()
        assert viejo.body_text == ""          # contenido borrado
        assert viejo.subject == "Consumo antiguo"   # ficha conservada
        assert reciente.body_text == "CUERPO RECIENTE"


def test_una_nota_ambigua_no_se_adivina():
    """El caso que lo demostro: una fila de varios miles de soles con la nota
    "Claro, Mestria" acabo entera en "Plan movil", inflando esa categoria al 32%
    del anio. Ese dia se pago el recibo de Claro (decenas de soles) Y una maestria
    (miles): la nota describe el dia, pero el importe es uno solo."""
    from app.excel.dominio.mapeo import clasificar_observacion

    cat, _ = clasificar_observacion("Claro, Mestria")
    assert cat is None, "con dos pistas distintas no se puede elegir una"

    # cada una por separado si se reconoce
    assert clasificar_observacion("Claro")[0] == "Plan movil"
    assert clasificar_observacion("Mestria")[0] == "Cursos"

    # y la marca de evitable sobrevive aunque la categoria quede sin decidir
    _, necesidad = clasificar_observacion("Gasto Innecesario, Cine, Disney Plus")
    assert necesidad is not None and necesidad.value == "evitable"


# ------------------------------------------------------------------------ IMAP
def test_aplanado_de_correo_mime_real():
    """El correo que devuelve IMAP es un email.message.Message, no el JSON de la
    API de Gmail. Tiene que producir el mismo texto para los mismos parsers."""
    from email.message import EmailMessage as MensajeMIME

    from app.correo.adaptadores.salida.html import decode_header_value, extract_body_mime

    msg = MensajeMIME()
    msg["From"] = "BCP Notificaciones <notificaciones@notificacionesbcp.com.pe>"
    # Asunto codificado en RFC 2047, como llega de verdad cuando lleva tildes
    msg["Subject"] = "=?UTF-8?B?UmVhbGl6YXN0ZSB1biBjb25zdW1vIGNvbiB0dSBUYXJqZXRhIGRlIENyw6lkaXRv?="
    msg.set_content("version en texto plano")
    msg.add_alternative(
        "<html><body><p>Realizaste un consumo de <b>S/ 12.30</b> con tu "
        "Tarjeta de Credito BCP en TAMBO.</p>"
        "<table><tr><td>Empresa</td><td>TAMBO</td></tr>"
        "<tr><td>Numero de operacion</td><td>998877</td></tr></table>"
        "</body></html>",
        subtype="html",
    )

    assert decode_header_value(msg["Subject"]) == "Realizaste un consumo con tu Tarjeta de Crédito"
    texto = extract_body_mime(msg)
    assert "S/ 12.30" in texto
    assert "TAMBO" in texto
    # las celdas de la tabla caen en lineas distintas, como en la API de Gmail
    assert "Empresa" in texto


def test_un_correo_imap_llega_hasta_movimiento(cliente):
    """De MIME crudo a movimiento clasificado, por el mismo pipeline."""
    from email.message import EmailMessage as MensajeMIME

    from sqlmodel import Session

    from app.plataforma.db import engine
    from app.correo.adaptadores.salida.html import extract_body_mime
    from app.correo.dominio.correo import RawEmail
    from app.correo.adaptadores import fabrica as correo_fabrica
    from app.correo.aplicacion.sincronizacion import ResultadoSync

    msg = MensajeMIME()
    msg["From"] = "BCP Notificaciones <notificaciones@notificacionesbcp.com.pe>"
    msg["Subject"] = "Realizaste un consumo con tu Tarjeta de Debito BCP"
    msg.set_content("texto plano")
    msg.add_alternative(
        "<html><body>"
        "<p>Realizaste un consumo de S/ 55.50 con tu Tarjeta de Debito BCP en METRO.</p>"
        "<table>"
        "<tr><td>Fecha y hora</td><td>10 de setiembre de 2026 - 06:15 PM</td></tr>"
        "<tr><td>Empresa</td><td>METRO</td></tr>"
        "<tr><td>Numero de operacion</td><td>555111</td></tr>"
        "</table></body></html>",
        subtype="html",
    )

    crudo = RawEmail(
        gmail_id="imap-9001",
        sender=msg["From"],
        subject=msg["Subject"],
        body=extract_body_mime(msg),
        received_at=datetime(2026, 9, 10, 18, 15),
    )
    with Session(engine) as s:
        r = ResultadoSync()
        correo_fabrica.sincronizador(s).ingerir(crudo, r)
        assert r.transacciones_creadas == 1

    movs = cliente.get("/api/movimientos", params={"buscar": "metro"}).json()["items"]
    assert any(m["amount"] == 55.5 and m["account_name"] == "BCP Debito" for m in movs)


def test_estado_dice_si_esta_conectado_y_como(cliente):
    """La pantalla tiene que poder decir con claridad si lee el correo o no."""
    e = cliente.get("/api/gmail/estado").json()
    assert e["backend"] in ("imap", "gmail")
    assert "autorizado" in e
    assert "sync_automatica_min" in e
    # El valor concreto sale del .env y cambia segun se este calibrando o no:
    # clavarlo aqui convertia un ajuste de configuracion en un test roto.
    assert isinstance(e["retencion_dias"], int) and e["retencion_dias"] >= 0
    assert isinstance(e["ventana_automatica"], int) and e["ventana_automatica"] > 0


def test_probar_conexion_sin_credenciales_explica_que_falta(cliente):
    """Sin credenciales, el error tiene que decir QUE falta y DONDE."""
    from app.plataforma.config import settings

    if not settings.usa_imap:
        pytest.skip("solo aplica en modo IMAP")
    if settings.imap_user and settings.imap_password:
        pytest.skip("hay credenciales configuradas: este caso no aplica")
    r = cliente.post("/api/correo/probar").json()
    assert r["ok"] is False
    assert "IMAP_USER" in r["error"] or "apppasswords" in r["error"]


def test_dos_correos_del_mismo_retiro_no_lo_cuentan_dos_veces(cliente):
    """El BBVA manda DOS correos por cada retiro en cajero: la "Constancia de
    Retiro en ATM" y "Tu operacion en nuestros cajeros". Y como en los correos
    reales solo UNO trae numero de operacion, sus huellas nunca coinciden: la
    huella corta en cuanto hay numero de operacion. Hace falta ademas comparar
    importe, cuenta y minuto."""
    from sqlmodel import Session

    from app.plataforma.db import engine
    from app.correo.dominio.correo import RawEmail
    from app.correo.adaptadores import fabrica as correo_fabrica
    from app.correo.aplicacion.sincronizacion import ResultadoSync

    BB = "BBVA <procesos@bbva.com.pe>"
    constancia = RawEmail(
        gmail_id="atm-constancia", sender=BB, subject="BBVA - Constancia de Retiro en ATM",
        body="""Hola, Carlos
Has realizado con exito la operacion:
Retiro de efectivo
Monto de retiro
S/ 250.00
Fecha y hora
12 de setiembre de 2026 - 09:30 AM
Comision
S/ 0.00
Numero de operacion
000000000425""",
        received_at=datetime(2026, 9, 12, 9, 30),
    )
    cajero = RawEmail(
        gmail_id="atm-cajero", sender=BB,
        subject="Tu operacion en nuestros cajeros automaticos ha sido aprobada",
        body="""Hola, CARLOS
OPERACION APROBADA
datos de su operacion en cajero
Fecha y hora
12/09/2026 09:30:00
Numero de cajero
1488
Moneda
PEN
Importe
250.00""",
        received_at=datetime(2026, 9, 12, 9, 31),
    )

    with Session(engine) as s:
        r = ResultadoSync()
        correo_fabrica.sincronizador(s).ingerir(constancia, r)
        correo_fabrica.sincronizador(s).ingerir(cajero, r)
        assert r.correos_nuevos == 2, "los dos correos se archivan"
        assert r.transacciones_creadas == 1, "pero el retiro cuenta UNA vez"
        assert r.duplicados == 1

    # el segundo queda guardado y marcado, no desaparece sin dejar rastro
    marcados = cliente.get(
        "/api/movimientos", params={"estado": "duplicada", "tamano": 50}
    ).json()
    assert any("notificado por dos correos" in (m["notes"] or "") for m in marcados["items"])


def test_dos_gastos_iguales_el_mismo_dia_si_cuentan_dos_veces(cliente):
    """El reverso: dos cafes de S/5 el mismo dia son dos gastos, no uno. Por eso
    la huella usa la hora al minuto y no solo la fecha."""
    base = {"amount": 5.0, "direction": "gasto", "merchant": "Bodega la esquina"}
    a = cliente.post("/api/movimientos", json={
        **base, "occurred_at": datetime(2026, 9, 13, 9, 0).isoformat()})
    b = cliente.post("/api/movimientos", json={
        **base, "occurred_at": datetime(2026, 9, 13, 18, 30).isoformat()})
    assert a.status_code == 201 and b.status_code == 201
    assert a.json()["id"] != b.json()["id"]

    encontrados = cliente.get(
        "/api/movimientos", params={"buscar": "bodega la esquina"}
    ).json()
    assert encontrados["total"] == 2


def test_dos_transferencias_iguales_con_operaciones_distintas_son_dos(cliente):
    """El reverso del caso anterior. Dos transferencias del BCP de S/400 a las
    14:07 con numeros de operacion 02992672 y 02998363 son DOS movimientos
    reales, no una notificacion repetida."""
    from sqlmodel import Session

    from app.plataforma.db import engine
    from app.correo.dominio.correo import RawEmail
    from app.correo.adaptadores import fabrica as correo_fabrica
    from app.correo.aplicacion.sincronizacion import ResultadoSync

    BC = "BCP Notificaciones <notificaciones@notificacionesbcp.com.pe>"

    def transferencia(gid, operacion):
        return RawEmail(
            gmail_id=gid, sender=BC, subject="Constancia de Transferencia a Terceros BCP",
            body=f"""Hola Carlos Alberto,
Realizaste una transferencia de S/ 400.00 desde tu Clasica.
Montos
Monto transferido
S/ 400.00
Datos de la operacion
Fecha y hora
11 de setiembre de 2026 - 02:07 PM
Enviado a
Juan Perez
Numero de operacion
{operacion}""",
            received_at=datetime(2026, 9, 11, 14, 7),
        )

    with Session(engine) as s:
        r = ResultadoSync()
        correo_fabrica.sincronizador(s).ingerir(transferencia("tr-a", "02992672"), r)
        correo_fabrica.sincronizador(s).ingerir(transferencia("tr-b", "02998363"), r)
        assert r.transacciones_creadas == 2, "operaciones distintas = movimientos distintos"
        assert r.duplicados == 0


# --------------------------------------------------------------- que entra a revision
def _ingerir(gmail_id: str, subject: str, body: str, sender: str):
    from sqlmodel import Session

    from app.plataforma.db import engine
    from app.correo.dominio.correo import RawEmail
    from app.correo.adaptadores import fabrica as correo_fabrica
    from app.correo.aplicacion.sincronizacion import ResultadoSync

    correo = RawEmail(
        gmail_id=gmail_id, sender=sender, subject=subject, body=body,
        received_at=datetime(2026, 9, 6, 18, 0),
    )
    with Session(engine) as s:
        r = ResultadoSync()
        correo_fabrica.sincronizador(s).ingerir(correo, r)
        assert r.transacciones_creadas == 1, "el correo no produjo movimiento"
        from app.movimientos.dominio.entidades import Transaction
        return s.exec(select(Transaction).order_by(Transaction.id.desc())).first()


def test_un_pago_a_persona_no_se_queda_esperando_revision():
    """Yape dice a quien le pagaste, nunca para que. Revisarlo no lo averigua.

    Con la pista del parser valorada en 0.7 (bajo el umbral de 0.75), los 45
    pagos a personas del usuario se quedaban en la bandeja para siempre: no habia
    nada que hacer con ellos y tapaban los 18 que si necesitaban una decision.
    """
    from app.compartido.tipos import TxStatus

    tx = _ingerir(
        "rev-yape-1",
        "Confirmacion de yapeo",
        """¡Hola, Carlos Qui*!
¡Acabas de yapear exitosamente!
Monto de yapeo*
S/ 25.00
Yapeaste a
Fulana Per*
Fecha y Hora de la operación
06 septiembre 2026 - 10:00 a. m.
Nro. de operación
99887766""",
        "notificaciones@yape.pe",
    )
    assert tx.status == TxStatus.confirmada
    assert tx.confidence >= 0.75


def test_un_traspaso_que_declara_el_banco_no_se_queda_esperando_revision():
    """"Entre cuentas propias" no es un cajon de sastre: es la respuesta."""
    from app.compartido.tipos import Direction, TxStatus

    tx = _ingerir(
        "rev-propias-1",
        "Constancia de transferencia entre mis cuentas",
        """Hola Carlos Alberto,
Realizaste una transferencia entre mis cuentas de S/ 500.00.
Monto transferido
S/ 500.00
Desde
Clasica
**** 0101
Fecha y hora
06 de setiembre de 2026 - 10:00 AM
Numero de operacion
55443322""",
        "notificaciones@notificacionesbcp.com.pe",
    )
    assert tx.direction == Direction.transferencia
    assert tx.status == TxStatus.confirmada


def test_un_envio_a_ti_mismo_no_cuenta_como_gasto_y_dice_por_que():
    """Sale del gasto, y el movimiento lleva escrito el motivo.

    No va a la bandeja de revision: son 121 movimientos en el historial del usuario
    y solo servirian para taparla. Lo que hace la app es avisarlo UNA vez en el
    panel, con el importe total, para que pueda auditarlos si quiere.
    """
    from app.correo.dominio.dinero_propio import NOTA_ENVIO_PROPIO
    from app.compartido.tipos import Direction, TxStatus

    tx = _ingerir(
        "rev-propio-1",
        "Constancia de Transferencia a Otros Bancos",
        """Hola Carlos Alberto,
Realizaste una transferencia de S/ 400.00 desde tu Clasica.
Monto enviado
S/ 400.00
Enviado a
Carlos Alberto Quispe M.
**** 0404
Banco destino
Bbva
Desde
Clasica
**** 0101
Fecha y hora
06 de setiembre de 2026 - 10:00 AM
Numero de operacion
11223344""",
        "notificaciones@notificacionesbcp.com.pe",
    )
    assert tx.direction == Direction.transferencia
    assert tx.notes == NOTA_ENVIO_PROPIO      # el movimiento explica por que
    assert tx.status == TxStatus.confirmada   # pero no tapa la bandeja


def test_el_motivo_no_culpa_al_parser_de_lo_que_no_es_suyo():
    """`confidence` mezcla la lectura del correo y la eleccion de categoria.

    Decir "el parser leyo mal" cuando el importe estaba perfecto mandaba al
    usuario a cotejar un dato correcto, y dejaba sin explicar lo que si fallaba.
    """
    from app.compartido.tipos import Direction
    from app.movimientos.dominio.entidades import Transaction
    from app.movimientos.adaptadores.fabrica import confianza_del_parser
    from app.movimientos.dominio import revision

    tx = Transaction(
        occurred_at=datetime(2026, 9, 6, 10, 0), booking_date=date(2026, 9, 6),
        amount_cents=2500, currency="PEN", direction=Direction.gasto,
        merchant="algun comercio", account_id=1, category_id=1,
        confidence=0.6, parser="bcp_consumo_debito",   # el parser declara 0.95
    )
    motivo = revision.motivo_confianza(tx, confianza_del_parser(tx.parser))
    assert motivo["clave"] == "categoria_dudosa"
    assert "se leyeron bien" in motivo["texto"]

    tx.parser = None                                    # nada que consultar
    assert revision.motivo_confianza(tx, None)["clave"] == "lectura_dudosa"


# ------------------------------------------------------------------- bugs reportados
def test_borrar_un_movimiento_con_duplicados_apuntandolo(cliente):
    """duplicate_of_id es una foranea a la propia tabla, y SQLite las aplica.

    Borrar el movimiento al que otro señalaba como duplicado devolvia un 500.
    """
    a = cliente.post("/api/movimientos", json={
        "occurred_at": "2026-09-06T10:00:00", "amount": 50, "direction": "gasto",
        "merchant": "kiosko",
    }).json()
    b = cliente.post("/api/movimientos", json={
        "occurred_at": "2026-09-06T10:01:00", "amount": 50, "direction": "gasto",
        "merchant": "kiosko",
    }).json()
    # duplicate_of_id no se puede tocar por la API a proposito: lo pone el
    # pipeline al detectar una sospecha cruzada. Se monta como lo montaria el.
    _marcar_duplicado(b["id"], a["id"])

    assert cliente.delete(f"/api/movimientos/{a['id']}").status_code == 204
    # El que apuntaba sigue vivo, ya sin la referencia colgando.
    quedan = cliente.get("/api/movimientos", params={"buscar": "kiosko"}).json()["items"]
    superviviente = next(m for m in quedan if m["id"] == b["id"])
    assert superviviente["duplicate_of_id"] is None


def test_borrar_una_categoria_con_subcategorias_avisa_en_vez_de_reventar(cliente):
    padre = cliente.post("/api/categorias", json={"name": "Prueba padre", "kind": "gasto"}).json()
    cliente.post("/api/categorias", json={
        "name": "Prueba hija", "kind": "gasto", "parent_id": padre["id"],
    })
    r = cliente.delete(f"/api/categorias/{padre['id']}")
    assert r.status_code == 409
    assert "subcategoria" in r.json()["detail"]


def test_los_totales_de_movimientos_no_cuentan_duplicados_ni_ignorados(cliente):
    """La cabecera de la tabla daba un total y el panel otro, para el mismo mes."""
    real = cliente.post("/api/movimientos", json={
        "occurred_at": "2026-07-15T10:00:00", "amount": 100, "direction": "gasto",
        "merchant": "tienda que si cuenta",
    }).json()
    ignorado = cliente.post("/api/movimientos", json={
        "occurred_at": "2026-07-15T11:00:00", "amount": 999, "direction": "gasto",
        "merchant": "tienda que no cuenta",
    }).json()
    cliente.patch(f"/api/movimientos/{ignorado['id']}", json={"status": "ignorada"})

    pagina = cliente.get("/api/movimientos", params={"desde": "2026-07-01", "hasta": "2026-07-31"}).json()
    assert pagina["suma_gastos"] == 100
    assert real["id"] in [m["id"] for m in pagina["items"]]


def test_elegir_categoria_en_la_bandeja_no_hace_desaparecer_la_ficha(cliente):
    """Si el backend auto-confirma al recibir categoria, la tarjeta se desmonta
    antes de que puedas marcar la necesidad. Con `status` explicito, no."""
    cats = cliente.get("/api/categorias").json()
    cat = next(c for c in cats if c["kind"] == "gasto" and c["parent_id"])

    mov = cliente.post("/api/movimientos", json={
        "occurred_at": "2026-09-06T12:00:00", "amount": 20, "direction": "gasto",
        "merchant": "algo sin clasificar",
    }).json()
    cliente.patch(f"/api/movimientos/{mov['id']}", json={"status": "por_revisar"})

    r = cliente.patch(
        f"/api/movimientos/{mov['id']}",
        json={"category_id": cat["id"], "status": "por_revisar"},
    ).json()
    assert r["status"] == "por_revisar"       # sigue en la bandeja
    assert r["category_id"] == cat["id"]      # pero ya con su categoria

    # Y al confirmar de verdad, se va.
    r = cliente.patch(f"/api/movimientos/{mov['id']}", json={"status": "confirmada"}).json()
    assert r["status"] == "confirmada"
    assert r["confidence"] == 1.0


def test_serie_por_meses_y_por_anios(cliente):
    for fecha_iso, monto in [
        ("2026-01-10", 100), ("2026-02-08", 200), ("2026-03-05", 250), ("2026-03-20", 50),
    ]:
        cliente.post("/api/movimientos", json={
            "occurred_at": f"{fecha_iso}T10:00:00", "amount": monto, "direction": "gasto",
            "merchant": "prueba serie",
        })

    meses = cliente.get("/api/resumen/periodos", params={
        "agrupar": "mes", "desde": "2026-01-01", "hasta": "2026-03-31",
    }).json()
    etiquetas = [p["periodo"] for p in meses["periodos"]]
    # Febrero no tiene movimientos pero aparece: un hueco se leeria como que dos
    # barras contiguas son meses consecutivos.
    assert etiquetas == ["2026-01", "2026-02", "2026-03"]
    assert meses["periodos"][0]["variacion"] is None      # no hay mes anterior
    assert meses["periodos"][2]["gasto"] == 300
    assert meses["periodos"][2]["variacion"] == 50.0      # 200 -> 300

    assert meses["totales"]["periodos_con_datos"] == 3
    assert meses["totales"]["mayor"]["periodo"] == "2026-03"

    # Un mes sin movimientos sale en cero, no desaparece: un hueco se leeria
    # como que dos barras contiguas son meses consecutivos.
    con_hueco = cliente.get("/api/resumen/periodos", params={
        "agrupar": "mes", "desde": "2026-01-01", "hasta": "2026-05-31",
    }).json()
    assert [p["periodo"] for p in con_hueco["periodos"]][-2:] == ["2026-04", "2026-05"]
    assert con_hueco["periodos"][-1]["gasto"] == 0
    # y esos meses vacios no rebajan el promedio
    assert con_hueco["totales"]["periodos_con_datos"] == 3

    anios = cliente.get("/api/resumen/periodos", params={"agrupar": "anio"}).json()
    assert all(len(p["periodo"]) == 4 for p in anios["periodos"])


def test_dos_gastos_del_mismo_importe_en_comercios_distintos_no_son_duplicados(cliente):
    """La ventana de sospecha cruzada es de 36 horas.

    Con solo "mismo importe", dos cafes de S/3.10 en dos dias distintos se
    acusaban de ser el mismo gasto. Si ambos dicen su comercio y no coinciden,
    son dos gastos y punto.
    """
    from sqlmodel import Session

    from app.plataforma.db import engine
    from app.movimientos.adaptadores import fabrica
    from app.compartido.tipos import Direction, Source, TxStatus
    from app.movimientos.dominio.entidades import Transaction

    with Session(engine) as s:
        a = Transaction(
            occurred_at=datetime(2026, 6, 8, 8, 52), booking_date=date(2026, 6, 8),
            amount_cents=240, currency="PEN", direction=Direction.gasto,
            merchant="oxxo", account_id=1, source=Source.gmail,
            status=TxStatus.confirmada, dedupe_hash="h-oxxo",
        )
        b = Transaction(
            occurred_at=datetime(2026, 6, 9, 14, 46), booking_date=date(2026, 6, 9),
            amount_cents=240, currency="PEN", direction=Direction.gasto,
            merchant="tambo", account_id=2, source=Source.manual,
            status=TxStatus.confirmada, dedupe_hash="h-tambo",
        )
        s.add(a); s.commit(); s.refresh(a)
        s.add(b); s.commit(); s.refresh(b)
        assert fabrica.registro(s).sospecha_de_duplicado(b) is None

        # Pero el mismo comercio y el mismo importe si levantan la sospecha.
        c = Transaction(
            occurred_at=datetime(2026, 6, 9, 15, 0), booking_date=date(2026, 6, 9),
            amount_cents=240, currency="PEN", direction=Direction.gasto,
            merchant="oxxo", account_id=2, source=Source.manual,
            status=TxStatus.confirmada, dedupe_hash="h-oxxo-2",
        )
        s.add(c); s.commit(); s.refresh(c)
        assert fabrica.registro(s).sospecha_de_duplicado(c) is not None


# ------------------------------------------------ hallazgos de la revision de codigo
def test_elegir_categoria_deja_de_ser_dudoso_aunque_siga_en_la_bandeja(cliente):
    """Si la confianza se queda en 0.3, la ficha responde "lo dudoso es la
    categoria (30%)" sobre la categoria que el usuario acaba de elegir."""
    cat = next(c for c in cliente.get("/api/categorias").json()
               if c["kind"] == "gasto" and c["parent_id"])
    mov = cliente.post("/api/movimientos", json={
        "occurred_at": "2026-09-06T12:00:00", "amount": 20, "direction": "gasto",
        "merchant": "comercio desconocido del test",
    }).json()
    cliente.patch(f"/api/movimientos/{mov['id']}", json={"status": "por_revisar"})

    r = cliente.patch(f"/api/movimientos/{mov['id']}",
                      json={"category_id": cat["id"], "status": "por_revisar"}).json()
    assert r["status"] == "por_revisar"      # sigue en la bandeja, como se pidio
    assert r["confidence"] == 1.0            # pero ya no es una suposicion
    claves = [m["clave"] for m in r["motivos"]]
    assert "categoria_dudosa" not in claves


def test_los_ignorados_siguen_siendo_alcanzables(cliente):
    """Dejaron de salir en el listado por defecto: si no hay forma de filtrarlos,
    ignorar un movimiento es irreversible."""
    mov = cliente.post("/api/movimientos", json={
        "occurred_at": "2026-11-15T10:00:00", "amount": 77, "direction": "gasto",
        "merchant": "algo que se ignora",
    }).json()
    cliente.patch(f"/api/movimientos/{mov['id']}", json={"status": "ignorada"})

    por_defecto = cliente.get("/api/movimientos", params={"buscar": "algo que se ignora"}).json()
    assert por_defecto["total"] == 0                       # fuera de los totales
    filtrado = cliente.get("/api/movimientos",
                           params={"estado": "ignorada", "buscar": "algo que se ignora"}).json()
    assert filtrado["total"] == 1                          # pero se puede llegar


def test_borrar_el_original_no_borra_la_explicacion_del_duplicado(cliente):
    """Las notas del sistema se comparan por su principio, no enteras: si no,
    cualquier aviso anadido despues dejaba al movimiento sin explicacion."""
    from app.correo.dominio.dinero_propio import NOTA_ENVIO_PROPIO, motivo_no_es_gasto

    a = cliente.post("/api/movimientos", json={
        "occurred_at": "2026-10-01T10:00:00", "amount": 400, "direction": "gasto",
        "merchant": "original",
    }).json()
    b = cliente.post("/api/movimientos", json={
        "occurred_at": "2026-10-01T10:02:00", "amount": 400, "direction": "transferencia",
        "merchant": "envio propio", "notes": NOTA_ENVIO_PROPIO,
    }).json()
    _marcar_duplicado(b["id"], a["id"])

    assert cliente.delete(f"/api/movimientos/{a['id']}").status_code == 204
    quedan = cliente.get("/api/movimientos", params={"buscar": "envio propio"}).json()["items"]
    superviviente = next(m for m in quedan if m["id"] == b["id"])
    assert motivo_no_es_gasto(superviviente["notes"]) == NOTA_ENVIO_PROPIO
    assert "se borro" in superviviente["notes"]     # y ademas queda el aviso


def test_un_rango_de_fechas_al_reves_se_rechaza(cliente):
    r = cliente.get("/api/resumen", params={"desde": "2026-09-30", "hasta": "2026-09-01"})
    assert r.status_code == 400
    r = cliente.get("/api/resumen/periodos", params={"desde": "2026-09-30", "hasta": "2026-09-01"})
    assert r.status_code == 400


def test_la_purga_mide_los_dias_en_la_misma_hora_en_que_guarda(cliente):
    """`received_at` se guarda sin zona y en hora de Lima; el limite se calculaba
    sobre UTC, cinco horas por delante. Un correo justo en la frontera se
    borraba antes de tiempo."""
    from datetime import datetime as dt
    from zoneinfo import ZoneInfo

    from sqlmodel import Session

    from app.plataforma.config import settings
    from app.plataforma.db import engine
    from app.correo.adaptadores import fabrica as correo_fabrica
    from app.correo.dominio.entidades import EmailMessage, ParseStatus

    TZ = ZoneInfo(settings.timezone)
    ahora = dt.now(TZ).replace(tzinfo=None)
    with Session(engine) as s:
        # Justo dentro de la ventana, pero fuera si se midiera en UTC (+5h).
        frontera = EmailMessage(
            gmail_id="frontera-purga", sender="x@y", subject="s",
            received_at=ahora - timedelta(days=30) + timedelta(hours=2),
            body_text="tengo cuerpo", parse_status=ParseStatus.parseado,
        )
        s.add(frontera)
        s.commit()
        correo_fabrica.sincronizador(s).purgar_cuerpos_antiguos(dias=30)
        s.refresh(frontera)
        assert frontera.body_text == "tengo cuerpo"   # NO debia borrarse


def test_el_reparseo_no_se_queda_a_medias_ni_lo_tumba_un_correo_roto(cliente):
    """El tope era 500 y la ruta no lo decia: con 626 correos archivados, pulsar
    una vez dejaba 126 sin tocar y el resultado no daba ninguna pista."""
    import inspect

    from app.correo.aplicacion.sincronizacion import ServicioSincronizacion

    firma = inspect.signature(ServicioSincronizacion.reparsear_pendientes)
    assert firma.parameters["limite"].default >= 5000

    # Y cada correo va en su propio try, como en la sincronizacion: uno roto no
    # puede tirar el lote entero.
    fuente = inspect.getsource(ServicioSincronizacion.reparsear_pendientes)
    assert "except Exception" in fuente


def test_datacell_y_taxi_se_clasifican_solos(cliente):
    """Dos correcciones que dio el usuario: que es Datacell, y que "Taxi por app"
    mentia (sus tres taxis eran de la calle, pagados por Yape al taxista)."""
    accesorios = cliente.post("/api/movimientos", json={
        "occurred_at": "2026-09-09T21:50:00", "amount": 2, "direction": "gasto",
        "merchant": "IZI*DATACELL",
    }).json()
    assert accesorios["merchant"] == "datacell"
    assert accesorios["category_name"] == "Tecnologia"

    # La categoria se llama "Taxi" a secas: como pagaste ya lo dice el medio de
    # pago, y separarlo por eso repartia el mismo gasto en dos sitios.
    nombres = [c["name"] for c in cliente.get("/api/categorias").json()]
    assert "Taxi" in nombres
    assert "Taxi por app" not in nombres

    taxi = cliente.post("/api/movimientos", json={
        "occurred_at": "2026-09-09T08:00:00", "amount": 15, "direction": "gasto",
        "merchant": "UBER TRIP",
    }).json()
    assert taxi["category_name"] == "Taxi"
