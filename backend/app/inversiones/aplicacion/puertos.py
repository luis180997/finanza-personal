"""Lo que el modulo de inversiones necesita de fuera, dicho como interfaces."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from app.inversiones.dominio.correo_hapi import CorreoHapi
from app.inversiones.dominio.entidades import (
    CorreoHapiLeido, EstadoCuentaImportado, Operacion, PosicionCierre, PrecioDiario, PrecioIntradia,
)
from app.inversiones.dominio.estado_cuenta import Pagina


class LectorDePdf(Protocol):
    def paginas(self, contenido: bytes) -> list[Pagina]:
        """Las paginas del PDF como lineas de palabras con su posicion horizontal."""


class BuzonHapi(Protocol):
    @property
    def configurado(self) -> bool: ...

    def correos(self, desde: date) -> list[CorreoHapi]:
        """Los correos de Hapi recibidos desde esa fecha. Solo lectura."""


@dataclass(frozen=True)
class Cierre:
    fecha: date
    cierre_micro: int          # tal cual
    split_micro: int           # ajustado por splits
    total_micro: int           # ajustado por splits y dividendos


class ErrorDePrecios(RuntimeError):
    """El proveedor de precios no respondio o rechazo la consulta."""


class FuenteDePrecios(Protocol):
    @property
    def configurada(self) -> bool: ...

    def cierres(self, simbolos: list[str], desde: date, hasta: date) -> dict[str, list[Cierre]]: ...

    def barras(self, simbolos: list[str], desde: datetime,
               minutos: int) -> dict[str, list[tuple[datetime, int]]]:
        """Barras de `minutos` desde `desde` (con zona): (momento UTC, cierre en micro)."""


class RepositorioInversiones(Protocol):
    """Los datos de inversiones. Nunca confirma: lo decide el caso de uso."""

    def agregar(self, entidad) -> None: ...

    def estados(self) -> list[EstadoCuentaImportado]: ...

    def posiciones_de(self, estado_cuenta_id: int) -> list[PosicionCierre]: ...

    def todas_las_posiciones(self) -> list[PosicionCierre]: ...

    def operaciones(self) -> list[Operacion]: ...

    def correo(self, message_id: str) -> CorreoHapiLeido | None: ...

    def correos_leidos(self, tipo: str, desde: datetime, hasta: datetime) -> list[CorreoHapiLeido]: ...

    def correos_con_resultado(self, resultado: str) -> list[CorreoHapiLeido]: ...

    def ultimo_correo_at(self) -> datetime | None: ...

    def precios_diarios(self, simbolos: list[str] | None = None) -> list[PrecioDiario]: ...

    def ultimas_fechas_de_precio(self) -> dict[str, date]: ...

    def cierre(self, simbolo: str, fecha: date) -> PrecioDiario | None: ...

    def guardar_cierre(self, simbolo: str, cierre: Cierre) -> None: ...

    def intradia(self, desde: datetime, simbolos: list[str] | None = None) -> list[PrecioIntradia]: ...

    def momentos_intradia(self, simbolo: str, desde: datetime) -> set[datetime]: ...
