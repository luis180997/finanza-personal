"""El programador: el otro adaptador de entrada, ademas de la API.

Lanza, sin que nadie pulse nada, los mismos casos de uso que la interfaz: la
sincronizacion del correo y el respaldo de la base.
"""
from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlmodel import Session

from app.plataforma.config import settings
from app.plataforma.db import engine

log = logging.getLogger("finanzas")


def _sincronizar_correo() -> None:
    from app.correo.adaptadores import fabrica as correo

    with Session(engine) as s:
        r = correo.sincronizador(s).sincronizar()
        log.info(
            "sync automatica: %s correos, %s movimientos nuevos",
            r.correos_leidos, r.transacciones_creadas,
        )


def iniciar():
    """Arranca las tareas que esten encendidas. Devuelve el planificador, o None."""
    from apscheduler.schedulers.background import BackgroundScheduler

    planificador = BackgroundScheduler(timezone=settings.timezone)

    if settings.sync_interval_minutes > 0:
        planificador.add_job(_sincronizar_correo, "interval",
                             minutes=settings.sync_interval_minutes,
                             id="sync_gmail", max_instances=1, coalesce=True)
        log.info("sincronizacion automatica cada %s min", settings.sync_interval_minutes)

    if settings.respaldo_cada_dias > 0:
        from app.plataforma import respaldo

        # Lo que decide es la FECHA del ultimo respaldo, no una hora: se comprueba
        # nada mas arrancar (en segundo plano, sin retrasar el arranque) y luego
        # cada hora. Comprobar es listar una carpeta; copiar solo cuando toca.
        planificador.add_job(
            respaldo.tarea_programada, "interval", hours=1, id="respaldo",
            next_run_time=datetime.now(ZoneInfo(settings.timezone)),
            max_instances=1, coalesce=True,
        )
        log.info(
            "respaldo automatico cada %s dia(s) en %s (se conservan %s)",
            settings.respaldo_cada_dias, settings.carpeta_respaldos,
            settings.respaldo_conservar or "todos",
        )

    if not planificador.get_jobs():
        return None
    planificador.start()
    return planificador
