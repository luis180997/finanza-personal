"""Monta los casos de uso de movimientos con sus adaptadores.

Es el unico sitio del modulo que sabe que implementacion va en cada puerto. Lo que
se necesita de otros modulos se pide a sus fabricas (dentro de cada funcion, para
no crear un ciclo de imports entre modulos que se usan mutuamente).
"""
from __future__ import annotations

from zoneinfo import ZoneInfo

from sqlmodel import Session

from app.movimientos.adaptadores.salida.sqlite import (
    CuentasSqlite,
    MovimientosSqlite,
    PapeleraSqlite,
)
from app.movimientos.aplicacion.cuentas import ServicioCuentas
from app.movimientos.aplicacion.lotes import ServicioLotes
from app.movimientos.aplicacion.movimientos import ServicioMovimientos
from app.movimientos.aplicacion.papelera import ServicioPapelera
from app.movimientos.aplicacion.registro import RegistroDeMovimientos
from app.plataforma.config import settings
from app.plataforma.db import UnidadDeTrabajoSqlite


def movimientos(session: Session) -> ServicioMovimientos:
    from app.clasificacion.adaptadores import fabrica as clasificacion
    from app.clasificacion.adaptadores.salida.sqlite import CategoriasSqlite

    return ServicioMovimientos(
        repo=MovimientosSqlite(session),
        cuentas=CuentasSqlite(session),
        categorias=CategoriasSqlite(session),
        clasificador=clasificacion.clasificador(session),
        uow=UnidadDeTrabajoSqlite(session),
        zona=ZoneInfo(settings.timezone),
    )


def cuentas(session: Session) -> ServicioCuentas:
    return ServicioCuentas(CuentasSqlite(session), UnidadDeTrabajoSqlite(session))


def papelera(session: Session) -> ServicioPapelera:
    return ServicioPapelera(
        PapeleraSqlite(session), MovimientosSqlite(session), UnidadDeTrabajoSqlite(session),
    )


def lotes(session: Session) -> ServicioLotes:
    return ServicioLotes(MovimientosSqlite(session), UnidadDeTrabajoSqlite(session))


def registro(session: Session) -> RegistroDeMovimientos:
    return RegistroDeMovimientos(
        MovimientosSqlite(session), papelera(session), UnidadDeTrabajoSqlite(session),
    )


def confianza_del_parser(parser_id: str) -> float | None:
    """Lo seguro que declara un parser al leer el correo (catalogo del modulo correo)."""
    from app.correo.adaptadores.salida.patrones import confianza_del_parser as del_catalogo

    return del_catalogo(parser_id)
