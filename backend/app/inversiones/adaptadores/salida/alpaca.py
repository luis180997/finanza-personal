"""El puerto `FuenteDePrecios` con la Market Data API de Alpaca (v2).

POR QUE ALPACA Y NO YAHOO. Yahoo Finance no tiene API oficial desde 2017: las
librerias usan sus direcciones internas, que limitan por exceso de consultas y
cambian sin aviso. Alpaca tiene una API publica, versionada y documentada, gratis
con una cuenta de practica: 200 consultas por minuto, historia desde 2016 y barras
de 1 minuto a 1 mes, con o sin ajuste por splits y dividendos.

QUE SE PIDE:
- Cierres diarios del feed SIP (el consolidado de todas las bolsas): son los
  cierres oficiales. El plan gratuito no da los ultimos 15 minutos del SIP, que
  para un cierre de dia no importa.
- Intradia del feed IEX, que el plan gratuito da en tiempo real. IEX es una sola
  bolsa: su precio sigue al del mercado, pero en un minuto sin operaciones no hay
  barra (se usa la anterior).

Solo salen los simbolos de los valores: nunca cantidades ni datos de la cuenta.

CONFIGURACION: crea una cuenta gratuita en https://alpaca.markets (basta la de
practica, sin dinero), genera las claves en el panel y ponlas en el .env:

    ALPACA_KEY_ID=...
    ALPACA_SECRET_KEY=...
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import httpx

from app.inversiones.aplicacion.puertos import Cierre, ErrorDePrecios
from app.inversiones.dominio import calendario

URL_BARRAS = "https://data.alpaca.markets/v2/stocks/bars"
_POR_PAGINA = 10_000
_MICRO = Decimal(1_000_000)
_MARGEN_SIP = timedelta(minutes=16)


def _micro(valor: float) -> int:
    return int((Decimal(str(valor)) * _MICRO).to_integral_value())


class PreciosAlpaca:
    def __init__(self, key_id: str, secret: str, cliente: httpx.Client | None = None,
                 ahora=lambda: datetime.now(timezone.utc)):
        self._key_id = key_id
        self._secret = secret
        self._cliente = cliente or httpx.Client(timeout=30)
        self._ahora = ahora

    @property
    def configurada(self) -> bool:
        return bool(self._key_id and self._secret)

    def cierres(self, simbolos: list[str], desde: date, hasta: date) -> dict[str, list[Cierre]]:
        # El plan gratuito no deja pedir los ultimos 15 minutos del SIP, y una fecha
        # sola como fin ("2026-10-09") vale por el dia entero: si es hoy, incluye esos
        # minutos y Alpaca rechaza TODA la consulta (403 "recent SIP data"). Por eso
        # el fin va como hora exacta, como mucho 16 minutos antes de ahora.
        fin_del_dia = datetime.combine(hasta + timedelta(days=1), time(0), tzinfo=calendario.NUEVA_YORK)
        fin = min(fin_del_dia, self._ahora() - _MARGEN_SIP).astimezone(timezone.utc).isoformat()
        por_ajuste = {
            ajuste: self._barras(simbolos, "1Day", inicio=desde.isoformat(), fin=fin,
                                 ajuste=ajuste, feed="sip")
            for ajuste in ("raw", "split", "all")
        }
        resultado: dict[str, list[Cierre]] = {}
        for simbolo, crudas in por_ajuste["raw"].items():
            split = {_dia(b["t"]): b["c"] for b in por_ajuste["split"].get(simbolo, [])}
            total = {_dia(b["t"]): b["c"] for b in por_ajuste["all"].get(simbolo, [])}
            cierres = []
            for b in crudas:
                dia = _dia(b["t"])
                if dia > hasta or dia not in split or dia not in total:
                    continue
                cierres.append(Cierre(dia, _micro(b["c"]), _micro(split[dia]), _micro(total[dia])))
            resultado[simbolo] = cierres
        return resultado

    def barras(self, simbolos: list[str], desde: datetime,
               minutos: int) -> dict[str, list[tuple[datetime, int]]]:
        crudas = self._barras(simbolos, f"{minutos}Min", inicio=desde.astimezone(timezone.utc).isoformat(),
                              fin=None, ajuste="raw", feed="iex")
        resultado = {}
        for simbolo, barras in crudas.items():
            # Alpaca fecha la barra por su inicio; el precio es el del final.
            resultado[simbolo] = [
                (_utc(b["t"]) + timedelta(minutes=minutos), _micro(b["c"])) for b in barras
            ]
        return resultado

    def _barras(self, simbolos: list[str], marco: str, inicio: str, fin: str | None,
                ajuste: str, feed: str) -> dict[str, list[dict]]:
        if not self.configurada:
            raise ErrorDePrecios("Faltan ALPACA_KEY_ID y ALPACA_SECRET_KEY en el .env")
        parametros = {
            "symbols": ",".join(simbolos), "timeframe": marco, "start": inicio,
            "adjustment": ajuste, "feed": feed, "limit": _POR_PAGINA, "sort": "asc",
        }
        if fin:
            parametros["end"] = fin
        cabeceras = {"APCA-API-KEY-ID": self._key_id, "APCA-API-SECRET-KEY": self._secret}
        barras: dict[str, list[dict]] = defaultdict(list)
        token = None
        while True:
            if token:
                parametros["page_token"] = token
            try:
                respuesta = self._cliente.get(URL_BARRAS, params=parametros, headers=cabeceras)
            except httpx.HTTPError as exc:
                raise ErrorDePrecios(f"Alpaca no responde: {type(exc).__name__}") from exc
            if respuesta.status_code == 401:
                raise ErrorDePrecios("Alpaca rechazo las claves: revisa ALPACA_KEY_ID y ALPACA_SECRET_KEY")
            if respuesta.status_code == 403:   # claves buenas, consulta fuera del plan
                raise ErrorDePrecios(f"Alpaca no permite esta consulta con tu plan: {_mensaje(respuesta)}")
            if respuesta.status_code == 429:
                raise ErrorDePrecios("Alpaca pidio esperar: demasiadas consultas en un minuto")
            if respuesta.status_code != 200:
                raise ErrorDePrecios(f"Alpaca respondio {respuesta.status_code}: {_mensaje(respuesta)}")
            cuerpo = respuesta.json()
            for simbolo, lista in (cuerpo.get("bars") or {}).items():
                barras[simbolo].extend(lista)
            token = cuerpo.get("next_page_token")
            if not token:
                return dict(barras)


def _mensaje(respuesta: httpx.Response) -> str:
    try:
        return str(respuesta.json().get("message") or respuesta.text)[:200]
    except ValueError:
        return respuesta.text[:200]


def _utc(marca: str) -> datetime:
    """'2026-10-09T13:35:00Z' -> datetime UTC sin zona."""
    return datetime.fromisoformat(marca.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)


def _dia(marca: str) -> date:
    """Las barras diarias vienen a medianoche de Nueva York expresada en UTC."""
    return datetime.fromisoformat(marca.replace("Z", "+00:00")).astimezone(calendario.NUEVA_YORK).date()
