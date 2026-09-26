"""Rutas de movimientos, cuentas y papelera. Solo traducen HTTP <-> caso de uso."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.compartido.dinero import to_amount
from app.compartido.tipos import Direction, Necessity, Source, TxStatus
from app.movimientos.adaptadores import fabrica
from app.movimientos.adaptadores.entrada.esquemas import (
    AccountIn,
    AccountOut,
    AccountPatch,
    BulkAction,
    PaginaTransacciones,
    TransactionIn,
    TransactionOut,
    TransactionPatch,
)
from app.movimientos.aplicacion.cuentas import ServicioCuentas
from app.movimientos.aplicacion.movimientos import ServicioMovimientos
from app.movimientos.aplicacion.papelera import ServicioPapelera
from app.movimientos.aplicacion.puertos import FiltrosMovimientos
from app.movimientos.dominio import revision
from app.movimientos.dominio.entidades import Transaction
from app.plataforma.config import settings
from app.plataforma.db import get_session

router = APIRouter()


def _movimientos(session: Session = Depends(get_session)) -> ServicioMovimientos:
    return fabrica.movimientos(session)


def _cuentas(session: Session = Depends(get_session)) -> ServicioCuentas:
    return fabrica.cuentas(session)


def _papelera(session: Session = Depends(get_session)) -> ServicioPapelera:
    return fabrica.papelera(session)


def to_out(tx: Transaction, cuentas: dict, categorias: dict) -> TransactionOut:
    cat = categorias.get(tx.category_id)
    padre = categorias.get(cat.parent_id) if cat and cat.parent_id else None
    cuenta = cuentas.get(tx.account_id)

    # Solo se calculan para lo que esta por revisar: en un listado de 500 filas
    # confirmadas seria trabajo tirado.
    razones = (
        revision.motivos(
            tx, cat, cuenta.name if cuenta else None,
            moneda_base=settings.base_currency,
            confianza_del_parser=fabrica.confianza_del_parser,
        )
        if tx.status == TxStatus.por_revisar
        else []
    )

    return TransactionOut(
        id=tx.id,
        occurred_at=tx.occurred_at,
        booking_date=tx.booking_date,
        amount=to_amount(tx.amount_cents),
        currency=tx.currency,
        direction=tx.direction,
        account_id=tx.account_id,
        account_name=cuenta.name if cuenta else None,
        payment_method=tx.payment_method,
        category_id=tx.category_id,
        category_name=cat.name if cat else None,
        category_parent=padre.name if padre else (cat.name if cat else None),
        category_color=cat.color if cat else None,
        merchant=tx.merchant,
        merchant_raw=tx.merchant_raw,
        description=tx.description,
        operation_number=tx.operation_number,
        necessity=tx.necessity,
        tags=tx.tags or [],
        notes=tx.notes,
        is_recurring=tx.is_recurring,
        source=tx.source,
        status=tx.status,
        confidence=tx.confidence,
        parser=tx.parser,
        email_id=tx.email_id,
        duplicate_of_id=tx.duplicate_of_id,
        locked_by_user=tx.locked_by_user,
        motivos=razones,
        motivo_resumen=revision.resumen_motivo(razones) if razones else None,
    )


def _salida(servicio: ServicioMovimientos, tx: Transaction) -> TransactionOut:
    cuentas, categorias = servicio.mapas()
    return to_out(tx, cuentas, categorias)


# ------------------------------------------------------------------------ movimientos
@router.get("/movimientos", response_model=PaginaTransacciones, tags=["movimientos"])
def listar(
    servicio: ServicioMovimientos = Depends(_movimientos),
    desde: date | None = None,
    hasta: date | None = None,
    direccion: Direction | None = None,
    estado: TxStatus | None = None,
    cuenta_id: int | None = None,
    categoria_id: int | None = None,
    necesidad: Necessity | None = None,
    origen: Source | None = None,
    buscar: str | None = None,
    pagina: int = Query(1, ge=1),
    tamano: int = Query(50, ge=1, le=500),
    orden: str = Query("fecha_desc", pattern="^(fecha_desc|fecha_asc|monto_desc|monto_asc)$"),
):
    filtros = FiltrosMovimientos(
        desde=desde, hasta=hasta, direccion=direccion, estado=estado, cuenta_id=cuenta_id,
        categoria_id=categoria_id, necesidad=necesidad, origen=origen, buscar=buscar,
    )
    resultado = servicio.listar(filtros, pagina, tamano, orden)
    cuentas, categorias = servicio.mapas()
    return PaginaTransacciones(
        items=[to_out(t, cuentas, categorias) for t in resultado.items],
        total=resultado.total,
        pagina=pagina,
        tamano=tamano,
        suma_gastos=to_amount(resultado.suma_gastos_cents),
        suma_ingresos=to_amount(resultado.suma_ingresos_cents),
    )


@router.post("/movimientos", response_model=TransactionOut, status_code=201, tags=["movimientos"])
def crear(datos: TransactionIn, servicio: ServicioMovimientos = Depends(_movimientos)):
    """Alta manual. Es la puerta de entrada de los gastos en efectivo."""
    return _salida(servicio, servicio.registrar_manual(datos.model_dump()))


@router.patch("/movimientos/{tx_id}", response_model=TransactionOut, tags=["movimientos"])
def editar(
    tx_id: int, datos: TransactionPatch, servicio: ServicioMovimientos = Depends(_movimientos),
):
    return _salida(servicio, servicio.editar(tx_id, datos.model_dump(exclude_unset=True)))


@router.post("/movimientos/lote", tags=["movimientos"])
def editar_lote(datos: BulkAction, servicio: ServicioMovimientos = Depends(_movimientos)):
    afectados = servicio.editar_lote(datos.ids, datos.category_id, datos.necessity, datos.status)
    return {"afectados": afectados}


@router.delete("/movimientos/{tx_id}", status_code=204, tags=["movimientos"])
def borrar(tx_id: int, servicio: ServicioMovimientos = Depends(_movimientos)):
    """Un registro manual se borra de verdad; uno del banco o del Excel se descarta."""
    servicio.borrar(tx_id)


@router.get("/movimientos/revision", response_model=list[TransactionOut], tags=["movimientos"])
def cola_revision(
    servicio: ServicioMovimientos = Depends(_movimientos),
    limite: int = Query(100, ge=1, le=500),
):
    """Bandeja de entrada: lo que el sistema no supo clasificar con seguridad."""
    items = servicio.por_revisar(limite)
    cuentas, categorias = servicio.mapas()
    return [to_out(t, cuentas, categorias) for t in items]


# ---------------------------------------------------------------------------- cuentas
@router.get("/cuentas", response_model=list[AccountOut], tags=["catalogos"])
def listar_cuentas(servicio: ServicioCuentas = Depends(_cuentas)):
    return servicio.listar()


@router.post("/cuentas", response_model=AccountOut, status_code=201, tags=["catalogos"])
def crear_cuenta(datos: AccountIn, servicio: ServicioCuentas = Depends(_cuentas)):
    return servicio.crear(datos.model_dump())


@router.patch("/cuentas/{cuenta_id}", response_model=AccountOut, tags=["catalogos"])
def editar_cuenta(
    cuenta_id: int, datos: AccountPatch, servicio: ServicioCuentas = Depends(_cuentas),
):
    """Edicion parcial: solo cambia lo que mandas."""
    return servicio.editar(cuenta_id, datos.model_dump(exclude_unset=True))


@router.delete("/cuentas/{cuenta_id}", status_code=204, tags=["catalogos"])
def borrar_cuenta(cuenta_id: int, servicio: ServicioCuentas = Depends(_cuentas)):
    servicio.borrar(cuenta_id)


# --------------------------------------------------------------------------- papelera
@router.get("/papelera", tags=["sistema"])
def papelera(
    servicio: ServicioPapelera = Depends(_papelera), limite: int = Query(50, ge=1, le=500),
):
    """Movimientos borrados, del mas reciente al mas antiguo.

    Los copia un trigger de SQLite, asi que aparece todo lo borrado, lo haya
    borrado la app, un script o cualquier otro proceso.
    """
    return servicio.listar(limite)


@router.post("/papelera/{papelera_id}/restaurar", tags=["sistema"], status_code=201)
def restaurar(papelera_id: int, servicio: ServicioPapelera = Depends(_papelera)):
    return {"id": servicio.restaurar(papelera_id).id}
