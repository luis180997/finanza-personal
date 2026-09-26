"""Diccionario de comercios conocidos: la tercera capa del clasificador.

Comercio (fragmento del nombre ya normalizado) -> (categoria, necesidad). Sirve
para el arranque en frio: lo que aparece aqui deja de pasar por la bandeja.
"""
from __future__ import annotations

import re
from collections.abc import Iterator

from app.compartido.tipos import Necessity

# comercio (substring normalizado) -> (categoria, necesidad)
SEED_KEYWORDS: dict[str, tuple[str, Necessity | None]] = {
    # delivery
    "rappi": ("Delivery", Necessity.evitable),
    "pedidosya": ("Delivery", Necessity.evitable),
    "didi food": ("Delivery", Necessity.evitable),
    "uber eats": ("Delivery", Necessity.evitable),
    # taxi
    "uber": ("Taxi", None),
    "cabify": ("Taxi", None),
    "indriver": ("Taxi", None),
    "didi": ("Taxi", None),
    "beat": ("Taxi", None),
    # supermercado
    "plaza vea": ("Mercado y supermercado", Necessity.esencial),
    "tottus": ("Mercado y supermercado", Necessity.esencial),
    "metro": ("Mercado y supermercado", Necessity.esencial),
    "wong": ("Mercado y supermercado", Necessity.esencial),
    "vivanda": ("Mercado y supermercado", Necessity.esencial),
    "makro": ("Mercado y supermercado", Necessity.esencial),
    "mass": ("Mercado y supermercado", Necessity.esencial),
    # tiendas de conveniencia: lo que se compra ahi es snack
    "oxxo": ("Snacks", Necessity.discrecional),
    "tambo": ("Snacks", Necessity.discrecional),
    "listo": ("Snacks", Necessity.discrecional),
    # restaurantes
    "bembos": ("Restaurante", Necessity.discrecional),
    "kfc": ("Restaurante", Necessity.discrecional),
    "popeyes": ("Restaurante", Necessity.discrecional),
    "pizza hut": ("Restaurante", Necessity.discrecional),
    "papa johns": ("Restaurante", Necessity.discrecional),
    "china wok": ("Restaurante", Necessity.discrecional),
    # Cadenas frecuentes en Lima, identificadas a mano
    # (6 set 2026). Todo lo que este aqui deja de pasar por la bandeja.
    "longhorn": ("Restaurante", Necessity.discrecional),
    "chilis": ("Restaurante", Necessity.discrecional),
    "don buffet": ("Restaurante", Necessity.discrecional),
    "norkys": ("Restaurante", Necessity.discrecional),
    "pardos": ("Restaurante", Necessity.discrecional),
    "rokys": ("Restaurante", Necessity.discrecional),
    "la lucha": ("Restaurante", Necessity.discrecional),
    "mc donald": ("Restaurante", Necessity.discrecional),
    "burger king": ("Restaurante", Necessity.discrecional),
    "subway": ("Restaurante", Necessity.discrecional),
    "xipe": ("Restaurante", Necessity.discrecional),
    "kaikan": ("Restaurante", Necessity.discrecional),
    "portofino": ("Restaurante", Necessity.discrecional),
    "naruto": ("Restaurante", Necessity.discrecional),
    "el rincon": ("Restaurante", Necessity.discrecional),
    # cafeterias
    "starbucks": ("Cafe", Necessity.discrecional),
    "juan valdez": ("Cafe", Necessity.discrecional),
    # minimarket
    "minimarket": ("Mercado y supermercado", Necessity.esencial),
    # salud  (los descriptores del POS ya vienen canonicalizados por normalize.py:
    #         "IKF SAN ISIDRO 9" llega aqui como "inkafarma")
    "inkafarma": ("Farmacia", Necessity.esencial),
    "mifarma": ("Farmacia", Necessity.esencial),
    "boticas": ("Farmacia", Necessity.esencial),
    "farmacia": ("Farmacia", Necessity.esencial),
    "clinica": ("Consultas", Necessity.esencial),
    "laboratorios clinico": ("Consultas", Necessity.esencial),
    "smart fit": ("Gimnasio", Necessity.discrecional),
    "bodytech": ("Gimnasio", Necessity.discrecional),
    # combustible
    "primax": ("Combustible", Necessity.esencial),
    "repsol": ("Combustible", Necessity.esencial),
    "petroperu": ("Combustible", Necessity.esencial),
    "grifo": ("Combustible", Necessity.esencial),
    # servicios
    "sedapal": ("Agua", Necessity.esencial),
    "luz del sur": ("Luz", Necessity.esencial),
    "enel": ("Luz", Necessity.esencial),
    "calidda": ("Gas", Necessity.esencial),
    "claro": ("Plan movil", Necessity.esencial),
    "movistar": ("Plan movil", Necessity.esencial),
    "entel": ("Plan movil", Necessity.esencial),
    "bitel": ("Plan movil", Necessity.esencial),
    "win": ("Internet y cable", Necessity.esencial),
    # suscripciones
    "netflix": ("Streaming", Necessity.discrecional),
    "spotify": ("Streaming", Necessity.discrecional),
    "disney": ("Streaming", Necessity.discrecional),
    "hbo": ("Streaming", Necessity.discrecional),
    "max": ("Streaming", Necessity.discrecional),
    "crunchyroll": ("Streaming", Necessity.discrecional),
    "youtube": ("Streaming", Necessity.discrecional),
    "openai": ("Software y nube", Necessity.discrecional),
    "anthropic": ("Software y nube", Necessity.discrecional),
    "google": ("Software y nube", Necessity.discrecional),
    "microsoft": ("Software y nube", Necessity.discrecional),
    "aws": ("Software y nube", Necessity.discrecional),
    "github": ("Software y nube", Necessity.discrecional),
    # compras
    "falabella": ("Ropa y calzado", Necessity.discrecional),
    "ripley": ("Ropa y calzado", Necessity.discrecional),
    "oechsle": ("Ropa y calzado", Necessity.discrecional),
    "marathon": ("Ropa y calzado", Necessity.discrecional),   # tienda deportiva
    "sodimac": ("Hogar", Necessity.discrecional),
    "promart": ("Hogar", Necessity.discrecional),
    "miniso": ("Hogar", Necessity.discrecional),
    "mercado libre": ("Tecnologia", Necessity.discrecional),
    "aliexpress": ("Tecnologia", Necessity.discrecional),
    "amazon": ("Tecnologia", Necessity.discrecional),
    "samsung": ("Tecnologia", Necessity.discrecional),
    "sansung": ("Tecnologia", Necessity.discrecional),
    "compu prime": ("Tecnologia", Necessity.discrecional),
    # Tienda de accesorios de celular: fundas, laminas, cargadores
    # (confirmado por el usuario, 9 set 2026). Llega como "IZI*DATACELL".
    "datacell": ("Tecnologia", Necessity.discrecional),
    # tramites
    "pagalo": ("Tramites del Estado", Necessity.esencial),
    # transporte publico
    "metropolitano": ("Transporte publico", Necessity.esencial),
    "linea 1": ("Transporte publico", Necessity.esencial),
    # entretenimiento
    "cineplanet": ("Cine y eventos", Necessity.discrecional),
    "cinemark": ("Cine y eventos", Necessity.discrecional),
    "teleticket": ("Cine y eventos", Necessity.discrecional),
    "joinnus": ("Cine y eventos", Necessity.discrecional),
}


def candidatos(objetivo: str) -> Iterator[tuple[str, Necessity | None]]:
    """(categoria, necesidad) de cada comercio conocido que aparece en el texto.

    La clave mas larga va primero: "didi food" antes que "didi". Se devuelven todos
    en orden porque quien pregunta se queda con el primero cuya categoria exista.
    """
    for clave in sorted(SEED_KEYWORDS, key=len, reverse=True):
        # Limites de palabra completa para evitar falsos positivos como
        # 'win' dentro de nombres de personas ('eswin', 'edwin', 'yrwing') o
        # 'max' en 'maximiliano'.
        patron = rf"\b{re.escape(clave)}\b"
        if re.search(patron, objetivo):
            yield SEED_KEYWORDS[clave]
