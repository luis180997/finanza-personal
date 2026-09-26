"""Casos de uso del panel y de Tendencia. Una sola llamada alimenta todo el dashboard.

Trae los datos por los puertos y deja el calculo al dominio (dominio/calculos.py).
"""
from __future__ import annotations

from app.analitica.aplicacion.puertos import (
    CatalogoDeCategorias,
    CatalogoDeCuentas,
    DatosDeMovimientos,
    MetaDeAhorro,
    RepositorioTopes,
)
from app.analitica.dominio.calculos import (
    alertas,
    desde_para_ritmo,
    estado_de_topes,
    estado_meta,
    fila_mensual,
    gasto_por_categoria,
    kpis,
    meses_hacia_atras,
    por_categoria,
    por_cuenta,
    por_medio_pago,
    por_necesidad,
    por_subcategoria,
    ritmo_diario,
    ritmo_total,
    serie_diaria,
    serie_periodos,
    top_comercios,
    totales,
)
from app.analitica.dominio.periodos import (
    Rango,
    mismos_dias_del_anterior,
    rango_mes,
    rango_por_defecto,
)
from app.compartido import reloj


class ServicioAnalitica:
    def __init__(
        self,
        *,
        datos: DatosDeMovimientos,
        categorias: CatalogoDeCategorias,
        cuentas: CatalogoDeCuentas,
        topes: RepositorioTopes,
        meta: MetaDeAhorro,
    ):
        self.datos = datos
        self.categorias = categorias
        self.cuentas = cuentas
        self.topes = topes
        self.meta = meta

    def _ritmo(self, hasta, categorias: dict) -> tuple[dict[int, float], int]:
        """El ritmo historico se calcula UNA vez: consulta 90 dias y lo necesitan la
        proyeccion del panel, los presupuestos y la meta de ahorro."""
        movs = self.datos.que_cuentan(Rango(desde_para_ritmo(hasta), hasta))
        return ritmo_diario(movs, categorias, hasta)

    def resumen(self, rango: Rango) -> dict:
        movs = self.datos.que_cuentan(rango)
        gastos_cents, ingresos_cents = totales(movs)

        previos = self.datos.que_cuentan(rango.anterior())
        gastos_prev, ingresos_prev = totales(previos)

        hoy = reloj.hoy()
        # A mitad de periodo, lo que llevas contra el periodo anterior ENTERO siempre
        # sale a la baja: el 13/09/2026, trece dias de septiembre contra agosto entero
        # daban "-82 %" cuando en realidad se gastaba un 67 % mas que del 1 al 13 de
        # agosto. La variacion se mide contra los mismos dias; el total del anterior se
        # sigue enviando para la linea de referencia del grafico.
        mismos_dias = mismos_dias_del_anterior(rango, hoy)
        gastos_comparables, ingresos_comparables = (
            (gastos_prev, ingresos_prev) if mismos_dias is None
            else totales([t for t in previos if t.booking_date <= mismos_dias.hasta])
        )

        categorias = self.categorias.todas()
        cuentas = self.cuentas.todas()

        corte = min(hoy, rango.hasta)
        dias_transcurridos = max(1, (corte - rango.desde).days + 1)

        ritmo, dias_historial = self._ritmo(corte, categorias)
        total_ritmo = ritmo_total(ritmo, categorias)
        topes_activos = self.topes.activos()
        topes = (
            estado_de_topes(
                topes_activos, categorias, gasto_por_categoria(movs, categorias),
                ritmo, dias_historial, rango, hoy,
            )
            if topes_activos else []
        )

        return {
            "rango": {"desde": rango.desde.isoformat(), "hasta": rango.hasta.isoformat(), "dias": rango.dias},
            "kpis": kpis(movs, gastos_cents, ingresos_cents, gastos_prev,
                         gastos_comparables, ingresos_comparables, mismos_dias is not None,
                         rango, dias_transcurridos, total_ritmo, dias_historial, hoy),
            "serie_diaria": serie_diaria(movs, rango),
            "por_categoria": por_categoria(movs, categorias, gastos_cents),
            "por_subcategoria": por_subcategoria(movs, categorias, gastos_cents),
            "por_necesidad": por_necesidad(movs, gastos_cents),
            "por_cuenta": por_cuenta(movs, cuentas, gastos_cents),
            "por_medio_pago": por_medio_pago(movs, gastos_cents),
            "top_comercios": top_comercios(movs, categorias, gastos_cents),
            "presupuestos": topes,
            "meta_ahorro": estado_meta(self.meta.leer(), gastos_cents, ingresos_cents, rango,
                                       total_ritmo, dias_historial, hoy),
            "alertas": alertas(movs, gastos_cents, topes, self.datos.cuantos_por_revisar()),
        }

    def resumen_del_mes_actual(self) -> dict:
        hoy = reloj.hoy()
        return self.resumen(rango_mes(hoy.year, hoy.month))

    def serie_mensual(self, meses: int = 12) -> list[dict]:
        """Tendencia de los ultimos N meses, para el grafico de barras del dashboard."""
        return [
            fila_mensual(anio, mes, self.datos.que_cuentan(rango_mes(anio, mes)))
            for anio, mes in meses_hacia_atras(reloj.hoy(), meses)
        ]

    def rango_de_los_datos(self) -> Rango:
        """Del primer movimiento al ultimo. El rango por defecto cuando no se pide uno."""
        primera, ultima = self.datos.primera_y_ultima_fecha()
        return rango_por_defecto(primera, ultima, reloj.hoy())

    def existe_categoria(self, cat_id: int) -> bool:
        return self.categorias.obtener(cat_id) is not None

    def serie_periodos(self, agrupar: str, rango: Rango, categoria_id: int | None = None) -> dict:
        movs = self.datos.que_cuentan(rango)
        return serie_periodos(movs, self.categorias.todas(), agrupar, rango, categoria_id)
