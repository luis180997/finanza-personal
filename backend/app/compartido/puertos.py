"""Puertos que usan todos los modulos."""
from __future__ import annotations

from typing import Any, Protocol


class UnidadDeTrabajo(Protocol):
    """Cuando se confirman los cambios de un caso de uso.

    Los repositorios nunca confirman por su cuenta: lo decide el caso de uso, que
    es quien sabe cuando una operacion esta completa.
    """

    def confirmar(self) -> None: ...

    def deshacer(self) -> None: ...

    def volcar(self) -> None:
        """Manda a la base lo pendiente sin confirmarlo (para que los triggers y las
        claves foraneas vean el estado intermedio)."""

    def refrescar(self, entidad: Any) -> None: ...
