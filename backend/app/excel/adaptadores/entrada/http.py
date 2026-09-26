"""Importacion del Excel historico desde la interfaz.

Dos pasos a proposito: primero **analizar** (no escribe nada) y luego
**confirmar**. Importar cuatro anios de datos a ciegas y descubrir despues que el
mapeo estaba mal es exactamente el error que este flujo evita.

La seccion entera esta apagada salvo IMPORTAR_EXCEL_HABILITADO=true: el Excel ya
esta importado hasta el 31/08/2026, y otro archivo con filas de setiembre en adelante
duplicaria los gastos que desde entonces llegan por correo.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlmodel import Session
from starlette.concurrency import run_in_threadpool

from app.excel.adaptadores import fabrica
from app.excel.aplicacion.importacion import ServicioImportacion
from app.excel.dominio.entidades import ImportBatch
from app.plataforma import respaldo
from app.plataforma.config import settings
from app.plataforma.db import get_session


def _exigir_habilitado() -> None:
    """Se corta en el servidor y no solo escondiendo el menu: un boton oculto
    sigue siendo una URL que cualquiera puede llamar."""
    if not settings.importar_excel_habilitado:
        raise HTTPException(
            403,
            "La importacion de Excel esta deshabilitada. Para usarla, pon "
            "IMPORTAR_EXCEL_HABILITADO=true y reinicia la aplicacion.",
        )


router = APIRouter(dependencies=[Depends(_exigir_habilitado)])


def _importacion(session: Session = Depends(get_session)) -> ServicioImportacion:
    return fabrica.importacion(session)

MAX_BYTES = 20 * 1024 * 1024          # 20 MB: el archivo real pesa 0.3 MB
EXTENSIONES = (".xlsx", ".xlsm", ".xltx", ".xltm")


async def _leer(archivo: UploadFile) -> bytes:
    if not archivo.filename or not archivo.filename.lower().endswith(EXTENSIONES):
        raise HTTPException(400, f"Formato no soportado. Se admite: {', '.join(EXTENSIONES)}")
    contenido = await archivo.read()
    if len(contenido) > MAX_BYTES:
        raise HTTPException(413, "El archivo supera los 20 MB")
    if not contenido:
        raise HTTPException(400, "El archivo esta vacio")
    return contenido


def _copia_previa(motivo: str) -> None:
    """Importar o deshacer mueve miles de filas de golpe: primero, una copia de la
    base. Si no se puede hacer, no se toca nada."""
    try:
        respaldo.copia_previa(motivo)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            503, f"No se pudo hacer la copia de seguridad previa, asi que no se toco nada: {exc}"
        ) from exc


@router.post("/importar/excel/analizar", tags=["importar"])
async def analizar(
    archivo: UploadFile = File(...),
    hoja: str | None = Form(default=None),
    fecha_hasta: date | None = Form(default=None),
    fecha_desde: date | None = Form(default=None),
    servicio: ServicioImportacion = Depends(_importacion),
):
    """Dice que pasaria si importaras. No escribe nada en la base de datos."""
    contenido = await _leer(archivo)
    try:
        res = servicio.analizar(
            contenido, hoja, fecha_hasta=fecha_hasta, fecha_desde=fecha_desde,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"No se pudo leer el archivo: {exc}") from exc

    return {
        "hoja": res.hoja,
        "hojas_disponibles": res.hojas_disponibles,
        "columnas_detectadas": res.columnas_detectadas,
        "columnas_importadas": res.columnas_importadas,
        "columnas_derivadas": res.columnas_derivadas,
        "columnas_sin_mapeo": res.columnas_sin_mapeo,
        "filas_leidas": res.filas_leidas,
        "filas_con_fecha": res.filas_con_fecha,
        "movimientos": res.movimientos,
        "rescatados_por_observacion": res.rescatados_por_observacion,
        "sin_clasificar": res.sin_clasificar,
        "desde": res.desde.isoformat() if res.desde else None,
        "hasta": res.hasta.isoformat() if res.hasta else None,
        "total_ingresos": res.total_ingresos,
        "total_gastos": res.total_gastos,
        "avisos": res.avisos,
        "muestra": [
            {
                "fecha": m.fecha.isoformat(), "columna": m.columna, "monto": m.monto,
                "direccion": m.direccion, "categoria": m.categoria,
                "necesidad": m.necesidad, "observacion": m.observacion,
                "origen_categoria": m.origen_categoria,
            }
            for m in res.muestra
        ],
    }


@router.post("/importar/excel", tags=["importar"], status_code=201)
async def importar(
    archivo: UploadFile = File(...),
    hoja: str | None = Form(default=None),
    cuenta_id: int | None = Form(default=None),
    usar_observaciones: bool = Form(default=True),
    fecha_hasta: date | None = Form(default=None),
    fecha_desde: date | None = Form(default=None),
    servicio: ServicioImportacion = Depends(_importacion),
):
    contenido = await _leer(archivo)
    await run_in_threadpool(_copia_previa, "importar un Excel")
    try:
        lote = servicio.importar(
            contenido, archivo.filename or "sin_nombre.xlsx",
            hoja=hoja, cuenta_id=cuenta_id, usar_observaciones=usar_observaciones,
            fecha_hasta=fecha_hasta, fecha_desde=fecha_desde,
        )
    except Exception as exc:  # noqa: BLE001
        servicio.uow.deshacer()
        raise HTTPException(400, f"Fallo la importacion: {exc}") from exc

    return _lote_out(lote)


@router.get("/importar/lotes", tags=["importar"])
def lotes(servicio: ServicioImportacion = Depends(_importacion)):
    return [_lote_out(l) for l in servicio.lotes_recientes()]


@router.delete("/importar/lotes/{lote_id}", tags=["importar"])
def deshacer(
    lote_id: int,
    incluir_protegidos: bool = Query(False, description="Borra tambien las filas que corregiste tu"),
    servicio: ServicioImportacion = Depends(_importacion),
):
    """Deshace una importacion completa. Borra exactamente lo que entro.

    Si corregiste alguna de sus filas responde 409, diciendo cuantas, y no borra
    nada hasta que lo confirmes con `incluir_protegidos=true`. Antes de borrar
    hace una copia de la base.
    """
    if not servicio.obtener_lote(lote_id):
        raise HTTPException(404, "Lote no encontrado")
    protegidos = servicio.protegidos_del_lote(lote_id)
    if protegidos and not incluir_protegidos:
        raise HTTPException(
            409,
            f"{protegidos} movimiento(s) de esta importacion los corregiste tu y se borrarian "
            "con ella. Confirma otra vez si igualmente quieres deshacerla.",
        )
    _copia_previa(f"deshacer la importacion #{lote_id}")
    borrados = servicio.deshacer(lote_id, incluir_protegidos=incluir_protegidos)
    # Borrar el lote es una orden tuya: sin esto, el aviso de copias diria que
    # desaparecieron miles de movimientos. Si no se puede anotar, no es motivo de error.
    try:
        respaldo.aceptar_perdida(settings.database_url, settings.carpeta_respaldos)
    except (ValueError, OSError):
        pass
    return {"borrados": borrados}


def _lote_out(l: ImportBatch) -> dict:
    return {
        "id": l.id,
        "filename": l.filename,
        "sheet": l.sheet,
        "rows_read": l.rows_read,
        "created_count": l.created_count,
        "duplicated_count": l.duplicated_count,
        "desde": l.date_from.isoformat() if l.date_from else None,
        "hasta": l.date_to.isoformat() if l.date_to else None,
        "created_at": l.created_at.isoformat(),
    }
