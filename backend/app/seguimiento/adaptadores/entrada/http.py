"""Rutas de Seguimiento: cortes de saldo real y su comparacion con lo registrado.
Solo traducen HTTP <-> caso de uso."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlmodel import Session
from starlette.concurrency import run_in_threadpool

from app.compartido.dinero import to_cents
from app.plataforma import respaldo
from app.plataforma.db import get_session
from app.seguimiento.adaptadores import fabrica
from app.seguimiento.adaptadores.entrada.esquemas import CorteIn
from app.seguimiento.aplicacion.cortes import ServicioSeguimiento
from app.seguimiento.dominio.conciliacion import Saldo, tipo_cambio_a_diezmil

router = APIRouter()

MAX_BYTES = 20 * 1024 * 1024
EXTENSIONES = (".xlsx", ".xlsm")


def _seguimiento(session: Session = Depends(get_session)) -> ServicioSeguimiento:
    return fabrica.seguimiento(session)


def _saldos(datos: CorteIn) -> list[Saldo]:
    return [Saldo(s.cuenta, s.moneda, s.es_deuda, to_cents(s.monto)) for s in datos.saldos]


def _tipo_cambio(datos: CorteIn) -> int:
    return tipo_cambio_a_diezmil(datos.tipo_cambio) if datos.tipo_cambio else 0


@router.get("/seguimiento", tags=["seguimiento"])
def ver(servicio: ServicioSeguimiento = Depends(_seguimiento)):
    return servicio.ver()


@router.post("/seguimiento/cortes", tags=["seguimiento"], status_code=201)
def crear(datos: CorteIn, servicio: ServicioSeguimiento = Depends(_seguimiento)):
    corte = servicio.crear(
        fecha=datos.fecha, tipo_cambio_diezmil=_tipo_cambio(datos),
        notas=datos.notas, saldos=_saldos(datos),
    )
    return {"id": corte.id}


@router.put("/seguimiento/cortes/{corte_id}", tags=["seguimiento"])
def editar(corte_id: int, datos: CorteIn, servicio: ServicioSeguimiento = Depends(_seguimiento)):
    corte = servicio.editar(
        corte_id, fecha=datos.fecha, tipo_cambio_diezmil=_tipo_cambio(datos),
        notas=datos.notas, saldos=_saldos(datos),
    )
    return {"id": corte.id}


@router.delete("/seguimiento/cortes/{corte_id}", tags=["seguimiento"], status_code=204)
def borrar(corte_id: int, servicio: ServicioSeguimiento = Depends(_seguimiento)):
    servicio.borrar(corte_id)


def _copia_previa() -> None:
    try:
        respaldo.copia_previa("importar el historial de saldos")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            503, f"No se pudo hacer la copia de seguridad previa, asi que no se toco nada: {exc}"
        ) from exc


@router.post("/seguimiento/importar", tags=["seguimiento"], status_code=201)
async def importar(
    archivo: UploadFile = File(...),
    hoja: str | None = Form(default=None),
    servicio: ServicioSeguimiento = Depends(_seguimiento),
):
    """Importa el historial de saldos de un Excel. Las fechas que ya existen no se
    tocan, asi que importar dos veces el mismo archivo no duplica nada."""
    if not archivo.filename or not archivo.filename.lower().endswith(EXTENSIONES):
        raise HTTPException(400, f"Formato no soportado. Se admite: {', '.join(EXTENSIONES)}")
    contenido = await archivo.read()
    if not contenido:
        raise HTTPException(400, "El archivo esta vacio")
    if len(contenido) > MAX_BYTES:
        raise HTTPException(413, "El archivo supera los 20 MB")
    try:
        lectura = servicio.leer_excel(contenido, hoja)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"No se pudo leer el archivo: {exc}") from exc

    await run_in_threadpool(_copia_previa)
    return servicio.importar(lectura)
