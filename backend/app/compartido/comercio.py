"""Normalizacion de texto y de nombres de comercio.

Los comercios llegan del banco con basura: "RAPPI*RAPPI PERU   LIMA PE 12345".
Necesitamos una clave estable ("rappi") para agrupar, aprender y deduplicar.
"""
from __future__ import annotations

import re
import unicodedata

# Ruido tipico en los descriptores de POS peruanos
_NOISE = re.compile(
    r"\b(lima|peru|pe|per|sac|s\.a\.c\.|sa|s\.a\.|eirl|e\.i\.r\.l\.|srl|ltda?|"
    r"tienda|sucursal|suc|nro|no|num|compra|pago|internet|web|online|"
    r"pos|visa|mastercard|mc|amex|diners)\b",
    re.IGNORECASE,
)
_TOKEN_SPLIT = re.compile(r"[*/|#\\]+")
# Pasarelas de pago: cobran por cuenta del comercio y ponen su marca delante.
# "Culqui *LUNARIA" es LUNARIA cobrando por Culqi, no una tienda llamada Culqui.
# La regla de "quedarse con el fragmento mas largo" no vale: solo funcionaba con
# prefijos cortos como "PYU*", y con "Culqui*" se quedaba con la pasarela. Once
# movimientos aparecian como comercios "culqui" y "culqi" en vez de LUNARIA.
#
# Solo marcas de tres letras o mas: "mp" (Mercado Pago) se descarto justamente
# porque dos letras son el principio de demasiados nombres reales, y con el en
# la lista un comercio como "MP HOGAR*LIMA" perdia su fragmento bueno y se
# quedaba sin comercio.
_PASARELAS = {
    "pyu", "payu", "culqi", "culqui", "izi", "izipay", "niubiz", "visanet",
    "mercadopago", "dlocal", "openpay", "kushki",
}
_NON_ALNUM = re.compile(r"[^a-z0-9\s]")
_SPACES = re.compile(r"\s+")
# Fechas y horas que se cuelan al final del descriptor ("... el 09/08/2026 13:45")
_FECHA_HORA = re.compile(
    r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm)?\b",
    re.IGNORECASE,
)
# Conectores sueltos que quedan al recortar ("maria lopez el")
_COLA = re.compile(r"\s+(?:el|del|de|la|las|los|a|por|con|en|para|desde|hasta)$", re.IGNORECASE)
# Un comercio no puede llamarse asi. Si el resultado es solo una de estas, el
# patron que lo extrajo estaba mal y es mejor no tener comercio que tener basura.
_PALABRAS_VACIAS = {
    "de", "del", "la", "el", "los", "las", "a", "y", "en", "por", "con",
    "para", "desde", "hasta", "su", "tu", "un", "una", "al", "lo",
}

# Numero de local al final del descriptor: "IKF SAN ISIDRO 9" -> "ikf san isidro"
_NUM_LOCAL = re.compile(r"\s+\d{1,2}$")

