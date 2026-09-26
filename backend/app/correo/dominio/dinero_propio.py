"""Movimientos que parecen gasto pero en los que el dinero sigue siendo tuyo.

Son dos casos, y el banco los notifica igual que un pago a un tercero:

1. **Te envias dinero a ti mismo.** Mover S/400 de tu cuenta del BCP a la tuya
   del BBVA no es gastarlo.
2. **Compras dolares en una casa de cambio.** Tampoco: el dinero solo cambia de
   moneda.

En los datos reales del usuario eran doce y tres movimientos, varios miles de soles, y
el primero llegaba a encabezar el ranking de "donde mas gastas" con el nombre
del propio titular.

El truco es que el banco ya nos dice quien eres: todos sus correos empiezan
saludandote por tu nombre. Comparamos ese saludo con el destinatario y no hay
nada que configurar.

El banco enmascara los nombres de personas ("Ca*** Al*** Qu***"), asi que la
comparacion acepta un token enmascarado si su parte visible es prefijo del
nombre del saludo.
"""
from __future__ import annotations

import re
from collections import Counter

from app.compartido.comercio import strip_accents

# La escribe el pipeline y la reconoce la pantalla de revision para explicar
# el movimiento. Compartir la constante evita comparar textos a mano.
NOTA_ENVIO_PROPIO = (
    "El destinatario se llama como tu, asi que se tomo como un envio "
    "entre tus propias cuentas y no cuenta como gasto."
)
NOTA_CASA_DE_CAMBIO = (
    "Es una casa de cambio: el dinero solo cambio de moneda, asi que no "
    "cuenta como gasto."
)

# Casas de cambio conocidas (confirmadas el 6 set 2026). Comprar dolares no es
# gastar: el dinero sigue siendo tuyo, solo cambia de moneda. Anade aqui las que
# veas aparecer; se comparan contra el nombre ya normalizado, asi que basta el
# principio del nombre.
CASAS_DE_CAMBIO = ("kambista", "cross payments")


def es_casa_de_cambio(merchant: str | None) -> bool:
    return bool(merchant) and merchant.startswith(CASAS_DE_CAMBIO)

# "Hola Carlos Alberto," / "Hola, Carlos Alberto:" / "Estimado Carlos Alberto"
_SALUDO = re.compile(
    r"^[ \t]*(?:hola|estimad[oa]|sr\.?|sra\.?)[ \t,:]+([^\n,:;!¡.]{2,60})",
    re.IGNORECASE | re.MULTILINE,
)
_NO_ES_NOMBRE = {"que", "como", "te", "ya", "aqui", "de", "tu", "su"}


def _tokens(texto: str) -> list[str]:
    limpio = strip_accents(texto or "").lower()
    return [t for t in re.split(r"[\s.]+", limpio) if t]


def nombre_del_titular(cuerpo: str | None) -> list[str]:
    """Los nombres con los que el banco te saluda, en tokens.

    Devuelve [] si el saludo es de una sola palabra: "Hola, Carlos" no distingue
    entre tu y cualquier otro Carlos, y creerselo marcaria como propios envios que
    no lo son.
    """
    if not cuerpo:
        return []
    m = _SALUDO.search(cuerpo)
    if not m:
        return []
    partes = [t for t in _tokens(m.group(1)) if t.isalpha() and t not in _NO_ES_NOMBRE]
    return partes if len(partes) >= 2 else []


# El nombre COMPLETO, cuando el correo lo dice con todas las letras. El BBVA
# saluda solo con el nombre de pila ("Hola, CARLOS"), que no identifica a nadie,
# pero otros correos tuyos traen el nombre entero en una fila con etiqueta.
_TITULAR_EXPLICITO = re.compile(
    r"(?:titular de la cuenta|yapero|titular)\s*:?\s*\n?\s*([^\n]{5,60})",
    re.IGNORECASE,
)
# Minimo de nombres que deben encajar cuando se usa el nombre aprendido. Con
# tres ("Carlos ... Quispe ...") la posibilidad de confundirte con otra persona es
# despreciable; con dos, cualquier tocayo de nombre y apellido colaria.
_MINIMO_TOKENS_APRENDIDO = 3


def nombre_completo_del_titular(cuerpo: str | None) -> list[str]:
    """El nombre entero del titular, si el correo lo dice explicitamente."""
    if not cuerpo:
        return []
    for m in _TITULAR_EXPLICITO.finditer(cuerpo):
        partes = [t for t in _tokens(m.group(1)) if t.isalpha() and t not in _NO_ES_NOMBRE]
        if len(partes) >= _MINIMO_TOKENS_APRENDIDO:
            return partes
    return []


