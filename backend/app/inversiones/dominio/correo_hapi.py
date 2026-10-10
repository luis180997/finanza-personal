"""Lector de los correos de Hapi (no-reply@hapi.trade).

Son la fuente en tiempo real: cada orden ejecutada, dividendo, deposito y retiro
llega por correo al momento. El estado de cuenta del mes los confirma despues.

El correo es una tabla HTML: al pasarlo a texto, cada etiqueta y su valor quedan
en lineas distintas ("Ticker:" / "VOO"). Se colapsan los espacios y se lee
`Etiqueta: valor`. Las etiquetas cambiaron con los anios (2022: "Comprar/Vender",
"Acciónes", "Comisión"; despues: "Compra/Venta", "Acciones", "Fee de Apex") y se
aceptan ambas.

LO QUE HAY QUE SABER (comprobado contra todos los correos de Hapi del usuario):

- **El correo no trae la hora de ejecucion.** La da la cabecera Date: llega a los
  pocos segundos de ejecutarse una orden de mercado.
- **"Venta total" es el importe tambien en las compras.** En las compras incluye
  la comision; en las ventas el estado de cuenta descuenta ademas unos centavos de
  tasas regulatorias que el correo no muestra. El importe oficial es el del estado.
- **Hapi a veces repite el correo de una ejecucion** (tres correos identicos por
  una sola compra). Este modulo solo lee; quitar los repetidos es cosa de quien los
  junta (`aplicacion/correos.py`).
- **Las criptomonedas se ignoran** (tickers como ETHUSD): no las custodia Apex y
  la seccion de inversiones no las muestra.
"""
from __future__ import annotations

import enum
import hashlib
import pathlib
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.compartido.comercio import strip_accents

REMITENTE = "no-reply@hapi.trade"
# Huella de este lector: cambia sola con cualquier cambio del archivo. Un correo que
# no se pudo leer se reintenta cuando el lector es otro, no en cada lectura.
VERSION_LECTOR = hashlib.sha1(pathlib.Path(__file__).read_bytes()).hexdigest()[:10]


class TipoCorreo(str, enum.Enum):
    ejecutada = "ejecutada"
    colocada = "colocada"
    cancelada = "cancelada"
    dividendo = "dividendo"
    solicitud_deposito = "solicitud_deposito"
    deposito_completado = "deposito_completado"
    fondos_agregados = "fondos_agregados"
    retiro = "retiro"
    ignorado = "ignorado"         # codigos, contrasenas, publicidad, cripto


@dataclass(frozen=True)
class CorreoHapi:
    message_id: str
    recibido: datetime            # con zona horaria
    asunto: str
    cuerpo: str


@dataclass(frozen=True)
class EventoHapi:
    tipo: TipoCorreo
    message_id: str
    recibido: datetime
    ticker: str | None = None
    lado: str | None = None               # "compra" | "venta"
    tipo_orden: str | None = None
    cantidad: Decimal | None = None
    precio: Decimal | None = None
    total: Decimal | None = None          # importe de la orden, comision incluida
    comision: Decimal | None = None
    monto: Decimal | None = None          # dividendo neto / deposito recibido / retiro
    monto_pagado: Decimal | None = None   # lo que sale del banco al depositar
    moneda_pagada: str | None = None
    costo: Decimal | None = None          # costo del retiro
    fecha_pago: date | None = None        # dividendo
    motivo: str | None = None             # por que se ignora

    @property
    def es_cripto(self) -> bool:
        return es_cripto(self.ticker)


class CorreoIlegible(ValueError):
    """Un correo de un tipo conocido al que le falta un dato imprescindible."""


def _plano(texto: str) -> str:
    return re.sub(r"\s+", " ", strip_accents(texto)).strip()


def es_cripto(ticker: str | None) -> bool:
    return bool(ticker) and len(ticker) >= 6 and ticker.endswith("USD")


def tipo_de(asunto: str) -> TipoCorreo:
    a = _plano(asunto).lower()
    if "orden ejecutada" in a:
        return TipoCorreo.ejecutada
    if "orden colocada" in a or "ha sido colocada" in a:
        return TipoCorreo.colocada
    if "orden cancelada" in a:
        return TipoCorreo.cancelada
    if re.search(r"dividendo de \S+ recibido", a):
        return TipoCorreo.dividendo
    if "solicitud de deposito" in a:
        return TipoCorreo.solicitud_deposito
    if "deposito completado" in a:
        return TipoCorreo.deposito_completado
    if "fondos agregados" in a:
        return TipoCorreo.fondos_agregados
    if "solicitud de retiro" in a:
        return TipoCorreo.retiro
    return TipoCorreo.ignorado


_NUMERO = r"(-?[\d,]*\.?\d+)"


