"""Rutas de Inversiones. Solo traducen HTTP <-> caso de uso."""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlmodel import Session
from starlette.concurrency import run_in_threadpool

from app.inversiones.adaptadores import fabrica
from app.inversiones.aplicacion.consultas import ServicioConsultas
from app.inversiones.aplicacion.estados import ResultadoImportacion
from app.plataforma import respaldo
from app.plataforma.db import get_session

router = APIRouter()

MAX_BYTES = 20 * 1024 * 1024
MAX_ARCHIVOS = 120
RANGOS = ("1D", "1S", "1M", "3M", "6M", "YTD", "1A", "TODO")


def _consultas(session: Session = Depends(get_session)) -> ServicioConsultas:
    return fabrica.consultas(session)


@router.get("/inversiones/resumen", tags=["inversiones"])
def resumen(servicio: ServicioConsultas = Depends(_consultas)):
    return servicio.resumen()


@router.get("/inversiones/posiciones", tags=["inversiones"])
def posiciones(servicio: ServicioConsultas = Depends(_consultas)):
    return servicio.posiciones()


@router.get("/inversiones/serie", tags=["inversiones"])
def serie(rango: str = Query("1A", pattern="^(" + "|".join(RANGOS) + ")$"),
          servicio: ServicioConsultas = Depends(_consultas)):
    return servicio.serie(rango)


@router.get("/inversiones/rentabilidad", tags=["inversiones"])
def rentabilidad(servicio: ServicioConsultas = Depends(_consultas)):
    return servicio.rentabilidad()


@router.get("/inversiones/dividendos", tags=["inversiones"])
def dividendos(servicio: ServicioConsultas = Depends(_consultas)):
    return servicio.dividendos()


@router.get("/inversiones/operaciones", tags=["inversiones"])
def operaciones(simbolo: str | None = None, estado: str | None = None,
                servicio: ServicioConsultas = Depends(_consultas)):
    return servicio.operaciones(simbolo, estado)


@router.get("/inversiones/acciones/{simbolo}", tags=["inversiones"])
def accion(simbolo: str, servicio: ServicioConsultas = Depends(_consultas)):
    datos = servicio.accion(simbolo.upper())
    if not datos:
        raise HTTPException(404, f"No hay operaciones de {simbolo}")
    return datos


@router.get("/inversiones/acciones/{simbolo}/precios", tags=["inversiones"])
def precios_de(simbolo: str, rango: str = Query("1A", pattern="^(" + "|".join(RANGOS) + ")$"),
               servicio: ServicioConsultas = Depends(_consultas)):
    return servicio.precios_de(simbolo.upper(), rango)


@router.get("/inversiones/estados", tags=["inversiones"])
def estados(servicio: ServicioConsultas = Depends(_consultas)):
    return servicio.estados_importados()


async def _leer_pdfs(archivos: list[UploadFile]) -> list[tuple[str, bytes]]:
    if not archivos:
        raise HTTPException(400, "No llego ningun archivo")
    if len(archivos) > MAX_ARCHIVOS:
        raise HTTPException(400, f"Como maximo {MAX_ARCHIVOS} archivos a la vez")
    leidos = []
    for archivo in archivos:
        nombre = archivo.filename or "sin-nombre.pdf"
        if not nombre.lower().endswith(".pdf"):
            raise HTTPException(400, f"{nombre}: solo se admiten PDF")
        contenido = await archivo.read()
        if not contenido:
            raise HTTPException(400, f"{nombre}: el archivo esta vacio")
        if len(contenido) > MAX_BYTES:
            raise HTTPException(413, f"{nombre}: supera los 20 MB")
        leidos.append((nombre, contenido))
    return leidos


def _a_dict(r: ResultadoImportacion) -> dict:
    documentos = []
    for d in r.documentos:
        fila = asdict(d)
        if d.comparacion is not None:
            c = d.comparacion
            fila["comparacion"] = {
                "seguido_por_correo": c.seguido_por_correo,
                "efectivo": c.efectivo_cents / 100,
                "total": c.total_cents / 100,
                "acciones": [
                    {"simbolo": x.simbolo, "segun_app": x.segun_app_micro / 1e6,
                     "segun_estado": x.segun_estado_micro / 1e6, "valor": x.valor_cents / 100}
                    for x in c.acciones
                ],
            }
        documentos.append(fila)
    return {"documentos": documentos, "errores": r.errores, "confirmado": r.confirmado,
            "importables": r.importables}


_OCUPADO = "Ya hay una actualizacion de inversiones en curso. Vuelve a intentarlo en unos segundos."


@router.post("/inversiones/estados/previsualizar", tags=["inversiones"])
async def previsualizar(archivos: list[UploadFile] = File(...),
                        session: Session = Depends(get_session)):
    """Lee, valida y concilia los estados sin guardar nada: lo que se ve es lo que se importaria."""
    documentos = await _leer_pdfs(archivos)
    with fabrica.en_exclusiva() as libre:
        if not libre:
            raise HTTPException(409, _OCUPADO)
        resultado = await run_in_threadpool(fabrica.estados(session).previsualizar, documentos)
    return _a_dict(resultado)


def _copia_previa() -> None:
    try:
        respaldo.copia_previa("importar estados de cuenta de Hapi")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            503, f"No se pudo hacer la copia de seguridad previa, asi que no se toco nada: {exc}"
        ) from exc


@router.post("/inversiones/estados", tags=["inversiones"], status_code=201)
async def importar(archivos: list[UploadFile] = File(...), session: Session = Depends(get_session)):
    """Importa los estados nuevos. Los ya importados se saltan; si uno no cuadra, no entra ninguno."""
    documentos = await _leer_pdfs(archivos)
    with fabrica.en_exclusiva() as libre:
        if not libre:
            raise HTTPException(409, _OCUPADO)
        await run_in_threadpool(_copia_previa)
        resultado = await run_in_threadpool(fabrica.estados(session).importar, documentos)
    return _a_dict(resultado)


@router.post("/inversiones/sincronizar", tags=["inversiones"])
def sincronizar(session: Session = Depends(get_session)):
    """Lee ya los correos de Hapi y actualiza los precios, sin esperar a la tarea programada."""
    with fabrica.en_exclusiva() as libre:
        if not libre:
            raise HTTPException(409, _OCUPADO)
        correos = fabrica.correos(session).sincronizar()
        precios = fabrica.precios(session).actualizar()
    return {"correos": asdict(correos), "precios": asdict(precios)}
