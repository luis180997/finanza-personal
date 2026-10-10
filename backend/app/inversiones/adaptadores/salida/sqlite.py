"""El repositorio de inversiones sobre SQLite."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import func
from sqlmodel import Session, col, select

from app.inversiones.aplicacion.puertos import Cierre
from app.inversiones.dominio.entidades import (
    CorreoHapiLeido, EstadoCuentaImportado, Operacion, PosicionCierre, PrecioDiario, PrecioIntradia,
)


class InversionesSqlite:
    def __init__(self, session: Session):
        self.session = session

    def agregar(self, entidad) -> None:
        self.session.add(entidad)

    def estados(self) -> list[EstadoCuentaImportado]:
        return list(self.session.exec(
            select(EstadoCuentaImportado).order_by(col(EstadoCuentaImportado.inicio))
        ).all())

    def posiciones_de(self, estado_cuenta_id: int) -> list[PosicionCierre]:
        return list(self.session.exec(
            select(PosicionCierre).where(PosicionCierre.estado_cuenta_id == estado_cuenta_id)
        ).all())

    def todas_las_posiciones(self) -> list[PosicionCierre]:
        return list(self.session.exec(select(PosicionCierre)).all())

    def operaciones(self) -> list[Operacion]:
        return list(self.session.exec(
            select(Operacion).order_by(col(Operacion.fecha), col(Operacion.id))
        ).all())

    def correo(self, message_id: str) -> CorreoHapiLeido | None:
        return self.session.exec(
            select(CorreoHapiLeido).where(CorreoHapiLeido.message_id == message_id)
        ).first()

    def correos_leidos(self, tipo: str, desde: datetime, hasta: datetime) -> list[CorreoHapiLeido]:
        return list(self.session.exec(
            select(CorreoHapiLeido)
            .where(CorreoHapiLeido.tipo == tipo)
            .where(CorreoHapiLeido.recibido_at >= desde, CorreoHapiLeido.recibido_at <= hasta)
            .order_by(col(CorreoHapiLeido.recibido_at))
        ).all())

    def correos_con_resultado(self, resultado: str) -> list[CorreoHapiLeido]:
        return list(self.session.exec(
            select(CorreoHapiLeido).where(CorreoHapiLeido.resultado == resultado)
        ).all())

    def ultimo_correo_at(self) -> datetime | None:
        return self.session.exec(select(func.max(CorreoHapiLeido.recibido_at))).first()

    def precios_diarios(self, simbolos: list[str] | None = None) -> list[PrecioDiario]:
        consulta = select(PrecioDiario)
        if simbolos is not None:
            consulta = consulta.where(col(PrecioDiario.simbolo).in_(simbolos))
        return list(self.session.exec(consulta.order_by(col(PrecioDiario.fecha))).all())

    def ultimas_fechas_de_precio(self) -> dict[str, date]:
        filas = self.session.exec(
            select(PrecioDiario.simbolo, func.max(PrecioDiario.fecha)).group_by(PrecioDiario.simbolo)
        ).all()
        return dict(filas)

    def cierre(self, simbolo: str, fecha: date) -> PrecioDiario | None:
        return self.session.exec(
            select(PrecioDiario).where(PrecioDiario.simbolo == simbolo, PrecioDiario.fecha == fecha)
        ).first()

    def guardar_cierre(self, simbolo: str, cierre: Cierre) -> None:
        existente = self.cierre(simbolo, cierre.fecha)
        fila = existente or PrecioDiario(simbolo=simbolo, fecha=cierre.fecha, cierre_micro=0,
                                         cierre_split_micro=0, cierre_total_micro=0)
        fila.cierre_micro = cierre.cierre_micro
        fila.cierre_split_micro = cierre.split_micro
        fila.cierre_total_micro = cierre.total_micro
        self.session.add(fila)

    def intradia(self, desde: datetime, simbolos: list[str] | None = None) -> list[PrecioIntradia]:
        consulta = select(PrecioIntradia).where(PrecioIntradia.momento >= desde)
        if simbolos is not None:
            consulta = consulta.where(col(PrecioIntradia.simbolo).in_(simbolos))
        return list(self.session.exec(consulta.order_by(col(PrecioIntradia.momento))).all())

    def momentos_intradia(self, simbolo: str, desde: datetime) -> set[datetime]:
        return set(self.session.exec(
            select(PrecioIntradia.momento)
            .where(PrecioIntradia.simbolo == simbolo, PrecioIntradia.momento >= desde)
        ).all())
