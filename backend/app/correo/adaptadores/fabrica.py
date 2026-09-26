"""Monta los casos de uso de correo con sus adaptadores."""
from __future__ import annotations

from zoneinfo import ZoneInfo

from sqlmodel import Session

from app.correo.adaptadores.salida.buzon import BuzonSegunConfiguracion
from app.correo.adaptadores.salida.patrones import PatronesYaml
from app.correo.adaptadores.salida.sqlite import ArchivoSqlite, EstadoKv, TitularKv
from app.correo.aplicacion.sincronizacion import AjustesDeCorreo, ServicioSincronizacion
from app.plataforma.config import settings
from app.plataforma.db import UnidadDeTrabajoSqlite


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
