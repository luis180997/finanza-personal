"""Monta los casos de uso de inversiones con sus adaptadores."""
from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

from sqlmodel import Session

from app.inversiones.adaptadores.salida.alpaca import PreciosAlpaca
from app.inversiones.adaptadores.salida.buzon import BuzonImap
from app.inversiones.adaptadores.salida.pdf import LectorPdfplumber
from app.inversiones.adaptadores.salida.sqlite import InversionesSqlite
from app.inversiones.aplicacion.consultas import ServicioConsultas
from app.inversiones.aplicacion.correos import ServicioCorreosHapi
from app.inversiones.aplicacion.estados import ServicioEstados
from app.inversiones.aplicacion.precios import ServicioPrecios
from app.inversiones.aplicacion.revision import ServicioRevision
from app.plataforma.config import settings
from app.plataforma.db import UnidadDeTrabajoSqlite


# La app corre en un solo proceso (un worker, ver Dockerfile): basta un cerrojo en
# memoria para que la tarea programada, "Actualizar" e importar no escriban a la vez
# los mismos correos o precios (chocarian en las claves unicas).
_ESCRIBIENDO = threading.Lock()


@contextmanager
def en_exclusiva() -> Iterator[bool]:
    """True si se obtuvo el turno; False si ya habia otra escritura en curso."""
    libre = _ESCRIBIENDO.acquire(blocking=False)
    try:
        yield libre
    finally:
        if libre:
            _ESCRIBIENDO.release()


def _fuente_de_precios() -> PreciosAlpaca:
    return PreciosAlpaca(settings.alpaca_key_id, settings.alpaca_secret_key)


def revision() -> ServicioRevision:
    return ServicioRevision(lector=LectorPdfplumber())


def estados(session: Session) -> ServicioEstados:
    return ServicioEstados(LectorPdfplumber(), InversionesSqlite(session), UnidadDeTrabajoSqlite(session))


def correos(session: Session) -> ServicioCorreosHapi:
    return ServicioCorreosHapi(BuzonImap(), InversionesSqlite(session), UnidadDeTrabajoSqlite(session))


def precios(session: Session) -> ServicioPrecios:
    return ServicioPrecios(
        _fuente_de_precios(), InversionesSqlite(session), UnidadDeTrabajoSqlite(session),
        minutos=settings.precios_intervalo_minutos or 5,
    )


def consultas(session: Session) -> ServicioConsultas:
    return ServicioConsultas(
        InversionesSqlite(session),
        precios_configurados=_fuente_de_precios().configurada,
        correo_configurado=BuzonImap().configurado,
    )
