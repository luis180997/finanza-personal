"""Lo que el importador del Excel necesita de fuera, dicho como interfaces."""
from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol

from app.clasificacion.dominio.entidades import Category
from app.excel.dominio.entidades import ImportBatch
from app.movimientos.dominio.entidades import Account, Transaction


class Libro(Protocol):
    hojas: list[str]

    def filas(self, hoja: str) -> Iterator[tuple]: ...


class LectorDeLibro(Protocol):
    def abrir(self, contenido: bytes) -> Libro: ...


class RepositorioLotes(Protocol):
    def agregar(self, lote: ImportBatch) -> None: ...

    def obtener(self, lote_id: int) -> ImportBatch | None: ...

    def recientes(self) -> list[ImportBatch]: ...

    def borrar(self, lote: ImportBatch) -> None: ...


class CatalogoDeCategorias(Protocol):
    """Lo implementa el modulo de clasificacion."""

    def todas(self) -> dict[int, Category]: ...


class CatalogoDeCuentas(Protocol):
    """Lo implementa el modulo de movimientos."""

    def obtener(self, cuenta_id: int) -> Account | None: ...


class MovimientosDeLotes(Protocol):
    """Lo implementa el modulo de movimientos: son sus datos."""

    def existe_huella(self, huella: str) -> bool: ...

    def agregar_importado(self, tx: Transaction) -> None: ...

    def protegidos_del_lote(self, lote_id: int) -> int: ...

    def deshacer_lote(self, lote_id: int) -> int:
        """Borra los movimientos del lote y devuelve cuantos. Confirma."""