def _casa(token_titular: str, token_destino: str, aceptar_inicial: bool = False) -> bool:
    if token_titular == token_destino:
        return True
    # "Ca***" es una mascara: nos vale si lo visible encaja con el principio.
    visible = token_destino.split("*", 1)[0]
    if "*" in token_destino and len(visible) >= 2 and token_titular.startswith(visible):
        return True
    # "Carlos A Quispe M" es "Carlos Alberto Quispe Mamani" con las iniciales.
    # Solo se acepta contra el nombre completo aprendido: con el saludo de dos
    # palabras, "Carlos M Perez" pasaria por tuyo y no lo es.
    return aceptar_inicial and len(token_destino) == 1 and token_titular.startswith(token_destino)


def es_envio_a_uno_mismo(
    cuerpo: str | None,
    destinatario: str | None,
    titular_aprendido: list[str] | None = None,
) -> bool:
    """True si el destinatario del envio eres tu.

    Primero manda lo que diga ESTE correo: su saludo. Es autocontenido y no
    depende de en que orden se procesen los correos. Solo cuando el saludo no
    sirve —el BBVA saluda "Hola, CARLOS" y eso no identifica a nadie— se recurre
    al nombre completo aprendido de otros correos tuyos.
    """
    if titular_aprendido and not nombre_del_titular(cuerpo):
        return _coincide_con_titular(titular_aprendido, destinatario)

    saludo = nombre_del_titular(cuerpo)
    if not saludo or not destinatario:
        return False
    destino = _tokens(destinatario)
    if len(destino) < len(saludo):
        return False
    return all(_casa(s, d) for s, d in zip(saludo, destino))


def _coincide_con_titular(titular: list[str], destinatario: str | None) -> bool:
    """Compara el destinatario con el nombre completo aprendido, SIN mirar el orden.

    Cada nombre del destinatario tiene que encajar con uno del titular que no se
    haya usado ya, y hacen falta al menos tres. Asi entra "Carlos A Quispe M" —el
    mismo, con las iniciales— y no entra un "Carlos Alberto" cualquiera.

    El orden no puede mandar aqui porque el propio banco escribe el nombre de las
    dos maneras: en los correos reales aparece tanto "Carlos Alberto Quispe
    Mamani" como "Quispe Mamani Carlos Alberto". Comparando por posicion,
    cual de las dos se hubiera aprendido primero decidia si los envios a uno
    mismo se detectaban o no.
    """
    if not destinatario:
        return False
    destino = _tokens(destinatario)
    if min(len(titular), len(destino)) < _MINIMO_TOKENS_APRENDIDO:
        return False

    libres = list(titular)
    for d in destino:
        pareja = next((t for t in libres if _casa(t, d, aceptar_inicial=True)), None)
        if pareja is None:
            # Un solo nombre que no sea suyo basta para descartarlo: "Carlos Alberto
            # Perez Garcia" comparte dos nombres con el y no es el.
            return False
        libres.remove(pareja)
    return True


# --------------------------------------------------------------- nombre aprendido
def mejor_nombre_completo(cuerpos) -> list[str]:
    """El nombre completo del titular, buscado en un monton de correos.

    Se calcula ANTES de clasificar, sobre todos los correos de la tanda, para que
    el resultado no dependa del orden en que se procesen: si el nombre se
    aprendiera sobre la marcha, los correos anteriores al primero que lo dice se
    quedarian sin el.

    Y NO se queda con el primero que encuentra, sino con el mas completo. El
    mismo buzon trae "Carlos Alberto Quispe Mamani" (47 correos) y "Carlos
    Alberto Quispe C" (7): quedarse con la version abreviada empeora todas las
    comparaciones posteriores, porque una inicial encaja con menos cosas.

    Devuelve [] si ningun correo lo dice. Guardarlo es cosa del caso de uso.
    """
    candidatos: Counter[tuple[str, ...]] = Counter()
    for cuerpo in cuerpos:
        nombre = nombre_completo_del_titular(cuerpo)
        if nombre:
            candidatos[tuple(nombre)] += 1
    if not candidatos:
        return []

    # Mas nombres completos (sin iniciales) primero; a igualdad, el mas repetido.
    mejor = max(
        candidatos,
        key=lambda n: (sum(1 for t in n if len(t) > 1), candidatos[n]),
    )
    return list(mejor)


def motivo_no_es_gasto(notes: str | None) -> str | None:
    """Cual de las dos deducciones marco este movimiento, si es que alguna.

    Mira solo el PRINCIPIO de la nota, no la nota entera. Comparando por
    igualdad exacta, cualquier cosa que se anadiera despues —el aviso de que se
    borro el movimiento del que era duplicado, por ejemplo— dejaba al movimiento
    sin su explicacion de por que no cuenta como gasto, y fuera del aviso del
    panel, aunque siguiera excluido del total.
    """
    if not notes:
        return None
    for marca in (NOTA_ENVIO_PROPIO, NOTA_CASA_DE_CAMBIO):
        if notes.startswith(marca):
            return marca
    return None