def _campo(texto: str, etiqueta: str, valor: str = r"(\S+)") -> str | None:
    m = re.search(rf"(?:{etiqueta})\s*:\s*{valor}", texto, re.IGNORECASE)
    return m.group(1) if m else None


def _decimal(valor: str | None) -> Decimal | None:
    if valor is None:
        return None
    try:
        return Decimal(valor.replace(",", ""))
    except InvalidOperation:
        return None


def _exigir(evento_campos: dict, *nombres: str) -> None:
    faltan = [n for n in nombres if evento_campos.get(n) is None]
    if faltan:
        raise CorreoIlegible(f"faltan {', '.join(faltan)}")


def leer(correo: CorreoHapi) -> EventoHapi:
    """Convierte un correo en un evento. CorreoIlegible si falta un dato clave."""
    tipo = tipo_de(correo.asunto)
    base = {"tipo": tipo, "message_id": correo.message_id, "recibido": correo.recibido}
    if tipo is TipoCorreo.ignorado:
        return EventoHapi(**base, motivo="no es una operacion")

    texto = _plano(correo.cuerpo)
    if tipo in (TipoCorreo.ejecutada, TipoCorreo.colocada, TipoCorreo.cancelada):
        campos = _orden(texto)
        if es_cripto(campos.get("ticker")):
            return EventoHapi(**{**base, "tipo": TipoCorreo.ignorado}, ticker=campos["ticker"],
                              motivo="criptomoneda")
        if tipo is TipoCorreo.ejecutada:
            _exigir(campos, "ticker", "lado", "cantidad", "precio", "total")
        else:
            _exigir(campos, "ticker", "lado")
        return EventoHapi(**base, **campos)

    if tipo is TipoCorreo.dividendo:
        ticker = (re.search(r"Dividendo de (\S+) recibido", _plano(correo.asunto), re.IGNORECASE)
                  or re.search(r"tus acciones de (\S+?)\.", texto, re.IGNORECASE))
        fecha = _campo(texto, "Fecha de pago", r"(\d{4}-\d{2}-\d{2})")
        campos = {
            "ticker": ticker.group(1) if ticker else None,
            "monto": _decimal(_campo(texto, "Monto recibido neto", r"(?:US)?\$\s?" + _NUMERO)),
            "fecha_pago": date.fromisoformat(fecha) if fecha else None,
        }
        _exigir(campos, "ticker", "monto")
        return EventoHapi(**base, **campos)

    if tipo is TipoCorreo.solicitud_deposito:
        pagar = re.search(rf"Monto a pagar\s*:\s*{_NUMERO}\s*(USD|PEN)", texto, re.IGNORECASE)
        # Los de 2022 traen solo "Monto: 10 USD", que es lo que llega a la cuenta.
        recibir = re.search(rf"Monto(?: a recibir)?\s*:\s*{_NUMERO}\s*USD", texto, re.IGNORECASE)
        campos = {
            "monto": _decimal(recibir.group(1)) if recibir else None,
            "monto_pagado": _decimal(pagar.group(1)) if pagar else None,
            "moneda_pagada": pagar.group(2).upper() if pagar else None,
        }
        _exigir(campos, "monto")
        return EventoHapi(**base, **campos)

    if tipo is TipoCorreo.fondos_agregados:
        m = re.search(rf"deposito de USD\s*{_NUMERO}", texto, re.IGNORECASE)
        campos = {"monto": _decimal(m.group(1)) if m else None}
        _exigir(campos, "monto")
        return EventoHapi(**base, **campos)

    if tipo is TipoCorreo.deposito_completado:
        return EventoHapi(**base)               # no trae importe: lo da la solicitud previa

    # retiro
    campos = {
        "monto": _decimal(_campo(texto, "Monto a retirar", _NUMERO)),
        "costo": _decimal(_campo(texto, "Costo del retiro", _NUMERO)),
    }
    _exigir(campos, "monto")
    return EventoHapi(**base, **campos)


def _orden(texto: str) -> dict:
    lado = (_campo(texto, r"Compra/Venta|Comprar/Vender") or "").lower()
    tipo_orden = _campo(texto, "Tipo de orden", r"(Orden (?:de mercado|limite|stop(?: limite)?))")
    cantidad = _campo(texto, r"Acciones|Cantidad", _NUMERO)
    return {
        "ticker": _campo(texto, "Ticker"),
        "lado": "compra" if lado.startswith("compr") else "venta" if lado.startswith("ven") else None,
        "tipo_orden": tipo_orden,
        "cantidad": _decimal(cantidad),
        "precio": _decimal(_campo(texto, "Precio promedio", r"US\$\s?" + _NUMERO)),
        "total": _decimal(_campo(texto, "Venta total", r"US\$\s?" + _NUMERO)),
        "comision": _decimal(_campo(texto, r"Fee de Apex|Comision", r"US\$\s?" + _NUMERO)),
    }
