"""Importar estados de cuenta y conciliarlos con lo que llego por correo.

Cada mes:

1. Se lee y valida el PDF (`revision.py`): si no cuadra consigo mismo, no entra.
2. Tiene que seguir al ultimo importado, sin huecos, y encadenar con el: las
   posiciones del mes anterior mas lo operado dan las de este.
3. Cada fila se traduce en una operacion (`libro.del_estado`) y el mes tiene que
   cuadrar en efectivo con lo que dice el documento.
4. Conciliacion. Cada fila oficial busca su correo:
     - si lo encuentra, la operacion del correo pasa a OFICIAL con los importes
       del estado y conserva la hora y la fecha real del correo;
     - si no, se crea la operacion oficial (con la fecha deducida si es una
       compra o venta: el estado solo trae la de liquidacion).
   Lo que llego por correo en ese mes y el estado no recoge queda DESCARTADO
   (un correo repetido, una orden que no se ejecuto).

La vista previa recorre exactamente el mismo camino y al final deshace: lo que se
ve antes de confirmar es lo que se guardara.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from app.compartido.errores import DatoInvalido
from app.compartido.puertos import UnidadDeTrabajo
from app.inversiones.aplicacion.puertos import LectorDePdf, RepositorioInversiones
from app.inversiones.aplicacion import saldo_inicial
from app.inversiones.aplicacion.revision import ServicioRevision
from app.inversiones.dominio import cartera, libro, validacion
from app.inversiones.dominio.entidades import (
    EstadoCuentaImportado, EstadoOperacion, FuenteOperacion, Operacion, PosicionCierre, TipoOperacion,
    archivo_de,
)
from app.inversiones.dominio.estado_cuenta import EstadoDeCuenta, Movimiento, Posicion, Seccion

log = logging.getLogger("finanzas.inversiones")
_T = TipoOperacion


@dataclass
class Diferencia:
    simbolo: str
    segun_app_micro: int
    segun_estado_micro: int
    precio_micro: int            # el de cierre de mes del estado

    @property
    def valor_cents(self) -> int:
        return round((self.segun_app_micro - self.segun_estado_micro) * self.precio_micro / 10**12 * 100)


@dataclass
class Comparacion:
    """Lo que la app calculaba (con los correos) frente a lo que dice el estado.

    Es la respuesta a "cuanto se desvio el seguimiento por correo": diferencias de
    acciones por valor y de efectivo, y su suma en dolares al precio de cierre.
    """

    seguido_por_correo: bool     # hubo correos de ese mes antes de importarlo
    efectivo_app_cents: int
    efectivo_estado_cents: int
    acciones: list[Diferencia]

    @property
    def efectivo_cents(self) -> int:
        return self.efectivo_app_cents - self.efectivo_estado_cents

    @property
    def total_cents(self) -> int:
        return self.efectivo_cents + sum(d.valor_cents for d in self.acciones)


@dataclass
class ResultadoDocumento:
    nombre: str
    periodo: str | None
    estado: str                       # nuevo | ya_importado | error
    errores: list[str] = field(default_factory=list)
    operaciones_nuevas: int = 0
    conciliadas_con_correo: int = 0
    correos_descartados: int = 0
    comparacion: Comparacion | None = None


@dataclass
class ResultadoImportacion:
    documentos: list[ResultadoDocumento]
    errores: list[str]
    confirmado: bool

    @property
    def importables(self) -> int:
        return sum(d.estado == "nuevo" for d in self.documentos)


class ServicioEstados:
    def __init__(self, lector: LectorDePdf, repo: RepositorioInversiones, uow: UnidadDeTrabajo):
        self.revision = ServicioRevision(lector)
        self.repo = repo
        self.uow = uow

    def previsualizar(self, documentos: Iterable[tuple[str, bytes]]) -> ResultadoImportacion:
        resultado = self._procesar(list(documentos))
        self.uow.deshacer()
        resultado.confirmado = False
        return resultado

    def importar(self, documentos: Iterable[tuple[str, bytes]]) -> ResultadoImportacion:
        resultado = self._procesar(list(documentos))
        if resultado.errores or any(d.estado == "error" for d in resultado.documentos):
            self.uow.deshacer()
            raise DatoInvalido("No se importo nada: " + "; ".join(
                resultado.errores + [f"{d.nombre}: {e}" for d in resultado.documentos for e in d.errores]
            ))
        if not resultado.importables:
            raise DatoInvalido("No hay estados nuevos: todos estaban ya importados.")
        self.uow.confirmar()
        resultado.confirmado = True
        log.info("estados de cuenta importados: %s", [d.periodo for d in resultado.documentos
                                                      if d.estado == "nuevo"])
        return resultado

    # ------------------------------------------------------------------ proceso

    def _procesar(self, documentos: list[tuple[str, bytes]]) -> ResultadoImportacion:
        importados = self.repo.estados()
        huellas = {e.huella for e in importados}
        fines = {e.fin for e in importados}

        informe = self.revision.revisar(documentos)
        resultados: dict[str, ResultadoDocumento] = {}
        nuevos: list[tuple[str, EstadoDeCuenta, str]] = []
        for doc in informe.documentos:
            periodo = doc.estado.periodo if doc.estado else None
            r = resultados[doc.nombre] = ResultadoDocumento(doc.nombre, periodo, "nuevo")
            if doc.huella in huellas or (doc.estado and doc.estado.fin in fines):
                r.estado = "ya_importado"
            elif not doc.valido:
                r.estado = "error"
                r.errores = [str(e) for e in doc.errores]
            else:
                nuevos.append((doc.nombre, doc.estado, doc.huella))

        errores: list[str] = []
        nuevos.sort(key=lambda n: n[1].inicio)
        if nuevos:
            errores = self._continuidad(importados, [e for _, e, _ in nuevos])
        if not errores:
            simbolos = self._simbolos([e for _, e, _ in nuevos])
            for nombre, estado, huella in nuevos:
                try:
                    self._importar_uno(nombre, estado, huella, simbolos, resultados[nombre])
                except (libro.FilaDesconocida, DatoInvalido) as exc:
                    resultados[nombre].estado = "error"
                    resultados[nombre].errores.append(str(exc))
                    break
            self._completar_simbolos(simbolos)
            self.uow.volcar()
            saldo_inicial.ajustar(self.repo)
        orden = {nombre: i for i, (nombre, _, _) in enumerate(nuevos)}
        return ResultadoImportacion(
            documentos=sorted(resultados.values(), key=lambda r: (orden.get(r.nombre, -1), r.periodo or "")),
            errores=errores, confirmado=False,
        )

    def _continuidad(self, importados: list[EstadoCuentaImportado],
                     nuevos: list[EstadoDeCuenta]) -> list[str]:
        """Los nuevos siguen al ultimo importado, sin huecos, y encadenan con el."""
        serie = list(nuevos)
        if importados:
            ultimo = importados[-1]
            if nuevos[0].inicio != ultimo.fin + timedelta(days=1):
                return [f"El siguiente estado tiene que empezar el {ultimo.fin + timedelta(days=1)}, "
                        f"pero el primero que subiste empieza el {nuevos[0].inicio}."]
            serie.insert(0, self._reconstruir(ultimo))
        return [str(e) for e in validacion.validar_serie(serie)]

    def _reconstruir(self, guardado: EstadoCuentaImportado) -> EstadoDeCuenta:
        """El ultimo estado importado, con lo que hace falta para encadenar el siguiente:
        sus posiciones y lo que quedo pendiente de liquidar."""
        estado = EstadoDeCuenta(inicio=guardado.inicio, fin=guardado.fin)
        for p in self.repo.posiciones_de(guardado.id):
            estado.posiciones.append(Posicion(
                simbolo=p.simbolo, nombre=p.nombre, tipo_cuenta=p.tipo_cuenta,
                cantidad=_decimal(p.cantidad_micro), precio=_decimal(p.precio_micro),
                valor_cents=p.valor_cents,
            ))
        for op in self.repo.operaciones():
            if (op.estado_cuenta_id == guardado.id and op.fecha_liquidacion is None
                    and op.tipo in (_T.compra, _T.venta)):
                estado.movimientos.append(Movimiento(
                    seccion=Seccion.pendientes, codigo="BOUGHT" if op.tipo is _T.compra else "SOLD",
                    fecha=op.fecha, tipo_cuenta="C", descripcion=op.nombre or "",
                    cantidad=_decimal(op.cantidad_micro),
                    debito_cents=-op.monto_cents if op.monto_cents < 0 else 0,
                    credito_cents=op.monto_cents if op.monto_cents > 0 else 0,
                ))
        return estado

    def _simbolos(self, nuevos: list[EstadoDeCuenta]) -> dict[str, str]:
        """Nombre del valor -> simbolo, de todas las posiciones conocidas."""
        simbolos = {p.nombre: p.simbolo for p in self.repo.todas_las_posiciones()}
        for e in nuevos:
            simbolos.update({p.nombre: p.simbolo for p in e.posiciones})
        for op in self.repo.operaciones():         # lo aprendido de correos anteriores
            if op.simbolo and op.nombre and op.fuente is FuenteOperacion.correo and op.nombre != op.simbolo:
                simbolos.setdefault(op.nombre, op.simbolo)
        return simbolos

    def _importar_uno(self, nombre: str, estado: EstadoDeCuenta, huella: str,
                      simbolos: dict[str, str], r: ResultadoDocumento) -> None:
        filas = libro.del_estado(estado, simbolos)
        descuadre = libro.cuadre_de_efectivo(estado, filas)
        if descuadre:
            raise DatoInvalido(
                f"las operaciones no explican el efectivo del mes: faltan {descuadre / 100:.2f}"
            )

        caja_apertura, caja = estado.portada["caja"]
        guardado = EstadoCuentaImportado(
            inicio=estado.inicio, fin=estado.fin, huella=huella, archivo=archivo_de(estado.fin),
            caja_cents=caja,
            caja_apertura_cents=caja_apertura, fdic_apertura_cents=estado.portada.get("fdic", (0, 0))[0],
            fdic_cents=estado.fdic_cents, valores_cents=sum(p.valor_cents for p in estado.posiciones),
        )
        self.repo.agregar(guardado)
        self.uow.volcar()
        for p in estado.posiciones:
            self.repo.agregar(PosicionCierre(
                estado_cuenta_id=guardado.id, simbolo=p.simbolo, nombre=p.nombre, tipo_cuenta=p.tipo_cuenta,
                cantidad_micro=libro.micro(p.cantidad), precio_micro=libro.micro(p.precio),
                valor_cents=p.valor_cents, valor_anterior_cents=p.valor_anterior_cents,
            ))

        existentes = self.repo.operaciones()
        r.comparacion = _comparar(existentes, estado)
        provisionales = [o for o in existentes if o.estado is EstadoOperacion.provisional]
        pendientes_previas = [
            o for o in existentes
            if o.estado is EstadoOperacion.oficial and o.fecha_liquidacion is None
            and o.tipo in (_T.compra, _T.venta)
        ]
        for fila in filas:
            if fila.op.tipo in (_T.compra, _T.venta) and not fila.pendiente:
                previa = next((o for o in pendientes_previas if libro.misma_liquidada(o, fila)), None)
                if previa is not None:          # ya entro el mes pasado como pendiente
                    previa.fecha_liquidacion = fila.op.fecha_liquidacion
                    pendientes_previas.remove(previa)
                    continue
            pareja = _mejor_pareja(fila, provisionales)
            if pareja is not None:
                libro.oficializar(pareja, fila, guardado.id)
                provisionales.remove(pareja)
                r.conciliadas_con_correo += 1
                if pareja.simbolo and fila.descripcion and fila.descripcion not in simbolos:
                    simbolos[fila.descripcion] = pareja.simbolo
                continue
            fila.op.estado_cuenta_id = guardado.id
            self.repo.agregar(fila.op)
            r.operaciones_nuevas += 1

        for o in provisionales:
            desde, hasta = libro.ventana_de_descarte(estado.inicio, estado.fin, o.tipo)
            if desde <= o.fecha <= hasta:
                o.estado = EstadoOperacion.descartada
                o.nota = f"No figura en el estado de cuenta de {estado.periodo}"
                r.correos_descartados += 1
        self.uow.volcar()

    def _completar_simbolos(self, simbolos: dict[str, str]) -> None:
        """Operaciones oficiales sin simbolo cuyo nombre se aprendio despues."""
        for op in self.repo.operaciones():
            if op.simbolo is None and op.nombre in simbolos:
                op.simbolo = simbolos[op.nombre]


def _comparar(existentes: list[Operacion], estado: EstadoDeCuenta) -> Comparacion:
    calculada = cartera.calcular_liquidado(existentes, estado.fin)
    app = {p.simbolo: p.cantidad_micro for p in calculada.abiertas() if p.simbolo}
    oficial: dict[str, int] = {}
    precios: dict[str, int] = {}
    for p in estado.posiciones:
        oficial[p.simbolo] = oficial.get(p.simbolo, 0) + libro.micro(p.cantidad)
        precios[p.simbolo] = libro.micro(p.precio)
    diferencias = [
        Diferencia(s, app.get(s, 0), oficial.get(s, 0), precios.get(s, 0))
        for s in sorted(set(app) | set(oficial)) if app.get(s, 0) != oficial.get(s, 0)
    ]
    seguido = any(
        o.estado is EstadoOperacion.provisional and estado.inicio <= o.fecha <= estado.fin for o in existentes
    )
    return Comparacion(
        seguido_por_correo=seguido, efectivo_app_cents=calculada.efectivo_cents,
        efectivo_estado_cents=estado.portada["caja"][1] + estado.fdic_cents, acciones=diferencias,
    )


def _mejor_pareja(fila: libro.FilaOficial, provisionales: list[Operacion]) -> Operacion | None:
    candidatas = [o for o in provisionales if libro.emparejan(o, fila.op, fila.pendiente)]
    if not candidatas:
        return None
    # Ante dos iguales (dos ordenes identicas), la mas antigua primero.
    return min(candidatas, key=lambda o: (o.fecha, o.ejecutada_at or datetime.min, o.id or 0))


def _decimal(micro_valor: int | None) -> Decimal | None:
    return None if micro_valor is None else Decimal(micro_valor) / libro.MICRO
