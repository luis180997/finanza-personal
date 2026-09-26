"""El arbol de categorias: padres, hijas y ramas."""
from __future__ import annotations

from collections.abc import Iterator

from app.clasificacion.dominio.entidades import Category


def ancestros(cat: Category | None, categorias: dict) -> Iterator[Category]:
    """`cat`, su padre, su abuelo... hasta la raiz.

    Se corta si los datos traen un ciclo. Sin el corte, una categoria que
    colgara de una de sus propias hijas dejaba cada calculo en un bucle infinito.
    """
    vistos: set[int] = set()
    while cat is not None and cat.id not in vistos:
        vistos.add(cat.id)
        yield cat
        cat = categorias.get(cat.parent_id) if cat.parent_id else None


def raiz(cat: Category | None, categorias: dict) -> Category | None:
    ultima = None
    for ultima in ancestros(cat, categorias):
        pass
    return ultima


def rama_bajo(cat: Category | None, ancestro_id: int, categorias: dict) -> Category | None:
    """De que categoria del nivel justo debajo de `ancestro_id` cuelga `cat`.

    Un gasto puesto en el propio ancestro devuelve el ancestro. None si `cat` no
    esta en su rama.
    """
    for c in ancestros(cat, categorias):
        if c.id == ancestro_id or c.parent_id == ancestro_id:
            return c
    return None


def crearia_ciclo(cat_id: int, nuevo_padre_id: int, categorias: dict) -> bool:
    """True si colgar `cat_id` de `nuevo_padre_id` la dejaria colgando de si misma.

    Un ciclo (A cuelga de B y B de A) dejaba en un bucle infinito cada calculo
    que sube hasta la categoria raiz: panel, presupuesto y tendencia.
    """
    actual, vistos = categorias.get(nuevo_padre_id), set()
    while actual is not None and actual.id not in vistos:
        if actual.id == cat_id:
            return True
        vistos.add(actual.id)
        actual = categorias.get(actual.parent_id) if actual.parent_id else None
    return False
