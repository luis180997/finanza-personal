"""Monta los casos de uso de correo con sus adaptadores."""
from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from zoneinfo import ZoneInfo

from sqlmodel import Session

from app.correo.adaptadores.salida.buzon import BuzonSegunConfiguracion
from app.correo.adaptadores.salida.patrones import PatronesYaml
from app.correo.adaptadores.salida.sqlite import ArchivoSqlite, EstadoKv, TitularKv
from app.correo.aplicacion.sincronizacion import AjustesDeCorreo, ServicioSincronizacion
from app.plataforma.config import settings
from app.plataforma.db import UnidadDeTrabajoSqlite

# La app corre en un solo proceso (un worker, ver Dockerfile): basta un cerrojo en
# memoria. Sin el, pulsar "Sincronizar" mientras corria la automatica leia los mismos
# correos a la vez: chocaban en las claves unicas y uno de los dos acababa anotando
# "es el mismo que ya trajo otro correo" en un correo que no lo era.
_LEYENDO = threading.Lock()


@contextmanager
def en_exclusiva() -> Iterator[bool]:
    """True si se obtuvo el turno; False si ya habia otra lectura del correo en curso."""
    libre = _LEYENDO.acquire(blocking=False)
    try:
        yield libre
    finally:
        if libre:
            _LEYENDO.release()


def patrones() -> PatronesYaml:
    return PatronesYaml()


def sincronizador(session: Session) -> ServicioSincronizacion:
    from app.clasificacion.adaptadores import fabrica as clasificacion
    from app.movimientos.adaptadores import fabrica as movimientos
    from app.movimientos.adaptadores.salida.sqlite import CuentasSqlite

    return ServicioSincronizacion(
        archivo=ArchivoSqlite(session),
        fuente=BuzonSegunConfiguracion(),
        patrones=patrones(),
        cuentas=CuentasSqlite(session),
        titular=TitularKv(session),
        estado=EstadoKv(session),
        clasificador=clasificacion.clasificador(session),
        registro=movimientos.registro(session),
        uow=UnidadDeTrabajoSqlite(session),
        ajustes=AjustesDeCorreo(
            zona=ZoneInfo(settings.timezone),
            moneda_base=settings.base_currency,
            dias_por_defecto=settings.gmail_lookback_days,
            retencion_dias=settings.email_retention_days,
        ),
    )
