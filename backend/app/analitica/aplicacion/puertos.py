"""Lo que el modulo de analitica necesita de fuera, dicho como interfaces."""
from __future__ import annotations

from datetime import date
from typing import Protocol

from app.analitica.dominio.entidades import Budget
from app.analitica.dominio.periodos import Rango
from app.clasificacion.dominio.entidades import Category
from app.movimientos.dominio.entidades import Account, Transaction


class DatosDeMovimientos(Protocol):
    """Lectura de los movimientos: la analitica solo consulta, nunca escribe."""

    def que_cuentan(self, rango: Rango) -> list[Transaction]:
        """Los del rango que cuentan en los totales (ni duplicados ni ignorados)."""

    def primera_y_ultima_fecha(self) -> tuple[date | None, date | None]: ...

    def cuantos_por_revisar(self) -> int: ...


class CatalogoDeCategorias(Protocol):
    """Lo implementa el modulo de clasificacion."""

    def todas(self) -> dict[int, Category]: ...

    def obtener(self, cat_id: int) -> Category | None: ...


class CatalogoDeCuentas(Protocol):
    """Lo implementa el modulo de movimientos."""

    def todas(self) -> dict[int, Account]: ...


class RepositorioTopes(Protocol):
    def activos(self) -> list[Budget]: ...

    def todos(self) -> list[Budget]: ...

    def obtener(self, tope_id: int) -> Budget | None: ...

    def de_categoria(self, cat_id: int) -> list[Budget]: ...

    def existe_para(self, cat_id: int) -> bool: ...

    def agregar(self, tope: Budget) -> None: ...

    def borrar(self, tope: Budget) -> None: ...


class MetaDeAhorro(Protocol):
    def leer(self) -> str | None:
        """El valor guardado tal cual (centimos en texto), o None."""

    def guardar(self, cents: int) -> None: ...