# Canonicalizacion de comercios. Los bancos escriben el descriptor del POS, no
# el nombre comercial: "IKF SAN ISIDRO 9" es Inkafarma. Sin esto, cada local
# seria un comercio distinto y ni el ranking ni la memoria de comercio
# funcionarian. Anade aqui los que veas repetirse en tus movimientos.
_ALIAS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^ikf\b"), "inkafarma"),
    # Mifarma factura con el codigo del local delante, y las letras que lleva
    # antes del numero varian: "MFAG36 LARCOMAR", "MFAA11 SAN MIGUEL",
    # "MFA604 SAN ISIDRO", "MFA517 BARRANCO" (confirmado por el usuario, 6 set 2026).
    (re.compile(r"^mifa\b|^mf\s|^mf[a-z]{1,3}\d"), "mifarma"),
    # Starbucks factura con el codigo del local delante: "SB121 JOCKEY
    # PLAZA", "SB084 LARCOMAR II", "SB REAL PLAZA" (confirmado por el usuario, 6 set
    # 2026). Sin esto eran tres comercios distintos y habia que clasificar cada
    # local por separado, sin que la correccion sirviera para el siguiente.
    (re.compile(r"^sb\d*\s|^sb\d+$"), "starbucks"),
    (re.compile(r"^bot\b|^boticas\b"), "boticas"),
    (re.compile(r"^pvea\b|^plaza\s*vea\b"), "plaza vea"),
    (re.compile(r"^tott\b|^tottus\b"), "tottus"),
    (re.compile(r"^spsa\b"), "supermercados peruanos"),
    (re.compile(r"^cnc\b|^cencosud\b"), "cencosud"),
    (re.compile(r"^rappi\b"), "rappi"),
    # Yape lo escribe "PEDIDOS YA" con espacio; el POS del banco, "PEDIDOSYA".
    (re.compile(r"^pedidos\s*ya\b|^peya\b"), "pedidosya"),
    (re.compile(r"^uber\s*eats\b"), "uber eats"),
    (re.compile(r"^uber\b"), "uber"),
    (re.compile(r"^dlc\b|^don\s*lucho\b"), "don lucho"),
    # Cadenas con el local en el propio descriptor: "OXXO JOCKEY PLAZA",
    # "TAMBO+ 1234". Sin canonicalizar, cada tienda seria un comercio distinto.
    (re.compile(r"^oxxo\b"), "oxxo"),
    (re.compile(r"^tambo\b"), "tambo"),
    (re.compile(r"^cinemark\b"), "cinemark"),
    (re.compile(r"^cineplanet\b|^cp\s"), "cineplanet"),
    (re.compile(r"^primax\b"), "primax"),
    (re.compile(r"^repsol\b"), "repsol"),
]


def canonicalizar(nombre: str) -> str:
    for patron, canonico in _ALIAS:
        if patron.search(nombre):
            return canonico
    return nombre


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def clean_text(text: str) -> str:
    """Minusculas, sin tildes, espacios colapsados. Para comparar."""
    return _SPACES.sub(" ", strip_accents(text or "").lower()).strip()


def normalize_merchant(raw: str | None) -> str | None:
    """Convierte el descriptor crudo en una clave corta y estable."""
    if not raw:
        return None
    text = strip_accents(raw).lower()
    # las fechas se van ANTES de partir por "/", si no "09/08/2026" crea fragmentos
    text = _FECHA_HORA.sub(" ", text)
    # "RAPPI*RAPPI PERU" -> nos quedamos con el fragmento mas informativo
    parts = [p.strip() for p in _TOKEN_SPLIT.split(text) if p.strip()]
    if parts:
        # Fuera las pasarelas de pago, vengan delante o detras.
        sin_pasarela = [p for p in parts if p.split()[0] not in _PASARELAS] or parts
        text = (
            max(sin_pasarela, key=len)
            if len(sin_pasarela[0]) < 4
            else sin_pasarela[0]
        )
    text = _NON_ALNUM.sub(" ", text)
    text = _NOISE.sub(" ", text)
    text = re.sub(r"\b\d{3,}\b", " ", text)          # codigos de tienda
    text = _SPACES.sub(" ", text).strip()
    text = _COLA.sub("", text).strip()
    text = _NUM_LOCAL.sub("", text).strip()
    if not text:
        return None
    # maximo 4 palabras: mas alla suele ser ruido. El recorte puede dejar el
    # nombre partido por un conector ("EL RINCON DE LOS ABUELOS" -> "el rincon
    # de los" -> "el rincon de"), asi que se limpia hasta que no quede ninguno.
    text = " ".join(text.split()[:4])
    anterior = None
    while anterior != text:
        anterior = text
        text = _COLA.sub("", text).strip()
    # Red de seguridad: un patron mal escrito puede acabar capturando una
    # preposicion suelta. Un comercio llamado "de" no existe, y si se cuela
    # encabeza el ranking de gastos como si fuera real.
    if not text or text in _PALABRAS_VACIAS:
        return None
    return canonicalizar(text)


def display_merchant(normalized: str | None) -> str:
    return (normalized or "Sin comercio").title()
