"""Con que empieza el primer estado de cuenta importado: efectivo y acciones.

Antes del primer estado solo hay correos. Lo que ellos cuentan tiene que dar lo
que habia al abrir ese estado; lo que falte se anota de forma visible:

- EFECTIVO. Sin correos anteriores, el saldo inicial es dinero que pusiste: un
  deposito. Con correos anteriores, la diferencia es algo que no llego por correo
  (una ejecucion sin aviso, una comision): un ajuste de saldo, que no es aporte.
- ACCIONES. Las que habia al empezar (las del cierre menos lo operado en el mes)
  y los correos no explican entran como "posicion inicial": no mueven efectivo,
  su costo es su valor de mercado de ese dia (el estado lo trae en la columna del
  mes anterior) y cuentan como aporte.

Se recalcula cada vez que cambia lo que hay antes del primer estado (al importar
estados y al leer correos), asi el resultado no depende del orden.
"""
from __future__ import annotations

from datetime import timedelta

from app.inversiones.aplicacion.puertos import RepositorioInversiones
from app.inversiones.dominio import cartera
from app.inversiones.dominio.entidades import (
    EstadoCuentaImportado, EstadoOperacion, FuenteOperacion, Operacion, TipoOperacion,
)

NOMBRE = "Saldo inicial"
_T = TipoOperacion
_NOTA_AJUSTE = (
    "Diferencia entre lo que cuentan los correos anteriores al primer estado de cuenta "
    "y el saldo con el que empieza ese estado"
)
_NOTA_DEPOSITO = "Saldo con el que empieza el primer estado de cuenta"
_NOTA_POSICION = (
    "Acciones con las que empieza el primer estado de cuenta, sin historia anterior. "
    "Su costo es su valor de mercado de ese dia"
)


def _oficial(**campos) -> Operacion:
    return Operacion(estado=EstadoOperacion.oficial, fuente=FuenteOperacion.estado_cuenta, **campos)


def ajustar(repo: RepositorioInversiones) -> None:
    estados = repo.estados()
    if not estados:
        return
    primero = estados[0]
    ops = repo.operaciones()
    efectivo = next((o for o in ops if o.estado_cuenta_id == primero.id and o.nombre == NOMBRE
                     and o.tipo in (_T.deposito, _T.ajuste_saldo)), None)
    iniciales = {o.simbolo: o for o in ops if o.tipo is _T.posicion_inicial}
    otras = [o for o in ops if o is not efectivo and o.tipo is not _T.posicion_inicial]
    dia_previo = primero.inicio - timedelta(days=1)
    antes = cartera.calcular_liquidado(otras, dia_previo)

    for simbolo, (cantidad, precio, nombre) in _acciones_al_empezar(repo, primero, otras).items():
        conocida = antes.posiciones[simbolo].cantidad_micro if simbolo in antes.posiciones else 0
        falta = cantidad - conocida
        op = iniciales.get(simbolo)
        if op is None and falta > 0:
            repo.agregar(_oficial(
                tipo=_T.posicion_inicial, simbolo=simbolo, nombre=nombre, fecha=dia_previo,
                cantidad_micro=falta, precio_micro=precio, nota=_NOTA_POSICION, estado_cuenta_id=primero.id,
            ))
        elif op is not None:
            op.cantidad_micro, op.precio_micro = max(falta, 0), precio

    hay_previas = any(cartera.fecha_de_liquidacion(o) <= dia_previo for o in cartera.cuentan(otras))
    diferencia = (primero.caja_apertura_cents + primero.fdic_apertura_cents) - antes.efectivo_cents
    tipo, nota = (_T.ajuste_saldo, _NOTA_AJUSTE) if hay_previas else (_T.deposito, _NOTA_DEPOSITO)
    if efectivo is None:
        if diferencia:
            repo.agregar(_oficial(tipo=tipo, fecha=dia_previo, monto_cents=diferencia, nombre=NOMBRE,
                                  nota=nota, estado_cuenta_id=primero.id))
    else:
        efectivo.tipo, efectivo.monto_cents, efectivo.nota = tipo, diferencia, nota


def _acciones_al_empezar(repo: RepositorioInversiones, primero: EstadoCuentaImportado,
                         ops: list[Operacion]) -> dict[str, tuple[int, int, str]]:
    """simbolo -> (acciones al abrir el estado, precio de ese dia en micro, nombre).

    Acciones al abrir = las del cierre - compras - splits + ventas liquidadas en el
    mes. El precio sale del valor de mercado del mes anterior que trae el estado;
    si el valor ya no estaba al cierre (se vendio entero), del precio de su venta.
    """
    cierre: dict[str, list] = {}
    for p in repo.posiciones_de(primero.id):
        actual = cierre.setdefault(p.simbolo, [0, 0, p.nombre])
        actual[0] += p.cantidad_micro
        actual[1] += p.valor_anterior_cents or 0
    cambios: dict[str, int] = {}
    precio_de_venta: dict[str, int] = {}
    for o in cartera.cuentan(ops):
        if not o.simbolo or not (primero.inicio <= cartera.fecha_de_liquidacion(o) <= primero.fin):
            continue
        if o.tipo in (_T.compra, _T.split):
            cambios[o.simbolo] = cambios.get(o.simbolo, 0) + (o.cantidad_micro or 0)
        elif o.tipo is _T.venta:
            cambios[o.simbolo] = cambios.get(o.simbolo, 0) - (o.cantidad_micro or 0)
            precio_de_venta.setdefault(o.simbolo, o.precio_micro or 0)
    resultado = {}
    for simbolo in set(cierre) | set(cambios):
        cantidad_cierre, valor_anterior, nombre = cierre.get(simbolo, [0, 0, simbolo])
        al_empezar = cantidad_cierre - cambios.get(simbolo, 0)
        if al_empezar <= 0:
            continue
        if valor_anterior:
            precio = round(valor_anterior / 100 * cartera.MICRO * cartera.MICRO / al_empezar)
        else:
            precio = precio_de_venta.get(simbolo, 0)
        resultado[simbolo] = (al_empezar, precio, nombre)
    return resultado
