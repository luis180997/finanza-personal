"""Monta los casos de uso de seguimiento con sus adaptadores."""
from __future__ import annotations

from sqlmodel import Session

from app.plataforma.db import UnidadDeTrabajoSqlite
from app.seguimiento.adaptadores.salida.sqlite import CortesSqlite, RegistradoSqlite
from app.seguimiento.aplicacion.cortes import ServicioSeguimiento


def seguimiento(session: Session) -> ServicioSeguimiento:
    from app.excel.adaptadores.salida.libro import LectorOpenpyxl

    return ServicioSeguimiento(
        CortesSqlite(session), RegistradoSqlite(session), LectorOpenpyxl(),
        UnidadDeTrabajoSqlite(session),
    )
