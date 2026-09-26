"""Contrato comun de los parsers de correo."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Protocol


@dataclass(slots=True)
class RawEmail:
    """Correo ya aplanado a texto. Es lo unico que ve un parser."""

    gmail_id: str
    sender: str
    subject: str
    body: str
    received_at: datetime
    thread_id: str | None = None
    snippet: str = ""

    @property
    def haystack(self) -> str:
        return f"{self.subject}\n{self.body}"


@dataclass(slots=True)
class ParsedTx:
    """Resultado de un parser, aun sin categorizar ni persistir."""

    amount: Decimal
    direction: str                       # gasto | ingreso | transferencia
    currency: str = "PEN"
    occurred_at: datetime | None = None
    merchant_raw: str | None = None
    description: str | None = None
    operation_number: str | None = None
    account_hint: str | None = None      # nombre de cuenta sugerido
    payment_method: str | None = None    # efectivo | debito | credito | yape | plin | transferencia
    # Pista de categoria del propio parser. Es el ULTIMO recurso: solo se aplica
    # si ni tus reglas, ni la memoria de comercio, ni el diccionario supieron
    # clasificarlo. Asi una correccion tuya nunca queda pisada por el parser.
    category_hint: str | None = None
    last4: str | None = None
    bank: str | None = None
    parser: str = "desconocido"
    confidence: float = 0.8
    extra: dict = field(default_factory=dict)


class Parser(Protocol):
    id: str
    priority: int

    def matches(self, email: RawEmail) -> bool: ...

    def parse(self, email: RawEmail) -> ParsedTx | None: ...
