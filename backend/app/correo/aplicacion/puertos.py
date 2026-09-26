"""Lo que el modulo de correo necesita de fuera, dicho como interfaces."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from app.correo.dominio.correo import ParsedTx, RawEmail
from app.correo.dominio.entidades import EmailMessage, ParseStatus
from app.correo.dominio.parsers import PatternBundle
from app.movimientos.dominio.entidades import Account, Transaction


class FuenteNoConfigurada(RuntimeError):
    """El buzon no esta configurado (faltan credenciales). No es un fallo: se avisa."""


class FuenteDeCorreos(Protocol):
    """El buzon: IMAP o la API de Gmail, segun la configuracion."""

    canal: str          # "IMAP" | "Gmail", para los mensajes de error

    def descargar(self, dias: int, max_correos: int) -> tuple[list[RawEmail], str]:
        """(correos, descripcion de lo que se pidio). Lanza FuenteNoConfigurada."""


class CatalogoDePatrones(Protocol):
    def actual(self) -> PatternBundle: ...

    def recargar(self) -> PatternBundle: ...

    def leer(
        self, email: RawEmail, ignorar_remitente: bool = False,
    ) -> tuple[ParsedTx | None, str | None]: ...


class ArchivoDeCorreos(Protocol):
    def por_gmail_id(self, gmail_id: str) -> EmailMessage | None: ...

    def obtener(self, correo_id: int) -> EmailMessage | None: ...

    def listar(self, estado: ParseStatus | None, limite: int) -> list[EmailMessage]:
        """Del mas reciente al mas antiguo."""

    def sin_parser(self, limite: int) -> list[EmailMessage]: ...

    def con_cuerpo_antes_de(self, limite: datetime) -> list[EmailMessage]: ...

    def tiene_movimiento(self, correo_id: int) -> bool: ...

    def agregar(self, correo: EmailMessage) -> None: ...


class MemoriaDelTitular(Protocol):
    """El nombre completo del titular, aprendido de sus propios correos."""

    def leer(self) -> list[str]: ...

    def guardar(self, nombre: list[str]) -> None: ...


class EstadoDeSincronizacion(Protocol):
    def anotar(self, clave: str, valor: str) -> None: ...


class CuentasActivas(Protocol):
    """Lo implementa el modulo de movimientos."""

    def activas(self) -> list[Account]: ...


class Clasificador(Protocol):
    """Lo implementa el modulo de clasificacion."""

    def aplicar(self, tx: Transaction, contexto: dict | None = None) -> Any: ...


class RegistroDeMovimientos(Protocol):
    """Lo implementa el modulo de movimientos: la cadena antiduplicado."""

    def registrar(self, tx: Transaction) -> str: ...
