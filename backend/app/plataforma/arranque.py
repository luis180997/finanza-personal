"""Lo que pasa al arrancar, antes de atender la primera peticion."""
from __future__ import annotations

import logging

from sqlmodel import Session

from app.plataforma import migraciones, respaldo
from app.plataforma.config import settings
from app.plataforma.db import cambios_pendientes, engine, init_db
from app.plataforma.semilla import seed

log = logging.getLogger("finanzas")


def _respaldo_previo_a_cambios() -> None:
    """Copia de la base ANTES de que el arranque la toque.

    Cubre todo lo que el arranque cambia: columnas nuevas, tablas retiradas (que se
    borran) y migraciones de datos. Antes la copia se hacia despues de `init_db`,
    con las columnas ya anadidas y las tablas ya borradas, y ni siquiera se hacia
    con RESPALDO_CADA_DIAS=0. Ahora va siempre que haya algo pendiente, y si falla
    la app no arranca: es preferible un error visible a cambiar la base sin red.
    """
    origen = respaldo.ruta_sqlite(settings.database_url)
    if origen is None or not origen.is_file():
        return                      # base nueva: todavia no hay nada que proteger
    pendientes = cambios_pendientes()
    if not pendientes:
        return
    nuevo = respaldo.respaldar(
        settings.database_url, settings.carpeta_respaldos,
        settings.respaldo_conservar, forzar=True, esperar=True,
    )
    if nuevo is None:
        raise RuntimeError("No se pudo hacer la copia previa: habia otro respaldo en curso.")
    log.info("respaldo previo a %s: %s", ", ".join(pendientes), nuevo.ruta.name)


def preparar_base() -> None:
    """Respaldo si hace falta, esquema, migraciones de datos y semilla, en ese orden."""
    _respaldo_previo_a_cambios()
    init_db()
    with Session(engine) as session:
        # Primero las migraciones de datos (la copia ya esta hecha): la semilla ya
        # conoce la taxonomia nueva.
        migraciones.aplicar(session)
        creado = seed(session)
        if any(creado.values()):
            log.info("datos iniciales: %s", creado)
