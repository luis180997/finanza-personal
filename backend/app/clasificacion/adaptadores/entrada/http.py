"""Rutas de categorias y reglas. Solo traducen HTTP <-> caso de uso."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.clasificacion.adaptadores import fabrica
from app.clasificacion.adaptadores.entrada.esquemas import (
    CategoryIn,
    CategoryOut,
    RuleIn,
    RuleOut,
)
from app.clasificacion.aplicacion.catalogo import ServicioCatalogo
from app.clasificacion.dominio.entidades import Rule
from app.compartido.dinero import to_amount
from app.plataforma.db import get_session

router = APIRouter()


def _catalogo(session: Session = Depends(get_session)) -> ServicioCatalogo:
    return fabrica.catalogo(session)


# ------------------------------------------------------------------------ categorias
@router.get("/categorias", response_model=list[CategoryOut], tags=["catalogos"])
def listar_categorias(catalogo: ServicioCatalogo = Depends(_catalogo)):
    return catalogo.listar_categorias()


@router.post("/categorias", response_model=CategoryOut, status_code=201, tags=["catalogos"])
def crear_categoria(datos: CategoryIn, catalogo: ServicioCatalogo = Depends(_catalogo)):
    return catalogo.crear_categoria(datos.model_dump())


@router.patch("/categorias/{cat_id}", response_model=CategoryOut, tags=["catalogos"])
def editar_categoria(
    cat_id: int, datos: CategoryIn, catalogo: ServicioCatalogo = Depends(_catalogo),
):
    return catalogo.editar_categoria(cat_id, datos.model_dump(exclude_unset=True))


@router.delete("/categorias/{cat_id}", status_code=204, tags=["catalogos"])
def borrar_categoria(
    cat_id: int,
    mover_a: int | None = Query(
        None, description="Categoria a la que pasan sus movimientos, reglas y tope",
    ),
    catalogo: ServicioCatalogo = Depends(_catalogo),
):
    catalogo.borrar_categoria(cat_id, mover_a)


# --------------------------------------------------------------------------- reglas
def _regla_out(r: Rule) -> RuleOut:
    return RuleOut(
        id=r.id, name=r.name, priority=r.priority, active=r.active, field=r.field,
        op=r.op, value=r.value, direction=r.direction,
        min_amount=to_amount(r.min_amount_cents) if r.min_amount_cents else None,
        max_amount=to_amount(r.max_amount_cents) if r.max_amount_cents else None,
        set_category_id=r.set_category_id, set_necessity=r.set_necessity,
        set_merchant=r.set_merchant, set_recurring=r.set_recurring, stop=r.stop, hits=r.hits,
    )


@router.get("/reglas", response_model=list[RuleOut], tags=["reglas"])
def listar_reglas(catalogo: ServicioCatalogo = Depends(_catalogo)):
    return [_regla_out(r) for r in catalogo.listar_reglas()]


@router.post("/reglas", response_model=RuleOut, status_code=201, tags=["reglas"])
def crear_regla(datos: RuleIn, catalogo: ServicioCatalogo = Depends(_catalogo)):
    return _regla_out(catalogo.crear_regla(datos.model_dump()))


@router.patch("/reglas/{regla_id}", response_model=RuleOut, tags=["reglas"])
def editar_regla(regla_id: int, datos: RuleIn, catalogo: ServicioCatalogo = Depends(_catalogo)):
    return _regla_out(catalogo.editar_regla(regla_id, datos.model_dump(exclude_unset=True)))


@router.delete("/reglas/{regla_id}", status_code=204, tags=["reglas"])
def borrar_regla(regla_id: int, catalogo: ServicioCatalogo = Depends(_catalogo)):
    catalogo.borrar_regla(regla_id)
