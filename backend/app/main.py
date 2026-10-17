"""Punto de entrada de la API y raiz de composicion.

La app esta hecha de modulos con arquitectura hexagonal (puertos y adaptadores):

    clasificacion  movimientos  correo  analitica  seguimiento  inversiones
    cada uno con dominio/ (reglas puras), aplicacion/ (casos de uso y puertos)
    y adaptadores/ (entrada: HTTP; salida: SQLite, IMAP/Gmail, Excel...)

    compartido/    lo que usan todos (dinero, fechas de corte, errores, reloj)
    plataforma/    configuracion, base de datos, respaldos, migraciones, arranque

Aqui solo se conectan las piezas: los routers de cada modulo, el arranque y el
programador. Las reglas de dependencia las vigila tests/test_arquitectura.py.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.analitica.adaptadores.entrada import http as analitica_http
from app.clasificacion.adaptadores.entrada import http as clasificacion_http
from app.compartido.errores import ErrorDeNegocio
from app.correo.adaptadores.entrada import http as correo_http
from app.inversiones.adaptadores.entrada import http as inversiones_http
from app.movimientos.adaptadores.entrada import http as movimientos_http
from app.plataforma import arranque, programador
from app.plataforma import http as plataforma_http
from app.plataforma.config import settings
from app.seguimiento.adaptadores.entrada import http as seguimiento_http

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
)
log = logging.getLogger("finanzas")


@asynccontextmanager
async def lifespan(app: FastAPI):
    arranque.preparar_base()
    planificador = programador.iniciar()
    yield
    if planificador:
        planificador.shutdown(wait=False)


app = FastAPI(
    title="Finanzas personales",
    description=(
        "Backend que lee las notificaciones bancarias de Gmail (BCP, Yape, BBVA), "
        "las convierte en movimientos clasificados y expone el resumen."
    ),
    version="0.1.0",
    lifespan=lifespan,
    # La documentacion interactiva va bajo /api para que nginx (unica puerta de
    # entrada en Docker) la sirva sin reglas extra.
    #
    # Con APP_ENV=prod se apaga entera. Mientras no haya login, /api/docs es un
    # panel que deja disparar cualquier endpoint a quien llegue a la URL; el dia
    # que esto salga del portatil, no debe estar publicado.
    docs_url="/api/docs" if settings.es_desarrollo else None,
    redoc_url="/api/redoc" if settings.es_desarrollo else None,
    openapi_url="/api/openapi.json" if settings.es_desarrollo else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ErrorDeNegocio)
async def _error_de_negocio(_: Request, exc: ErrorDeNegocio) -> JSONResponse:
    """Los casos de uso no conocen HTTP: aqui su error se vuelve la respuesta con
    su codigo, con el mismo formato que un HTTPException."""
    return JSONResponse(status_code=exc.estado_http, content={"detail": exc.mensaje})


def explicar_rechazo(exc: IntegrityError) -> str:
    """Por que la base rechazo el cambio, dicho para quien usa la app."""
    detalle = str(exc.orig)
    if detalle.startswith("Movimiento protegido"):
        return detalle                 # el del trigger (plataforma/db.py) ya lo explica
    if "FOREIGN KEY" in detalle:
        return (
            "No se pudo guardar: apunta a algo que no existe, o hay otros datos que "
            "todavia lo usan."
        )
    if "UNIQUE" in detalle:
        return "No se pudo guardar: ya existe un registro igual."
    return f"No se pudo guardar: la base de datos lo rechazo ({detalle})."


@app.exception_handler(IntegrityError)
async def _choque_con_otros_datos(_: Request, exc: IntegrityError) -> JSONResponse:
    """Red de seguridad. Un caso de uso que no comprobo antes una clave foranea o un
    valor repetido llegaba hasta la base, y la API respondia un 500 sin explicacion.
    Los casos conocidos tienen su propio mensaje en su caso de uso; esto cubre los
    que falten, y deja la causa en el log para poder anadir el suyo."""
    log.warning("la base rechazo un cambio: %s", exc.orig)
    return JSONResponse(status_code=409, content={"detail": explicar_rechazo(exc)})


for router in (
    clasificacion_http.router,
    movimientos_http.router,
    analitica_http.router,
    correo_http.router,
    plataforma_http.router,
    seguimiento_http.router,
    inversiones_http.router,
):
    app.include_router(router, prefix="/api")


@app.get("/api/salud", tags=["sistema"])
def salud():
    return {
        "estado": "ok",
        "entorno": settings.app_env,
        "moneda": settings.base_currency,
        "zona_horaria": settings.timezone,
    }
