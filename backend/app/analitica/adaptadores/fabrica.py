"""Monta los casos de uso de analitica con sus adaptadores."""
from __future__ import annotations

from sqlmodel import Session

from app.analitica.adaptadores.salida.sqlite import MetaKv, MovimientosQueCuentan, TopesSqlite
from app.analitica.aplicacion.presupuestos import ServicioPresupuestos
from app.analitica.aplicacion.resumen import ServicioAnalitica
from app.plataforma.db import UnidadDeTrabajoSqlite


def analitica(session: Session) -> ServicioAnalitica:
    from app.clasificacion.adaptadores.salida.sqlite import CategoriasSqlite
    from app.movimientos.adaptadores.salida.sqlite import CuentasSqlite

    return ServicioAnalitica(
        datos=MovimientosQueCuentan(session),
        categorias=CategoriasSqlite(session),
        cuentas=CuentasSqlite(session),
        topes=TopesSqlite(session),
        meta=MetaKv(session),
    )


def presupuestos(session: Session) -> ServicioPresupuestos:
    from app.clasificacion.adaptadores.salida.sqlite import CategoriasSqlite

    return ServicioPresupuestos(
        TopesSqlite(session), UnidadDeTrabajoSqlite(session),
        categorias=CategoriasSqlite(session), meta=MetaKv(session),
    )
