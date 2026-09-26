"""Monta los casos de uso del importador del Excel con sus adaptadores."""
from __future__ import annotations

from sqlmodel import Session

from app.excel.adaptadores.salida.libro import LectorOpenpyxl
from app.excel.adaptadores.salida.sqlite import LotesSqlite
from app.excel.aplicacion.importacion import ServicioImportacion
from app.plataforma.db import UnidadDeTrabajoSqlite


def importacion(session: Session) -> ServicioImportacion:
    from app.clasificacion.adaptadores.salida.sqlite import CategoriasSqlite
    from app.movimientos.adaptadores import fabrica as movimientos
    from app.movimientos.adaptadores.salida.sqlite import CuentasSqlite

    return ServicioImportacion(
        lector=LectorOpenpyxl(),
        lotes=LotesSqlite(session),
        movimientos=movimientos.lotes(session),
        categorias=CategoriasSqlite(session),
        cuentas=CuentasSqlite(session),
        uow=UnidadDeTrabajoSqlite(session),
    )
