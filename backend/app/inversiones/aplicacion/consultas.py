"""Lo que muestra la pantalla de Inversiones, ya calculado.

Los importes salen en dolares (2 decimales) y las cantidades de acciones en
unidades, como el resto de la API; por dentro todo es centavos y millonesimas.

PRECIO "AHORA" de cada valor: el mas reciente de estos, por este orden de
preferencia cuando empatan:
    1. intradia (cada pocos minutos con la bolsa abierta)
    2. cierre diario
    3. cierre de mes del ultimo estado de cuenta
    4. el de la ultima compra o venta
Asi la cartera se valora aunque no haya proveedor de precios configurado.

HISTORIA DE PRECIOS (graficos y valor en el tiempo): los cierres diarios del
proveedor y, donde no los hay, el precio oficial de cierre de cada mes que trae
cada estado de cuenta. Sin proveedor, la historia queda exacta a fin de mes. Para
dibujar, esos precios de cierre de mes se ajustan por los splits del libro.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from app.compartido import reloj
from app.inversiones.aplicacion.precios import REFERENCIA
from app.inversiones.aplicacion.puertos import RepositorioInversiones
from app.inversiones.dominio import calendario, cartera as cartera_mod, metricas
from app.inversiones.dominio.cartera import MICRO, Posicion
from app.inversiones.dominio.entidades import EstadoOperacion, Operacion, TipoOperacion
from app.inversiones.dominio.metricas import SeriePrecios

_T = TipoOperacion
RANGOS = {"1M": 31, "3M": 92, "6M": 183, "1A": 366}


def _cents(cantidad_micro: int, precio_micro: int) -> int:
    """Acciones x precio (ambos en millonesimas), en centavos."""
    return round(cantidad_micro * precio_micro / MICRO / MICRO * 100)


def usd(cents: int | float | None) -> float | None:
    return None if cents is None else round(float(cents) / 100, 2)


def unidades(micro: int | None) -> float | None:
    return None if micro is None else micro / MICRO


def _iso_utc(momento: datetime | None) -> str | None:
    return None if momento is None else momento.replace(tzinfo=timezone.utc).isoformat()


def _cierre_utc(d: date) -> datetime:
    return calendario.cierre_de(d).astimezone(timezone.utc).replace(tzinfo=None)


@dataclass
class Precio:
    micro: int
    momento: datetime        # UTC sin zona
    fuente: str              # intradia | cierre | estado_cuenta | operacion


class ServicioConsultas:
    def __init__(self, repo: RepositorioInversiones, precios_configurados: bool,
                 correo_configurado: bool, ahora: Callable[[], datetime] = reloj.ahora_utc):
        self.repo = repo
        self.precios_configurados = precios_configurados
        self.correo_configurado = correo_configurado
        self.ahora = ahora
        self._libro_cargado = False
        self._precios_cargados = False
        self._carteras: dict[date, cartera_mod.Cartera] = {}
        self._diaria: list[metricas.Punto] | None = None
        self._rentables: list[metricas.DiaRentable] | None = None

    # ------------------------------------------------------------------ datos

    def _cargar_libro(self) -> None:
        """Operaciones y estados: lo que necesitan todas las consultas."""
        if self._libro_cargado:
            return
        self.ops = self.repo.operaciones()
        self.cartera = cartera_mod.calcular(self.ops)
        self.estados = self.repo.estados()
        self.hoy = self.ahora().astimezone(calendario.NUEVA_YORK).date()
        self._libro_cargado = True

    def _cargar(self) -> None:
        """Ademas, los precios. Solo lo piden las consultas que valoran."""
        self._cargar_libro()
        if self._precios_cargados:
            return
        crudo, split, total = defaultdict(list), defaultdict(list), defaultdict(list)
        for p in self.repo.precios_diarios():
            crudo[p.simbolo].append((p.fecha, p.cierre_micro))
            split[p.simbolo].append((p.fecha, p.cierre_split_micro))
            total[p.simbolo].append((p.fecha, p.cierre_total_micro))
        self.crudo = {s: SeriePrecios(v) for s, v in crudo.items()}
        self.split = {s: SeriePrecios(v) for s, v in split.items()}
        self.total = {s: SeriePrecios(v) for s, v in total.items()}
        ahora = self.ahora().astimezone(timezone.utc).replace(tzinfo=None)
        self.intradia: dict[str, list[tuple[datetime, int]]] = defaultdict(list)
        for p in self.repo.intradia(ahora - timedelta(days=8)):
            self.intradia[p.simbolo].append((p.momento, p.precio_micro))
        self.cierre_mes: dict[str, tuple[date, int]] = {}
        if self.estados:
            ultimo = self.estados[-1]
            for p in self.repo.posiciones_de(ultimo.id):
                self.cierre_mes[p.simbolo] = (ultimo.fin, p.precio_micro)
        self._historia(crudo, split)
        self._precios_cargados = True

    def _historia(self, crudo: dict[str, list], split: dict[str, list]) -> None:
        """Cierres del proveedor completados con los de fin de mes de los estados."""
        fin_de = {e.id: e.fin for e in self.estados}
        factores = self.factores = _splits(self.ops)
        historico = defaultdict(list, {k: list(v) for k, v in crudo.items()})
        ajustado = defaultdict(list, {k: list(v) for k, v in split.items()})
        con_proveedor = {s: {f for f, _ in v} for s, v in crudo.items()}
        for p in self.repo.todas_las_posiciones():
            fecha = fin_de.get(p.estado_cuenta_id)
            if fecha is None or fecha in con_proveedor.get(p.simbolo, set()):
                continue
            historico[p.simbolo].append((fecha, p.precio_micro))
            factor = _factor_despues(factores, p.simbolo, fecha)
            ajustado[p.simbolo].append((fecha, round(p.precio_micro / factor)))
        self.historico = {s: SeriePrecios(v) for s, v in historico.items()}
        self.historico_ajustado = {s: SeriePrecios(v) for s, v in ajustado.items()}

    def _precio(self, posicion: Posicion) -> Precio | None:
        s = posicion.simbolo
        candidatos: list[Precio] = []
        if s and self.intradia.get(s):
            momento, valor = self.intradia[s][-1]
            candidatos.append(Precio(valor, momento, "intradia"))
        if s and s in self.crudo and self.crudo[s]:
            serie = self.crudo[s]
            candidatos.append(Precio(serie.valores[-1], _cierre_utc(serie.fechas[-1]), "cierre"))
        if s and s in self.cierre_mes:
            fin, valor = self.cierre_mes[s]
            candidatos.append(Precio(valor, _cierre_utc(fin), "estado_cuenta"))
        if not candidatos and posicion.ultimo_precio_micro:
            ultima = max((o for o in self.ops if cartera_mod.clave_de(o) == posicion.clave
                          and o.tipo in (_T.compra, _T.venta)), key=lambda o: o.fecha, default=None)
            fecha = ultima.fecha if ultima else self.hoy
            candidatos.append(Precio(posicion.ultimo_precio_micro, _cierre_utc(fecha), "operacion"))
        return max(candidatos, key=lambda p: p.momento) if candidatos else None

    def _cartera_al(self, d: date) -> cartera_mod.Cartera:
        if d not in self._carteras:
            self._carteras[d] = cartera_mod.calcular(self.ops, hasta=d)
        return self._carteras[d]

    def _variacion_dia(self, p: Posicion, precio: Precio | None) -> tuple[int, int] | None:
        """(ganancia del dia, lo que habia en juego) en centavos.

        Ganancia = valor ahora - valor al cierre anterior - lo pagado hoy + lo
        cobrado hoy. Una accion comprada hoy solo gana desde su precio de compra, no
        desde el cierre de ayer.
        """
        if precio is None or not p.simbolo or p.simbolo not in self.crudo:
            return None
        dia = precio.momento.replace(tzinfo=timezone.utc).astimezone(calendario.NUEVA_YORK).date()
        previo = self.crudo[p.simbolo].en(dia - timedelta(days=1))
        if not previo:
            return None
        antes = self._cartera_al(dia - timedelta(days=1)).posiciones.get(p.clave)
        valor_antes = _cents(antes.cantidad_micro, previo) if antes else 0
        de_hoy = [o for o in cartera_mod.cuentan(self.ops)
                  if cartera_mod.clave_de(o) == p.clave and o.fecha == dia
                  and o.tipo in (_T.compra, _T.venta)]
        flujo = sum(o.monto_cents for o in de_hoy)
        comprado_hoy = -sum(o.monto_cents for o in de_hoy if o.tipo is _T.compra)
        return self._valor_de(p, precio) - valor_antes + flujo, valor_antes + comprado_hoy

    def _valor_de(self, p: Posicion, precio: Precio | None) -> int:
        return _cents(p.cantidad_micro, precio.micro if precio else 0)

    def _valor_total(self, abiertas: list[Posicion]) -> int:
        return sum(self._valor_de(p, self._precio(p)) for p in abiertas) + self.cartera.efectivo_cents

    def _ahora_utc(self) -> datetime:
        return self.ahora().astimezone(timezone.utc).replace(tzinfo=None)

    # ------------------------------------------------------------------ resumen

    def resumen(self) -> dict:
        self._cargar()
        c = self.cartera
        acciones = variacion = en_juego = no_realizada = 0
        con_variacion = False
        precios_al: datetime | None = None
        for p in c.abiertas():
            precio = self._precio(p)
            valor = self._valor_de(p, precio)
            acciones += valor
            no_realizada += valor - round(p.costo_cents)
            if precio:
                precios_al = max(precios_al or precio.momento, precio.momento)
                dia = self._variacion_dia(p, precio)
                if dia is not None:
                    variacion += dia[0]
                    en_juego += dia[1]
                    con_variacion = True
        valor = acciones + c.efectivo_cents
        aportes = c.aportes_cents
        flujos = metricas.flujos_de_aporte(self.ops)
        rentabilidad = metricas.xirr(metricas.flujos_del_inversor(flujos, valor, self.hoy))
        indice = self.total.get(REFERENCIA, SeriePrecios([]))
        referencia = metricas.valor_si_fuera_indice(flujos, indice, self.hoy)
        rentabilidad_referencia = metricas.xirr(
            metricas.flujos_del_inversor(flujos, referencia, self.hoy)) if referencia else None
        div = metricas.dividendos(self.ops).total
        realizada = sum(p.realizada_cents for p in c.posiciones.values())
        return {
            "configuracion": {
                "precios": self.precios_configurados, "correo": self.correo_configurado,
            },
            "valor": usd(valor), "acciones": usd(acciones), "efectivo": usd(c.efectivo_cents),
            "aportes": usd(aportes), "ganancia": usd(valor - aportes),
            "ganancia_pct": (valor - aportes) / aportes if aportes > 0 else None,
            "dia": {
                "variacion": usd(variacion) if con_variacion else None,
                "variacion_pct": variacion / en_juego if con_variacion and en_juego > 0 else None,
            },
            "rentabilidad_anual": rentabilidad,
            "aporte_mensual": usd(metricas.aporte_mensual(flujos, self.hoy)),
            "referencia": {
                "simbolo": REFERENCIA, "valor": usd(referencia),
                "rentabilidad_anual": rentabilidad_referencia,
            },
            "realizada": usd(realizada), "no_realizada": usd(no_realizada),
            "dividendos": {"bruto": usd(div.bruto_cents + div.neto_sin_detalle_cents),
                           "retencion": usd(div.retencion_cents), "neto": usd(div.neto_cents)},
            "costos": {
                "operaciones": usd(c.comisiones_operacion_cents),
                "depositos": usd(c.comisiones_deposito_cents),
                "retiros": usd(c.comisiones_retiro_cents),
                "total": usd(
                    c.comisiones_operacion_cents + c.comisiones_deposito_cents + c.comisiones_retiro_cents
                ),
            },
            "intereses": usd(c.intereses_cents),
            "ajustes": usd(c.ajustes_cents),
            "precios_al": _iso_utc(precios_al),
            "ultimo_estado": self._ultimo_estado(),
            "provisionales": sum(o.estado is EstadoOperacion.provisional for o in self.ops),
            "avisos": c.avisos,
        }

    def _ultimo_estado(self) -> dict | None:
        if not self.estados:
            return None
        ultimo = self.estados[-1]
        liquidada = cartera_mod.calcular_liquidado(self.ops, ultimo.fin)
        oficial = {p.simbolo: p.cantidad_micro for p in self.repo.posiciones_de(ultimo.id)}
        app = {p.simbolo: p.cantidad_micro for p in liquidada.abiertas() if p.simbolo}
        efectivo = liquidada.efectivo_cents - (ultimo.caja_cents + ultimo.fdic_cents)
        return {
            "periodo": f"{ultimo.fin:%Y-%m}", "fin": ultimo.fin.isoformat(),
            "cuadra": app == oficial and efectivo == 0,
            "diferencia_efectivo": usd(efectivo),
        }

    # ------------------------------------------------------------------ posiciones

    def _fila_posicion(self, p: Posicion, total_cents: int) -> dict:
        precio = self._precio(p)
        valor = self._valor_de(p, precio)
        costo = round(p.costo_cents)
        dia = self._variacion_dia(p, precio)
        return {
            "simbolo": p.simbolo, "nombre": p.nombre, "cantidad": unidades(p.cantidad_micro),
            "precio": unidades(precio.micro) if precio else None,
            "precio_fuente": precio.fuente if precio else None,
            "precio_al": _iso_utc(precio.momento) if precio else None,
            "valor": usd(valor), "costo": usd(costo),
            "costo_promedio": unidades(p.costo_promedio_micro),
            "ganancia": usd(valor - costo),
            "ganancia_pct": (valor - costo) / costo if costo > 0 else None,
            "peso": valor / total_cents if total_cents else None,
            "variacion_dia": usd(dia[0]) if dia else None,
            "variacion_dia_pct": dia[0] / dia[1] if dia and dia[1] > 0 else None,
            "dividendos_netos": usd(p.dividendos_cents - p.retenciones_cents),
            "realizada": usd(p.realizada_cents),
        }

    def posiciones(self) -> list[dict]:
        self._cargar()
        abiertas = self.cartera.abiertas()
        total = self._valor_total(abiertas)
        filas = [self._fila_posicion(p, total) for p in abiertas]
        return sorted(filas, key=lambda f: -(f["valor"] or 0))

    # ------------------------------------------------------------------ series

    def _serie_diaria(self) -> list[metricas.Punto]:
        if self._diaria is None:
            self._diaria = metricas.serie_diaria(self.ops, self.historico, self.hoy)
        return self._diaria

    def _dias_rentables(self) -> list[metricas.DiaRentable]:
        if self._rentables is None:
            self._rentables = metricas.rentabilidad_diaria(
                self._serie_diaria(), self.total.get(REFERENCIA))
        return self._rentables

    def serie(self, rango: str) -> dict:
        self._cargar()
        diaria = self._serie_diaria()
        recorte = _recortar(diaria, rango, self.hoy, lambda p: p.fecha)
        periodo = self._periodo(diaria, recorte)
        if rango in ("1D", "1S"):
            puntos = self._serie_intradia(1 if rango == "1D" else 7)
            if puntos:
                return {"detalle": "intradia", "puntos": puntos, "periodo": periodo}
        return {"detalle": "diario", "periodo": periodo, "puntos": [
            {"t": p.fecha.isoformat(), "valor": usd(p.valor_cents), "aportes": usd(p.aportes_cents)}
            for p in recorte
        ]}

    def _periodo(self, diaria: list[metricas.Punto], recorte: list[metricas.Punto]) -> dict | None:
        """Ganancia y rentabilidad del rango, medidas desde su primer cierre. Si el
        rango llega al inicio de la cuenta, se cuenta tambien el primer dia."""
        if not recorte:
            return None
        desde = date.min if recorte[0] is diaria[0] else recorte[0].fecha
        dias = [d for d in self._dias_rentables() if d.fecha > desde]
        if not dias:
            return None
        (p,) = metricas.por_periodo(dias, lambda _: "rango")
        return {"ganancia": usd(p.ganancia_cents), "rentabilidad": p.rentabilidad,
                "referencia": p.referencia}

    def rentabilidad(self) -> dict:
        """Rentabilidad por mes, acumulada y por anio, frente al S&P 500."""
        self._cargar()
        dias = self._dias_rentables()

        def fila(p: metricas.Periodo) -> dict:
            return {"rentabilidad": p.rentabilidad, "referencia": p.referencia,
                    "ganancia": usd(p.ganancia_cents), "aportes": usd(p.aportes_cents),
                    "valor_final": usd(p.valor_final_cents)}

        total = metricas.por_periodo(dias, lambda _: "total")
        return {
            "referencia": REFERENCIA,
            "por_mes": [{"mes": p.clave, **fila(p)}
                        for p in metricas.por_periodo(dias, lambda d: f"{d:%Y-%m}")],
            "por_anio": [{"anio": int(p.clave), "en_curso": p.clave == str(self.hoy.year), **fila(p)}
                         for p in metricas.por_periodo(dias, lambda d: str(d.year))],
            "acumulada": [{"t": f.isoformat(), "tuya": tuya, "referencia": indice}
                          for f, tuya, indice in metricas.acumulada(dias)],
            "total": fila(total[0]) if total else None,
        }

    def _serie_intradia(self, dias: int) -> list[dict]:
        """Valor de lo que tienes hoy en cada muestra intradia de los ultimos dias."""
        abiertas = [p for p in self.cartera.abiertas() if p.simbolo]
        desde = self.ahora().astimezone(timezone.utc).replace(tzinfo=None) - timedelta(days=dias)
        momentos = sorted({
            m for p in abiertas for m, _ in self.intradia.get(p.simbolo, []) if m >= desde
        })
        if not momentos:
            return []
        ultimo: dict[str, int] = {}
        for p in abiertas:               # se parte del cierre anterior a la primera muestra
            dia = momentos[0].replace(tzinfo=timezone.utc).astimezone(calendario.NUEVA_YORK).date()
            serie = self.crudo.get(p.simbolo)
            previo = serie.en(dia - timedelta(days=1)) if serie else None
            ultimo[p.simbolo] = previo or p.ultimo_precio_micro or 0
        por_momento: dict[datetime, dict[str, int]] = defaultdict(dict)
        for p in abiertas:
            for m, v in self.intradia.get(p.simbolo, []):
                if m >= desde:
                    por_momento[m][p.simbolo] = v
        puntos, aportes = [], usd(self.cartera.aportes_cents)
        for m in momentos:
            ultimo.update(por_momento[m])
            acciones = sum(_cents(p.cantidad_micro, ultimo[p.simbolo]) for p in abiertas)
            puntos.append({"t": _iso_utc(m), "valor": usd(acciones + self.cartera.efectivo_cents),
                           "aportes": aportes})
        return puntos

    # ------------------------------------------------------------------ dividendos

    def dividendos(self) -> dict:
        self._cargar_libro()
        r = metricas.dividendos(self.ops)
        nombres = {p.clave: p.nombre for p in self.cartera.posiciones.values()}

        def fila(d: metricas.Dividendos) -> dict:
            return {"bruto": usd(d.bruto_cents + d.neto_sin_detalle_cents),
                    "retencion": usd(d.retencion_cents), "neto": usd(d.neto_cents)}

        return {
            "por_mes": [{"mes": mes, **fila(d)} for mes, d in sorted(r.por_mes.items())],
            "por_valor": sorted(
                ({"simbolo": clave.lstrip("?"), "nombre": nombres.get(clave), **fila(d)}
                 for clave, d in r.por_valor.items()),
                key=lambda f: -(f["neto"] or 0),
            ),
            "total": fila(r.total),
        }

    # ------------------------------------------------------------------ una accion

    def accion(self, simbolo: str) -> dict:
        self._cargar()
        p = self.cartera.posiciones.get(simbolo)
        ops = [o for o in self.ops if o.simbolo == simbolo]
        if p is None and not ops:
            return {}
        total = self._valor_total(self.cartera.abiertas())
        div = metricas.dividendos(ops)
        return {
            "simbolo": simbolo, "nombre": p.nombre if p else None,
            "posicion": self._fila_posicion(p, total) if p and p.abierta else None,
            "realizada": usd(p.realizada_cents) if p else 0.0,
            "comisiones": usd(p.comisiones_cents) if p else 0.0,
            "dividendos": {
                "bruto": usd(div.total.bruto_cents + div.total.neto_sin_detalle_cents),
                "retencion": usd(div.total.retencion_cents), "neto": usd(div.total.neto_cents),
                "por_mes": [
                    {"mes": m, "neto": usd(d.neto_cents)} for m, d in sorted(div.por_mes.items())
                ],
            },
            "operaciones": [
                operacion_a_dict(o) for o in sorted(ops, key=lambda o: o.fecha, reverse=True)
            ],
        }

    def precios_de(self, simbolo: str, rango: str) -> dict:
        """Precio de la accion (ajustado por splits) con tus compras y ventas encima."""
        self._cargar()
        ajustado = self.historico_ajustado.get(simbolo)
        puntos: list[dict] = []
        detalle = "diario"
        if rango in ("1D", "1S"):
            desde = self._ahora_utc() - timedelta(days=1 if rango == "1D" else 7)
            puntos = [{"t": _iso_utc(m), "precio": unidades(v)}
                      for m, v in self.intradia.get(simbolo, []) if m >= desde]
            detalle = "intradia"
        if not puntos and ajustado:
            dias = _recortar(list(zip(ajustado.fechas, ajustado.valores)), rango, self.hoy, lambda x: x[0])
            puntos = [{"t": f.isoformat(), "precio": unidades(v)} for f, v in dias]
            detalle = "diario"
        desde_d = date.fromisoformat(puntos[0]["t"][:10]) if puntos and rango != "TODO" else date.min

        marcas = []
        for o in self.ops:
            if o.simbolo != simbolo or o.tipo not in (_T.compra, _T.venta):
                continue
            if o.estado is EstadoOperacion.descartada:
                continue
            if o.fecha < desde_d:
                continue
            # Como el precio, ajustada por los splits posteriores a la operacion.
            f = _factor_despues(self.factores, simbolo, o.fecha)
            marcas.append({
                "t": (_iso_utc(o.ejecutada_at) if detalle == "intradia" and o.ejecutada_at
                      else o.fecha.isoformat()),
                "tipo": o.tipo.value,
                "cantidad": unidades(o.cantidad_micro) * f if o.cantidad_micro else None,
                "precio": unidades(o.precio_micro) / f if o.precio_micro else None,
                "monto": usd(o.monto_cents), "estado": o.estado.value,
            })
        return {"detalle": detalle, "puntos": puntos, "marcas": marcas}

    # ------------------------------------------------------------------ listados

    def operaciones(self, simbolo: str | None = None, estado: str | None = None) -> list[dict]:
        self._cargar_libro()
        ops = [o for o in self.ops if (simbolo is None or o.simbolo == simbolo)
               and (estado is None or o.estado.value == estado)]
        ordenadas = sorted(ops, key=lambda o: (o.fecha, o.id or 0), reverse=True)
        return [operacion_a_dict(o) for o in ordenadas]

    def estados_importados(self) -> list[dict]:
        self._cargar_libro()
        sin_cuadre = self.repo.correos_con_resultado("sin_cuadre")
        filas = []
        for e in reversed(self.estados):
            suyas = [o for o in self.ops if o.estado_cuenta_id == e.id]
            descartadas = [o for o in self.ops if o.estado is EstadoOperacion.descartada
                           and e.inicio <= o.fecha <= e.fin]
            filas.append({
                "periodo": f"{e.fin:%Y-%m}", "inicio": e.inicio.isoformat(),
                "fin": e.fin.isoformat(), "archivo": e.archivo,
                "caja": usd(e.caja_cents), "fdic": usd(e.fdic_cents), "valores": usd(e.valores_cents),
                "total": usd(e.caja_cents + e.fdic_cents + e.valores_cents),
                "operaciones": len(suyas),
                "con_correo": sum(o.correo_id is not None for o in suyas),
                "fechas_estimadas": sum(o.fecha_estimada for o in suyas),
                "correos_no_recogidos": len(descartadas) + sum(
                    e.inicio <= c.recibido_at.date() <= e.fin for c in sin_cuadre
                ),
            })
        return filas


def _desde(rango: str, hoy: date) -> date | None:
    if rango == "YTD":                                   # lo que va del anio
        return date(hoy.year, 1, 1)
    dias = 7 if rango == "1S" else RANGOS.get(rango)
    return None if dias is None else hoy - timedelta(days=dias)


def _recortar(filas: list, rango: str, hoy: date, fecha_de) -> list:
    """Las filas diarias del rango, desde el ultimo cierre anterior a el: es el punto
    de partida (lo que va del anio se mide desde el cierre del 31 de diciembre).
    Sin intradia, 1D son los dos ultimos cierres (ayer y hoy) y 1S la ultima
    semana: nunca toda la historia."""
    if rango == "1D":
        return filas[-2:]
    desde = _desde(rango, hoy)
    if desde is None:
        return filas
    primera = next((i for i, f in enumerate(filas) if fecha_de(f) >= desde), len(filas))
    recorte = filas[max(primera - 1, 0):]
    return recorte if len(recorte) >= 2 else filas[-2:]


def _splits(ops: list[Operacion]) -> dict[str, list[tuple[date, float]]]:
    """Por valor: (fecha, proporcion) de cada split, con las acciones que habia antes."""
    acciones: dict[str, int] = defaultdict(int)
    splits: dict[str, list[tuple[date, float]]] = defaultdict(list)
    for o in cartera_mod.ordenar(cartera_mod.cuentan(ops)):
        clave = cartera_mod.clave_de(o)
        q = o.cantidad_micro or 0
        if o.tipo is _T.split and acciones[clave] > 0:
            splits[clave].append((o.fecha, (acciones[clave] + q) / acciones[clave]))
        if o.tipo in (_T.compra, _T.split, _T.posicion_inicial):
            acciones[clave] += q
        elif o.tipo is _T.venta:
            acciones[clave] -= q
    return splits


def _factor_despues(splits: dict[str, list[tuple[date, float]]], simbolo: str,
                    fecha: date) -> float:
    factor = 1.0
    for dia, proporcion in splits.get(simbolo, []):
        if dia > fecha:
            factor *= proporcion
    return factor


def operacion_a_dict(o: Operacion) -> dict:
    return {
        "id": o.id, "tipo": o.tipo.value, "simbolo": o.simbolo, "nombre": o.nombre,
        "fecha": o.fecha.isoformat(), "fecha_estimada": o.fecha_estimada,
        "hora": _iso_utc(o.ejecutada_at),
        "fecha_liquidacion": o.fecha_liquidacion.isoformat() if o.fecha_liquidacion else None,
        "cantidad": unidades(o.cantidad_micro), "precio": unidades(o.precio_micro),
        "monto": usd(o.monto_cents), "retencion": usd(o.retencion_cents),
        "comision": usd(o.comision_cents),
        "estado": o.estado.value, "fuente": o.fuente.value, "nota": o.nota,
        "con_correo": o.correo_id is not None,
    }
