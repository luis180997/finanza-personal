"""Interruptores que necesita la interfaz y copias de seguridad."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException

from app.plataforma.config import settings
from app.plataforma import respaldo

router = APIRouter()


@router.get("/config", tags=["sistema"])
def config():
    """Lo que la interfaz tiene que saber para mostrar u ocultar secciones.

    Solo booleanos: ni rutas, ni credenciales, ni nada que no deba verse.
    """
    return {"importar_excel": settings.importar_excel_habilitado}


@router.get("/respaldos", tags=["sistema"])
def listar_respaldos():
    return respaldo.estado(
        settings.database_url, settings.carpeta_respaldos,
        settings.respaldo_cada_dias, settings.respaldo_conservar,
    )


@router.post("/respaldos", tags=["sistema"], status_code=201)
def crear_respaldo():
    """Respaldo inmediato, sin esperar a que toque. Tambien poda los viejos.

    Si el automatico esta a mitad, espera a que termine en vez de devolver error.
    """
    try:
        nuevo = respaldo.respaldar(
            settings.database_url, settings.carpeta_respaldos,
            settings.respaldo_conservar, forzar=True, esperar=True,
        )
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(400, str(exc)) from exc
    except (RuntimeError, OSError, sqlite3.Error) as exc:
        raise HTTPException(500, f"No se pudo crear la copia: {exc}") from exc
    if nuevo is None:
        raise HTTPException(409, "Ya hay un respaldo en curso. Prueba en unos segundos.")
    return nuevo.a_dict()


@router.post("/respaldos/aceptar-perdida", tags=["sistema"])
def aceptar_perdida():
    """"Lo borre a proposito": apaga el aviso de movimientos desaparecidos.

    No borra ninguna copia. Si despues desaparecen mas movimientos, el aviso vuelve.
    """
    try:
        respaldo.aceptar_perdida(settings.database_url, settings.carpeta_respaldos)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return listar_respaldos()
