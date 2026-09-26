"""Rutas del panel, de Tendencia y de los presupuestos. Solo traducen HTTP <-> caso de uso."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from app.analitica.adaptadores import fabrica
from app.analitica.adaptadores.entrada.esquemas import BudgetIn, BudgetOut, MetaAhorroIn
from app.analitica.aplicacion.presupuestos import ServicioPresupuestos
from app.analitica.aplicacion.resumen import ServicioAnalitica
from app.analitica.dominio.entidades import Budget
from app.analitica.dominio.periodos import Rango
from app.clasificacion.dominio.entidades import Category
from app.compartido.corte import ANIO_MAX, ANIO_MIN
from app.compartido.dinero import to_amount
from app.plataforma.db import get_session

router = APIRouter()


def _analitica(session: Session = Depends(get_session)) -> ServicioAnalitica:
    return fabrica.analitica(session)


def _presupuestos(session: Session = Depends(get_session)) -> ServicioPresupuestos:
    return fabrica.presupuestos(session)


# Mientras se teclea "2022" en un <input type="date">, el navegador emite las
# fechas del ano 2, 20 y 202. El ano 2 reventaba el calculo del periodo anterior
# (no hay fechas antes del ano 1) y el panel mostraba un error generico. Fuera de
# este margen no puede haber datos (tampoco se admiten al registrar un movimiento),
# asi que se rechaza diciendo por que. Los limites viven en app/compartido/corte.py.


def _validar_fechas(*fechas: date | None) -> None:
    for f in fechas:
        if f is not None and not ANIO_MIN <= f.year <= ANIO_MAX:
            raise HTTPException(
                400,
                f"Fecha fuera de rango: {f.isoformat()}. Usa anos entre {ANIO_MIN} y {ANIO_MAX}.",
            )


# --------------------------------------------------------------------------- resumen
@router.get("/resumen", tags=["resumen"])
def resumen(
    servicio: ServicioAnalitica = Depends(_analitica),
    desde: date | None = Query(None, description="Por defecto: primer dia del mes actual"),
    hasta: date | None = Query(None, description="Por defecto: ultimo dia del mes actual"),
):
    _validar_fechas(desde, hasta)
    if (desde is None) != (hasta is None):
        # Con una sola fecha se ignoraba en silencio y salia el mes actual, que se
        # leia como si fuera el periodo pedido.
        raise HTTPException(400, "Indica las dos fechas (desde y hasta) o ninguna.")
    if desde and hasta:
        # Un rango al reves daba un panel entero a cero, que se lee como "no
        # gastaste nada" en vez de "las fechas estan cambiadas".
        if desde > hasta:
            raise HTTPException(400, "La fecha 'desde' es posterior a 'hasta'.")
        return servicio.resumen(Rango(desde, hasta))
    return servicio.resumen_del_mes_actual()


@router.get("/resumen/mensual", tags=["resumen"])
def mensual(
    servicio: ServicioAnalitica = Depends(_analitica), meses: int = Query(12, ge=1, le=36),
):
    return servicio.serie_mensual(meses)


@router.get("/resumen/periodos", tags=["resumen"])
def periodos(
    servicio: ServicioAnalitica = Depends(_analitica),
    agrupar: str = Query("mes", pattern="^(mes|anio)$"),
    desde: date | None = Query(None, description="Por defecto: desde tu primer movimiento"),
    hasta: date | None = Query(None, description="Por defecto: hasta hoy"),
    categoria: int | None = Query(
        None, description="Solo los gastos de esta categoria y sus subcategorias"
    ),
):
    """Gasto por mes o por anio en el rango que pidas.

    Sin `desde`/`hasta` cubre todo tu historial, que es lo que uno quiere ver
    cuando pregunta "cuanto gaste cada mes".
    """
    _validar_fechas(desde, hasta)
    completo = servicio.rango_de_los_datos()
    rango = Rango(desde or completo.desde, hasta or completo.hasta)
    if rango.desde > rango.hasta:
        raise HTTPException(400, "La fecha 'desde' es posterior a 'hasta'.")
    # Un id que no existe daria una serie entera a cero, que se lee como "no
    # gastaste nada en esa categoria".
    if categoria is not None and not servicio.existe_categoria(categoria):
        raise HTTPException(404, "Categoria no encontrada")
    return servicio.serie_periodos(agrupar, rango, categoria)


# ----------------------------------------------------------------------- presupuestos
def _out(b: Budget, cat: Category) -> BudgetOut:
    return BudgetOut(
        id=b.id, category_id=b.category_id, categoria=cat.name,
        color=cat.color, amount=to_amount(b.amount_cents), active=b.active,
    )


@router.get("/presupuestos", response_model=list[BudgetOut], tags=["presupuesto"])
def listar(servicio: ServicioPresupuestos = Depends(_presupuestos)):
    salida = [_out(b, cat) for b, cat in servicio.listar()]
    return sorted(salida, key=lambda x: x.amount, reverse=True)


@router.put("/presupuestos", response_model=BudgetOut, tags=["presupuesto"])
def guardar(datos: BudgetIn, servicio: ServicioPresupuestos = Depends(_presupuestos)):
    """Crea o actualiza el tope de una categoria."""
    return _out(*servicio.guardar(datos.category_id, datos.amount, datos.active))


@router.delete("/presupuestos/{budget_id}", status_code=204, tags=["presupuesto"])
def borrar(budget_id: int, servicio: ServicioPresupuestos = Depends(_presupuestos)):
    servicio.borrar(budget_id)


@router.get("/meta-ahorro", tags=["presupuesto"])
def leer_meta(servicio: ServicioPresupuestos = Depends(_presupuestos)):
    return {"amount": to_amount(servicio.meta_cents())}


@router.put("/meta-ahorro", tags=["presupuesto"])
def guardar_meta(datos: MetaAhorroIn, servicio: ServicioPresupuestos = Depends(_presupuestos)):
    return {"amount": to_amount(servicio.guardar_meta(datos.amount))}
