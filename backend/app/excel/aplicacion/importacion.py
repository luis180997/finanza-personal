"""Casos de uso del importador del Excel historico: analizar, importar y deshacer.

Dos pasos a proposito: primero **analizar** (no escribe nada) y luego
**confirmar**. Importar cuatro anios de datos a ciegas y descubrir despues que el
mapeo estaba mal es exactamente el error que este flujo evita.
"""
from __future__ import annotations

from datetime import date

from app.compartido.corte import (
    FECHA_INICIO_AUTOMATIZADO_TEXTO,
    ULTIMO_DIA_EXCEL,
    ULTIMO_DIA_EXCEL_TEXTO,
)
from app.compartido.errores import Conflicto
from app.compartido.puertos import UnidadDeTrabajo
from app.compartido.tipos import Direction
from app.excel.aplicacion.puertos import (
    CatalogoDeCategorias,
    CatalogoDeCuentas,
    LectorDeLibro,
    MovimientosDeLotes,
    RepositorioLotes,
)
from app.excel.dominio.entidades import ImportBatch
from app.excel.dominio.mapeo import (
    COLUMNAS,
    DERIVADAS,
    Analisis,
    FilaPrevista,
    categoria_de_celda,
    clasificar_observacion,
    elegir_hoja,
    fecha_de,
    indice_fecha,
    indice_observacion,
    limite_de_importacion,
    mapeo_de,
    movimiento_del_excel,
    norm,
    numero,
    observacion_de,
)


