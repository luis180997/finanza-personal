"""Monta los casos de uso de clasificacion con sus adaptadores.

Es el unico sitio del modulo que sabe que implementacion va en cada puerto. Lo que
se necesita de otros modulos se pide a sus fabricas (dentro de cada funcion, para
no crear un ciclo de imports entre modulos que se usan mutuamente).
"""
from __future__ import annotations

from sqlmodel import Session

from app.clasificacion.adaptadores.salida.sqlite import CategoriasSqlite, MemoriaSqlite, ReglasSqlite
from app.clasificacion.aplicacion.catalogo import ServicioCatalogo
from app.clasificacion.aplicacion.clasificar import ServicioClasificacion
from app.plataforma.db import UnidadDeTrabajoSqlite


def clasificador(session: Session) -> ServicioClasificacion:
    return ServicioClasificacion(
        CategoriasSqlite(session), ReglasSqlite(session), MemoriaSqlite(session),
    )


def catalogo(session: Session) -> ServicioCatalogo:
    from app.analitica.adaptadores import fabrica as analitica
    from app.movimientos.adaptadores import fabrica as movimientos

    return ServicioCatalogo(
        categorias=CategoriasSqlite(session),
        reglas=ReglasSqlite(session),
        movimientos=movimientos.movimientos(session),
        topes=analitica.presupuestos(session),
        uow=UnidadDeTrabajoSqlite(session),
    )
