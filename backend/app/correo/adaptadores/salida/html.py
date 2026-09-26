"""Aplanado de correos: MIME -> texto legible."""
from __future__ import annotations

import base64
import re

from bs4 import BeautifulSoup

_BLANK_LINES = re.compile(r"\n{3,}")
_SPACES = re.compile(r"[ \t\xa0]+")


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "head", "title", "meta"]):
        tag.decompose()
    # <br> y <td> deben producir saltos: si no, "S/ 39.63RAPPI" queda pegado
    for br in soup.find_all(["br", "tr", "div", "p", "td", "th", "li"]):
        br.append("\n")
    text = soup.get_text(separator=" ")
    text = _SPACES.sub(" ", text)
    return _BLANK_LINES.sub("\n\n", text).strip()


def _b64(data: str) -> str:
    return base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", errors="replace")


def normalizar_saltos(texto: str) -> str:
    """Unifica los finales de linea a \\n.

    Los correos vienen con CRLF. Los patrones de comercio usan `([^\\n]+)` para
    quedarse con "el resto de la linea", y con CRLF eso capturaba el `\\r` final:
    el asunto "Servicio de\\r\\n Notificaciones BCP" daba el comercio "de".
    """
    return (texto or "").replace("\r\n", "\n").replace("\r", "\n")


def decode_header_value(valor: str | None) -> str:
    """Decodifica cabeceras RFC 2047 ("=?UTF-8?B?...?=") a texto legible.

    Los asuntos con tildes llegan codificados, y sin decodificarlos los patrones
    nunca encontrarian "Realizaste un consumo".
    """
    from email.header import decode_header, make_header

    if not valor:
        return ""
    try:
        return normalizar_saltos(str(make_header(decode_header(valor))))
    except (UnicodeDecodeError, LookupError, ValueError):
        return normalizar_saltos(valor)


def extract_body_mime(msg) -> str:
    """Aplana un email.message.Message (lo que devuelve IMAP) a texto.

    Equivalente a extract_body(), pero para el formato de la biblioteca estandar
    en vez del arbol JSON de la API de Gmail.
    """
    plain: list[str] = []
    html: list[str] = []

    for parte in msg.walk() if msg.is_multipart() else [msg]:
        tipo = parte.get_content_type()
        if tipo not in ("text/plain", "text/html"):
            continue
        try:
            crudo = parte.get_payload(decode=True)
        except Exception:  # noqa: BLE001 - una parte corrupta no debe tumbar la sync
            continue
        if not crudo:
            continue
        juego = parte.get_content_charset() or "utf-8"
        try:
            texto = crudo.decode(juego, errors="replace")
        except (LookupError, UnicodeDecodeError):
            texto = crudo.decode("utf-8", errors="replace")
        (plain if tipo == "text/plain" else html).append(texto)

    # Mismo criterio que en la API: el HTML trae el monto en una tabla que la
    # version text/plain suele dejar incompleta.
    if html:
        texto = html_to_text("\n".join(html))
        if len(texto) > 40:
            return texto
    if plain:
        return _BLANK_LINES.sub("\n\n", "\n".join(plain)).strip()
    return ""


def extract_body(payload: dict) -> str:
    """Recorre el arbol MIME de la API de Gmail y devuelve el mejor texto."""
    plain: list[str] = []
    html: list[str] = []

    def walk(part: dict) -> None:
        mime = part.get("mimeType", "")
        body = part.get("body", {}) or {}
        data = body.get("data")
        if data:
            try:
                decoded = _b64(data)
            except (ValueError, UnicodeDecodeError):
                decoded = ""
            if mime == "text/plain":
                plain.append(decoded)
            elif mime == "text/html":
                html.append(decoded)
        for child in part.get("parts", []) or []:
            walk(child)

    walk(payload)

    # Preferimos HTML: las notificaciones bancarias suelen poner el monto en
    # una tabla que la version text/plain deja incompleta.
    if html:
        text = html_to_text("\n".join(html))
        if len(text) > 40:
            return text
    if plain:
        return _BLANK_LINES.sub("\n\n", "\n".join(plain)).strip()
    return ""