class ServicioImportacion:
    def __init__(
        self,
        *,
        lector: LectorDeLibro,
        lotes: RepositorioLotes,
        movimientos: MovimientosDeLotes,
        categorias: CatalogoDeCategorias,
        cuentas: CatalogoDeCuentas,
        uow: UnidadDeTrabajo,
    ):
        self.lector = lector
        self.lotes = lotes
        self.movimientos = movimientos
        self.categorias = categorias
        self.cuentas = cuentas
        self.uow = uow

    # ----------------------------------------------------------------- analizar
    def analizar(
        self,
        contenido: bytes,
        hoja: str | None = None,
        fecha_hasta: date | None = None,
        fecha_desde: date | None = None,
    ) -> Analisis:
        """Lee el archivo y calcula que pasaria, sin tocar la base de datos.

        `fecha_desde` deja fuera las filas anteriores: sirve para traer solo un mes nuevo
        sin volver a leer lo ya importado (si una fila vieja se hubiera retocado en el
        Excel, su huella cambiaria y entraria duplicada).
        """
        libro = self.lector.abrir(contenido)
        nombres = libro.hojas
        elegida = elegir_hoja(nombres, hoja)

        filas = libro.filas(elegida)
        try:
            cabecera = [norm(c) for c in next(filas)]
        except StopIteration:
            a = Analisis(hoja=elegida, hojas_disponibles=nombres)
            a.avisos.append("La hoja esta vacia.")
            return a

        res = Analisis(hoja=elegida, hojas_disponibles=nombres, columnas_detectadas=cabecera)

        idx_fecha = indice_fecha(cabecera)
        idx_obs = indice_observacion(cabecera)
        if idx_fecha is None:
            res.avisos.append("No se encontro la columna 'Fecha'. Sin ella no se puede importar.")
            return res

        mapeo = mapeo_de(cabecera)
        res.columnas_importadas = [cabecera[i] for i in mapeo]
        res.columnas_derivadas = [c for c in cabecera if c in DERIVADAS]
        res.columnas_sin_mapeo = [
            c for i, c in enumerate(cabecera)
            if c and i != idx_fecha and i != idx_obs and c not in COLUMNAS and c not in DERIVADAS
        ]
        if not mapeo:
            res.avisos.append("Ninguna columna coincide con las conocidas. Revisa la cabecera.")
            return res

        limite = limite_de_importacion(fecha_hasta)
        posteriores_al_corte = 0
        anteriores_al_desde = 0
        for fila in filas:
            res.filas_leidas += 1
            f = fecha_de(fila[idx_fecha]) if idx_fecha < len(fila) else None
            if not f:
                continue
            if f > limite:
                posteriores_al_corte += f > ULTIMO_DIA_EXCEL
                continue
            if fecha_desde and f < fecha_desde:
                anteriores_al_desde += 1
                continue
            res.filas_con_fecha += 1
            res.desde = f if res.desde is None else min(res.desde, f)
            res.hasta = f if res.hasta is None else max(res.hasta, f)

            observacion = observacion_de(fila, idx_obs)
            cat_obs, nec_obs = clasificar_observacion(observacion)

            for idx, (direccion, cat_col, nec_col) in mapeo.items():
                if idx >= len(fila):
                    continue
                monto = numero(fila[idx])
                if monto <= 0:
                    continue

                categoria, necesidad, origen = categoria_de_celda(
                    cat_col, nec_col, direccion, cat_obs, nec_obs,
                )
                if origen == "observacion":
                    res.rescatados_por_observacion += 1
                if categoria == "Sin clasificar":
                    res.sin_clasificar += 1

                res.movimientos += 1
                if direccion == Direction.ingreso:
                    res.total_ingresos += monto
                else:
                    res.total_gastos += monto

                if len(res.muestra) < 40:
                    res.muestra.append(FilaPrevista(
                        fecha=f, columna=cabecera[idx], monto=round(monto, 2),
                        direccion=direccion.value, categoria=categoria,
                        necesidad=necesidad.value if necesidad else None,
                        observacion=observacion, origen_categoria=origen,
                    ))

        res.total_ingresos = round(res.total_ingresos, 2)
        res.total_gastos = round(res.total_gastos, 2)

        if posteriores_al_corte:
            res.avisos.append(
                f"{posteriores_al_corte} fila(s) posteriores al {ULTIMO_DIA_EXCEL_TEXTO} no se "
                f"importan: desde el {FECHA_INICIO_AUTOMATIZADO_TEXTO} mandan los correos y lo que "
                "registras a mano."
            )
        if anteriores_al_desde:
            res.avisos.append(
                f"{anteriores_al_desde} fila(s) anteriores al {fecha_desde:%d/%m/%Y} no se importan: "
                "pediste importar desde esa fecha."
            )

        if res.columnas_derivadas:
            res.avisos.append(
                f"Columnas derivadas que NO se importan (el backend las recalcula): "
                f"{', '.join(res.columnas_derivadas)}."
            )
        if res.columnas_sin_mapeo:
            res.avisos.append(
                f"Columnas sin equivalencia, se ignoran: {', '.join(res.columnas_sin_mapeo)}."
            )
        res.avisos.append(
            "Cada fila del Excel es un dia, no un movimiento suelto. Lo importado es un "
            "agregado diario y queda marcado con origen 'Excel'."
        )
        return res

    # ----------------------------------------------------------------- importar
    def importar(
        self,
        contenido: bytes,
        filename: str,
        hoja: str | None = None,
        cuenta_id: int | None = None,
        usar_observaciones: bool = True,
        fecha_hasta: date | None = None,
        fecha_desde: date | None = None,
    ) -> ImportBatch:
        """Importa de verdad. Idempotente: re-importar el mismo archivo no duplica."""
        analisis = self.analizar(contenido, hoja, fecha_hasta=fecha_hasta, fecha_desde=fecha_desde)
        filas = self.lector.abrir(contenido).filas(analisis.hoja)

        lote = ImportBatch(
            filename=filename, sheet=analisis.hoja,
            date_from=analisis.desde, date_to=analisis.hasta,
        )
        self.lotes.agregar(lote)
        self.uow.confirmar()
        self.uow.refrescar(lote)

        # Una categoria por nombre; con nombres repetidos gana la ultima, como siempre.
        categorias = {c.name: c for c in self.categorias.todas().values()}
        cuenta = self.cuentas.obtener(cuenta_id) if cuenta_id else None

        cabecera = [norm(c) for c in next(filas)]
        idx_fecha = indice_fecha(cabecera)
        idx_obs = indice_observacion(cabecera)
        mapeo = mapeo_de(cabecera)

        # El bucle va por lotes de 300 con commits parciales, para no tener miles de
        # filas colgando en memoria. El precio es que un fallo a mitad no se deshace
        # solo: lo ya confirmado se quedaba en la base con un lote sin cerrar, y el
        # usuario veia un error 400 sin saber que tenia media importacion dentro.
        # Aqui se limpia entera y se relanza el fallo tal cual.
        try:
            return self._importar_filas(
                lote, filas, cabecera, idx_fecha, idx_obs, mapeo, categorias, cuenta,
                usar_observaciones, fecha_hasta=fecha_hasta, fecha_desde=fecha_desde,
            )
        except Exception:
            self.uow.deshacer()
            self.deshacer(lote.id)
            raise

    def _importar_filas(
        self, lote, filas, cabecera, idx_fecha, idx_obs, mapeo, categorias, cuenta,
        usar_observaciones, fecha_hasta: date | None = None, fecha_desde: date | None = None,
    ) -> ImportBatch:
        creados = duplicados = leidas = 0
        limite = limite_de_importacion(fecha_hasta)

        for fila in filas:
            leidas += 1
            f = fecha_de(fila[idx_fecha]) if idx_fecha < len(fila) else None
            if not f:
                continue
            if f > limite:
                continue
            if fecha_desde and f < fecha_desde:
                continue

            observacion = observacion_de(fila, idx_obs)
            cat_obs, nec_obs = (
                clasificar_observacion(observacion) if usar_observaciones else (None, None)
            )

            for idx, (direccion, cat_col, nec_col) in mapeo.items():
                if idx >= len(fila):
                    continue
                monto = numero(fila[idx])
                if monto <= 0:
                    continue

                nombre_cat, necesidad, _ = categoria_de_celda(
                    cat_col, nec_col, direccion, cat_obs, nec_obs,
                )
                cat = categorias.get(nombre_cat)
                tx = movimiento_del_excel(
                    fecha=f, monto=monto, direccion=direccion, etiqueta=cabecera[idx],
                    category_id=cat.id if cat else None, necesidad=necesidad,
                    observacion=observacion, cuenta_id=cuenta.id if cuenta else None,
                    lote_id=lote.id,
                )
                if self.movimientos.existe_huella(tx.dedupe_hash):
                    duplicados += 1
                    continue
                self.movimientos.agregar_importado(tx)
                creados += 1

            if creados % 300 == 0:
                self.uow.confirmar()

        lote.rows_read = leidas
        lote.created_count = creados
        lote.duplicated_count = duplicados
        self.lotes.agregar(lote)
        self.uow.confirmar()
        self.uow.refrescar(lote)
        return lote

    # ------------------------------------------------------------------ lotes
    def lotes_recientes(self) -> list[ImportBatch]:
        return self.lotes.recientes()

    def obtener_lote(self, lote_id: int) -> ImportBatch | None:
        return self.lotes.obtener(lote_id)

    def protegidos_del_lote(self, lote_id: int) -> int:
        """Cuantas filas de ese lote registraste o corregiste tu."""
        return self.movimientos.protegidos_del_lote(lote_id)

    def deshacer(self, lote_id: int, incluir_protegidos: bool = False) -> int:
        """Borra todo lo que entro en ese lote. Devuelve cuantos movimientos elimino.

        Si corregiste alguna fila del lote no borra nada, salvo que lo pidas con
        `incluir_protegidos` (CLAUDE.md, regla 1: tus decisiones no se borran a
        ciegas). Lo que se borre queda en la papelera, que la escribe el trigger.
        """
        lote = self.lotes.obtener(lote_id)
        if not lote:
            return 0
        if not incluir_protegidos and self.protegidos_del_lote(lote_id):
            raise Conflicto("El lote tiene movimientos protegidos: hace falta incluir_protegidos.")
        borrados = self.movimientos.deshacer_lote(lote_id)
        self.lotes.borrar(lote)      # imprescindible despues: el lote no se puede borrar
        self.uow.confirmar()         # mientras alguien lo referencie
        return borrados
