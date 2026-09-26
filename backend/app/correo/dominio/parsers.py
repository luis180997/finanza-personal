"""Motor de parsers: convierte las reglas de patterns.yaml en parsers ejecutables.

Es dominio: sabe leer un correo bancario, pero no de donde salen las reglas. El
archivo lo lee el adaptador (adaptadores/salida/patrones.py) y le pasa los datos ya
cargados, junto con la zona horaria en la que el banco escribe sus fechas.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from dateutil import parser as dateparser

from app.compartido.dinero import parse_money
from app.compartido.comercio import clean_text
from app.correo.dominio.correo import ParsedTx, RawEmail

_MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "setiembre": 9, "septiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
    # Abreviaturas: Yape escribe "22 Ago. 2026" en los pagos de servicio.
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "set": 9, "sep": 9, "oct": 10, "nov": 11, "dic": 12,
}


def _compile(patterns: list[str]) -> list[re.Pattern]:
    return [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in patterns or []]


def _first_group(regexes: list[re.Pattern], text: str) -> str | None:
    for rx in regexes:
        m = rx.search(text)
        if m:
            value = (m.group(1) if m.groups() else m.group(0)).strip()
            if value:
                return value
    return None


def _parse_spanish_date(raw: str) -> datetime | None:
    """Acepta los cuatro formatos que usan los bancos peruanos:

        BCP           -> "03 de setiembre de 2026"
        Yape          -> "04 septiembre 2026"     (sin los "de")
        BBVA          -> "5 de setiembre, 2026"   (con coma antes del anio)
        Yape servicio -> "22 Ago. 2026"           (mes abreviado, con punto)
    """
    raw = raw.strip().lower()
    m = re.match(r"(\d{1,2})\s+(?:de\s+)?([a-z]+)\.?,?\s+(?:de\s+)?(\d{4})", raw)
    if m and m.group(2) in _MESES:
        return datetime(int(m.group(3)), _MESES[m.group(2)], int(m.group(1)))
    try:
        return dateparser.parse(raw, dayfirst=True, fuzzy=True)
    except (ValueError, OverflowError):
        return None


def _normalizar_hora(raw: str) -> str:
    """Yape escribe "03:38 p. m." con puntos y espacios; dateutil no lo entiende
    y lo interpretaria como las 3 de la madrugada. Lo dejamos en "03:38 PM"."""
    limpio = raw.strip().lower()
    limpio = re.sub(r"\bp\s*\.?\s*m\s*\.?", "PM", limpio)
    limpio = re.sub(r"\ba\s*\.?\s*m\s*\.?", "AM", limpio)
    return re.sub(r"\s+", " ", limpio).strip()


@dataclass
class YamlParser:
    id: str
    label: str
    bank: str
    priority: int
    direction: str
    confidence: float
    account_hint: str | None
    payment_method: str | None
    category_hint: str | None
    sender_any: list[str]
    subject_any: list[str]
    body_all: list[str]
    body_any: list[str]
    skip_any: list[str]
    direction_if: list[dict[str, Any]]
    extract: dict[str, list[re.Pattern]]
    zona: ZoneInfo                    # la hora del correo es hora local del banco

    # ------------------------------------------------------------------ match
    def matches(self, email: RawEmail, ignorar_remitente: bool = False) -> bool:
        sender = clean_text(email.sender)
        subject = clean_text(email.subject)
        hay = clean_text(email.haystack)

        if not ignorar_remitente and self.sender_any:
            if not any(s in sender for s in self.sender_any):
                return False
        if self.subject_any and not any(s in subject for s in self.subject_any):
            return False
        if self.body_all and not all(s in hay for s in self.body_all):
            return False
        if self.body_any and not any(s in hay for s in self.body_any):
            return False
        if self.skip_any and any(s in hay for s in self.skip_any):
            return False
        return True

    # ------------------------------------------------------------------ parse
    def parse(self, email: RawEmail) -> ParsedTx | None:
        hay = clean_text(email.haystack)

        raw_amount = _first_group(self.extract.get("amount", []), hay)
        amount = parse_money(raw_amount) if raw_amount else None
        if amount is None or amount <= 0:
            return None

        currency = "PEN"
        if _first_group(self.extract.get("currency", []), hay):
            currency = "USD"

        direction = self.direction
        for override in self.direction_if:
            if any(clean_text(k) in hay for k in override.get("any", [])):
                direction = override["direction"]
                break

        occurred_at = self._extract_datetime(hay) or email.received_at

        merchant_raw = _first_group(self.extract.get("merchant", []), email.haystack)
        # El numero de operacion se saca del texto CRUDO para conservar
        # mayusculas: el del BBVA es "ABC123DEF456", y guardarlo como
        # "abc123def456" impide compararlo con el correo o con la banca.
        operacion = (
            _first_group(self.extract.get("operation", []), email.haystack)
            or _first_group(self.extract.get("operation", []), hay)
        )
        confidence = self.confidence
        if not merchant_raw:
            confidence -= 0.15

        return ParsedTx(
            amount=amount,
            direction=direction,
            currency=currency,
            occurred_at=occurred_at,
            merchant_raw=merchant_raw,
            description=email.subject.strip() or None,
            operation_number=operacion,
            account_hint=self.account_hint,
            payment_method=self.payment_method,
            category_hint=self.category_hint,
            last4=_first_group(self.extract.get("last4", []), hay),
            bank=self.bank,
            parser=self.id,
            confidence=round(max(0.1, min(confidence, 1.0)), 2),
        )

    def _extract_datetime(self, hay: str) -> datetime | None:
        raw_date = _first_group(self.extract.get("date", []), hay)
        if not raw_date:
            return None
        dt = _parse_spanish_date(raw_date)
        if not dt:
            return None
        raw_time = _first_group(self.extract.get("time", []), hay)
        if raw_time:
            try:
                t = dateparser.parse(_normalizar_hora(raw_time)).time()
                dt = datetime.combine(dt.date(), t)
            except (ValueError, OverflowError, TypeError):
                dt = datetime.combine(dt.date(), time(12, 0))
        return dt.replace(tzinfo=self.zona)


@dataclass
class PatternBundle:
    senders: list[str]
    global_skip: list[str]
    parsers: list[YamlParser]


def construir_bundle(data: dict, zona: ZoneInfo) -> PatternBundle:
    """Los parsers definidos en `data` (el contenido de patterns.yaml), por prioridad."""
    global_skip = [clean_text(s) for s in data.get("global_skip", [])]

    parsers: list[YamlParser] = []
    for raw in data.get("parsers", []):
        if raw.get("enabled") is False:
            continue
        match = raw.get("match", {}) or {}
        parsers.append(
            YamlParser(
                id=raw["id"],
                label=raw.get("label", raw["id"]),
                bank=raw.get("bank", "otro"),
                priority=int(raw.get("priority", 100)),
                direction=raw.get("direction", "gasto"),
                confidence=float(raw.get("confidence", 0.8)),
                account_hint=raw.get("account_hint"),
                payment_method=raw.get("payment_method"),
                category_hint=raw.get("category_hint"),
                sender_any=[clean_text(s) for s in match.get("sender_any", [])],
                subject_any=[clean_text(s) for s in match.get("subject_any", [])],
                body_all=[clean_text(s) for s in match.get("body_all", [])],
                body_any=[clean_text(s) for s in match.get("body_any", [])],
                # OJO: aqui va SOLO el skip_if_any del parser, que si mira el
                # cuerpo a proposito (para que el parser generico no se trague
                # un retiro, por ejemplo). El global_skip NO se mezcla: mira
                # solo el asunto, en `leer`. Mezclarlo aqui era
                # la segunda via por la que el aviso de seguridad del BCP
                # ("...sorteos o promociones") mataba consumos reales.
                skip_any=[clean_text(s) for s in raw.get("skip_if_any", [])],
                direction_if=raw.get("direction_if", []) or [],
                extract={k: _compile(v) for k, v in (raw.get("extract", {}) or {}).items()},
                zona=zona,
            )
        )
    parsers.sort(key=lambda p: p.priority)
    return PatternBundle(
        senders=data.get("senders", []),
        global_skip=global_skip,
        parsers=parsers,
    )


def consulta_gmail(bundle: PatternBundle, lookback_days: int) -> str:
    """Query de Gmail que acota la busqueda a los remitentes conocidos."""
    senders = bundle.senders
    if not senders:
        return f"newer_than:{lookback_days}d"
    from_clause = " OR ".join(f"from:{s}" for s in senders)
    return f"({from_clause}) newer_than:{lookback_days}d"


def leer(
    bundle: PatternBundle, email: RawEmail, ignorar_remitente: bool = False,
) -> tuple[ParsedTx | None, str | None]:
    """Devuelve (transaccion, motivo_de_fallo).

    `ignorar_remitente` solo se usa en el laboratorio: alli el usuario pega
    un cuerpo suelto y a menudo no sabe cual era el remitente exacto.
    """
    # El descarte mira SOLO EL ASUNTO, nunca el cuerpo.
    #
    # Miraba el cuerpo entero, y eso tiraba a la basura todos los consumos del
    # BCP: su aviso de seguridad al pie dice "...para participar en sorteos o
    # promociones", y "sorteo" estaba en la lista de descarte. 22 gastos reales
    # perdidos en silencio antes de que nadie los viera.
    #
    # Un correo promocional se delata en el asunto ("Aprovecha 30% de
    # descuento"); el pie de pagina de uno legitimo siempre trae publicidad.
    asunto = clean_text(email.subject)
    if any(skip in asunto for skip in bundle.global_skip):
        return None, "descartado por el asunto (parece promocional)"

    tried: list[str] = []
    for parser in bundle.parsers:
        if not parser.matches(email, ignorar_remitente):
            continue
        tried.append(parser.id)
        result = parser.parse(email)
        if result is not None:
            return result, None

    if tried:
        return None, f"parsers que coincidieron pero no extrajeron monto: {', '.join(tried)}"
    return None, "ningun parser coincidio con este remitente/contenido"
