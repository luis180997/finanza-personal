"""Lo que el modulo de clasificacion necesita de fuera, dicho como interfaces.

Los implementan los adaptadores (adaptadores/salida/sqlite.py) y, cuando lo que
se necesita es de otro modulo, el servicio de ese modulo (adaptadores/fabrica.py).
"""
from __future__ import annotations

from typing import Protocol

from app.clasificacion.dominio.entidades import Category, Rule
from app.compartido.tipos import Necessity


class CatalogoCategorias(Protocol):
    def ordenadas(self) -> list[Category]:
        """Todas, por `sort` y nombre: el orden en que las muestra la interfaz."""

    def todas(self) -> dict[int, Category]: ...

    def obtener(self, cat_id: int) -> Category | None: ...

    def por_nombre(self, nombre: str) -> Category | None: ...

    def en_nivel(self, nombre: str, parent_id: int | None) -> Category | None:
        """La que se llama asi y cuelga de `parent_id` (None = de la raiz)."""

    def hijas(self, cat_id: int) -> list[Category]: ...

    def agregar(self, cat: Category) -> None: ...

    def borrar(self, cat: Category) -> None: ...


class RepositorioReglas(Protocol):
    def activas_por_prioridad(self) -> list[Rule]: ...

    def por_prioridad(self) -> list[Rule]: ...

    def obtener(self, regla_id: int) -> Rule | None: ...

    def que_apuntan_a(self, cat_id: int) -> list[Rule]: ...

    def registrar_acierto(self, regla: Rule) -> None: ...

    def agregar(self, regla: Rule) -> None: ...

    def borrar(self, regla: Rule) -> None: ...


class MemoriaDeComercios(Protocol):
    def mas_usada(
        self, comercio: str, excluir_id: int | None,
    ) -> tuple[int, Necessity | None, int] | None:
        """(categoria, necesidad, veces) que mas elegiste para ese comercio."""


class MovimientosDeCategoria(Protocol):
    """Lo implementa el modulo de movimientos: son sus datos."""

    def protegidos_en_categoria(self, cat_id: int) -> int: ...

    def soltar_categoria(self, cat_id: int, destino_id: int | None) -> None: ...


class TopesDeCategoria(Protocol):
    """Lo implementa el modulo de analitica (presupuestos)."""

    def reasignar_topes(self, cat_id: int, destino_id: int | None) -> None: ...
