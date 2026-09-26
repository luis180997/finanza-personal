"""Lo que el modulo de seguimiento necesita de fuera, dicho como interfaces."""
from __future__ import annotations

from datetime import date
from typing import Any, Protocol

from app.seguimiento.dominio.entidades import SaldoCorte, SaldoCuenta


class RepositorioCortes(Protocol):
    def por_fecha(self) -> list[SaldoCorte]:
        """Todos, del mas antiguo al mas reciente."""

    def saldos_por_corte(self) -> dict[int, list[SaldoCuenta]]:
        """Los saldos de cada corte, en el orden del formulario."""

    def obtener(self, corte_id: int) -> SaldoCorte | None: ...

    def en_fecha(self, fecha: date, excluir_id: int | None = None) -> SaldoCorte | None: ...

    def fechas(self) -> set[date]: ...

    def saldos_de(self, corte_id: int) -> list[SaldoCuenta]: ...

    def agregar(self, fila: SaldoCorte | SaldoCuenta) -> None: ...

    def borrar(self, fila: SaldoCorte | SaldoCuenta) -> None: ...


class TotalesRegistrados(Protocol):
    """Lectura de los movimientos (modulo movimientos): lo registrado en un periodo."""

    def entre(self, desde_excluido: date, hasta: date) -> tuple[int, int]:
        """(ingresos, gastos) en centimos de la moneda base, sin duplicados ni ignorados."""


class LectorDeLibro(Protocol):
    def abrir(self, contenido: bytes) -> Any:
        """Un libro con `hojas` y `filas(hoja)`."""
