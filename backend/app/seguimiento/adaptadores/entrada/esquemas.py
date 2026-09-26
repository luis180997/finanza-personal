"""Contratos HTTP de Seguimiento (cortes de saldo)."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field, field_validator, model_validator

from app.compartido.corte import ANIO_MAX, ANIO_MIN


class SaldoCuentaIn(BaseModel):
    cuenta: str = Field(min_length=1, max_length=60)
    moneda: str = "PEN"
    es_deuda: bool = False
    monto: float = Field(ge=0, lt=1_000_000_000, description="Saldo en la moneda de la cuenta")

    @field_validator("cuenta")
    @classmethod
    def _cuenta(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("la cuenta necesita un nombre")
        return v

    @field_validator("moneda")
    @classmethod
    def _moneda(cls, v: str) -> str:
        v = (v or "").strip().upper()
        if v not in ("PEN", "USD"):
            raise ValueError("la moneda tiene que ser PEN o USD")
        return v


class CorteIn(BaseModel):
    """Un corte de saldo: cuanto habia en cada cuenta en una fecha."""

    fecha: date
    tipo_cambio: float | None = Field(default=None, gt=0, lt=100, description="Soles por dolar")
    notas: str | None = None
    saldos: list[SaldoCuentaIn] = Field(min_length=1)

    @field_validator("fecha")
    @classmethod
    def _fecha(cls, v: date) -> date:
        if not ANIO_MIN <= v.year <= ANIO_MAX:
            raise ValueError(f"la fecha tiene que estar entre los años {ANIO_MIN} y {ANIO_MAX}")
        return v

    @model_validator(mode="after")
    def _coherente(self) -> "CorteIn":
        vistas: set[tuple[str, str]] = set()
        for s in self.saldos:
            clave = (s.cuenta.lower(), s.moneda)
            if clave in vistas:
                raise ValueError(f"la cuenta {s.cuenta} ({s.moneda}) esta repetida")
            vistas.add(clave)
        if any(s.moneda == "USD" for s in self.saldos) and not self.tipo_cambio:
            raise ValueError("hay saldos en dolares: falta el tipo de cambio")
        return self
