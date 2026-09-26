"""Lo que el modulo de movimientos necesita de fuera, dicho como interfaces."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Protocol

from app.clasificacion.dominio.entidades import Category
from app.compartido.tipos import Direction, Necessity, Source, TxStatus
from app.movimientos.dominio.entidades import Account, Transaction, TransactionPapelera


@dataclass
class FiltrosMovimientos:
    desde: date | None = None
    hasta: date | None = None
    direccion: Direction | None = None
    estado: TxStatus | None = None
    cuenta_id: int | None = None
    categoria_id: int | None = None
    necesidad: Necessity | None = None
    origen: Source | None = None
    buscar: str | None = None


@dataclass
class PaginaDeMovimientos:
    items: list[Transaction]
    total: int
    suma_gastos_cents: int
    suma_ingresos_cents: int


class RepositorioMovimientos(Protocol):
    def obtener(self, tx_id: int) -> Transaction | None: ...

    def agregar(self, tx: Transaction) -> None: ...

    def borrar(self, tx: Transaction) -> None: ...

    def de_categoria(self, cat_id: int) -> list[Transaction]: ...

    def duplicados_de(self, tx_id: int) -> list[Transaction]:
        """Los que estan marcados como duplicado de `tx_id`."""

    def por_huella(self, huella: str) -> Transaction | None: ...

    def del_lote(self, lote_id: int) -> list[Transaction]: ...

    def protegidos_del_lote(self, lote_id: int) -> int: ...

    def duplicados_de_fuera_del_lote(self, lote_id: int) -> list[Transaction]:
        """Los de fuera del lote marcados como duplicado de una fila del lote."""

    def ids_por_huella(self, huellas: list[str]) -> dict[str, int]: ...

    def candidatos_mellizo(self, tx: Transaction) -> list[Transaction]:
        """Mismo importe, direccion, cuenta y minuto; sin contar los duplicados."""

    def candidatos_cruzados(self, tx: Transaction, ventana: timedelta) -> list[Transaction]:
        """Mismo importe y direccion en +-`ventana`; sin contar los duplicados."""

    def pagina(
        self, filtros: FiltrosMovimientos, pagina: int, tamano: int, orden: str,
    ) -> PaginaDeMovimientos: ...

    def por_revisar(self, limite: int) -> list[Transaction]: ...


class RepositorioCuentas(Protocol):
    def ordenadas(self) -> list[Account]: ...

    def todas(self) -> dict[int, Account]: ...

    def obtener(self, cuenta_id: int) -> Account | None: ...

    def por_nombre(self, nombre: str) -> Account | None: ...

    def efectivo(self) -> Account | None: ...

    def tiene_movimientos(self, cuenta_id: int) -> bool: ...

    def agregar(self, cuenta: Account) -> None: ...

    def borrar(self, cuenta: Account) -> None: ...


class RepositorioPapelera(Protocol):
    def ultimas(self, limite: int) -> list[TransactionPapelera]: ...

    def obtener(self, papelera_id: int) -> TransactionPapelera | None: ...

    def borrar(self, fila: TransactionPapelera) -> None: ...

    def decisiones_para(self, huella: str, email_id: int | None) -> TransactionPapelera | None:
        """La copia mas reciente, con decisiones tuyas, del movimiento con esa huella
        o de ese correo."""

    def referencias_rotas(self, tx: Transaction) -> list[str]:
        """Columnas de `tx` que apuntan a una fila que ya no existe."""


class CatalogoDeCategorias(Protocol):
    """Lo implementa el modulo de clasificacion."""

    def obtener(self, cat_id: int) -> Category | None: ...

    def todas(self) -> dict[int, Category]: ...


class Clasificador(Protocol):
    """Lo implementa el modulo de clasificacion."""

    def aplicar(self, tx: Transaction, contexto: dict | None = None) -> Any: ...
