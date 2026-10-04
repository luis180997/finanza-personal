"""Los calculos del panel, puros: reciben los movimientos y devuelven cifras.

Regla de negocio: las TRANSFERENCIAS nunca cuentan como gasto ni como ingreso.
Mover plata de BCP a Yape, o pagar la tarjeta, no es gastar. Ignorar esto es el
error mas comun al automatizar finanzas personales: duplica todo.

Quien trae los movimientos de la base es el caso de uso (aplicacion/resumen.py).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from app.analitica.dominio.periodos import MESES_CORTOS, Rango, etiqueta_mes, rango_mes
from app.clasificacion.dominio import arbol as arbol_de_categorias
from app.compartido.dinero import to_amount
from app.compartido.tipos import Direction, Necessity, PaymentMethod, TxStatus
from app.correo.dominio.dinero_propio import motivo_no_es_gasto
from app.movimientos.dominio.entidades import Transaction

# Lo que no cuenta en ningun total: un duplicado ya esta contado en otro sitio y lo
# ignorado lo quitaste tu.
EXCLUIDOS = (TxStatus.duplicada, TxStatus.ignorada)

CLAVE_META_AHORRO = "meta_ahorro_cents"

ETIQUETA_MEDIO = {
    PaymentMethod.efectivo: "Efectivo",
    PaymentMethod.debito: "Tarjeta de debito",
    PaymentMethod.credito: "Tarjeta de credito",
    PaymentMethod.yape: "Yape",
    PaymentMethod.plin: "Plin",
    PaymentMethod.transferencia: "Transferencia",
    PaymentMethod.otro: "Otro",
    None: "Sin especificar",
}


def totales(movs: list[Transaction]) -> tuple[int, int]:
    gastos = sum(t.amount_cents for t in movs if t.direction == Direction.gasto)
    ingresos = sum(t.amount_cents for t in movs if t.direction == Direction.ingreso)
    return gastos, ingresos


def pct(parte: int, total: int) -> float:
    return round(parte / total * 100, 1) if total else 0.0


def variacion(actual: int, previo: int) -> float | None:
    if not previo:
        return None
    return round((actual - previo) / previo * 100, 1)


def kpis(movs, gastos, ingresos, gastos_prev, gastos_comparables, ingresos_comparables,
          comparacion_parcial: bool, rango, dias_transcurridos,
          ritmo_total: float, dias_historial: int, hoy: date) -> dict:
    evitable = sum(
        t.amount_cents for t in movs
        if t.direction == Direction.gasto and t.necessity == Necessity.evitable
    )
    dias_con_gasto = len({t.booking_date for t in movs if t.direction == Direction.gasto})
    promedio_diario = gastos / dias_transcurridos if dias_transcurridos else 0

    # Mismo criterio que presupuestos y meta: ritmo historico, no extrapolar los
    # pocos dias que lleve el periodo.
    dias_restantes = max(0, (rango.hasta - min(hoy, rango.hasta)).days)
    proyeccion = (
        to_amount(int(gastos + ritmo_total * dias_restantes))
        if dias_historial >= MINIMO_HISTORIAL_DIAS
        else None
    )

    return {
        "gastos": to_amount(gastos),
        "ingresos": to_amount(ingresos),
        "neto": to_amount(ingresos - gastos),
        "tasa_ahorro": pct(ingresos - gastos, ingresos) if ingresos else 0.0,
        "gasto_evitable": to_amount(evitable),
        "pct_evitable": pct(evitable, gastos),
        "promedio_diario": to_amount(int(promedio_diario)),
        "proyeccion_periodo": proyeccion,
        "dias_con_gasto": dias_con_gasto,
        "dias_sin_gasto": max(0, dias_transcurridos - dias_con_gasto),
        "num_movimientos": len(movs),
        "ticket_promedio": to_amount(
            int(gastos / max(1, sum(1 for t in movs if t.direction == Direction.gasto)))
        ),
        "variacion_gastos": variacion(gastos, gastos_comparables),
        "variacion_ingresos": variacion(ingresos, ingresos_comparables),
        # El anterior ENTERO: la linea de referencia del grafico de ritmo.
        "gastos_periodo_anterior": to_amount(gastos_prev),
        # Lo gastado en los mismos dias del periodo anterior, contra lo que se mide la
        # variacion. Igual al anterior entero si el periodo no esta en curso.
        "gastos_anterior_comparable": to_amount(gastos_comparables),
        "comparacion_parcial": comparacion_parcial,
    }


def serie_diaria(movs, rango: Rango, hoy: date, ritmo_total: float,
                 dias_historial: int) -> list[dict]:
    """Un punto por dia del periodo.

    `acumulado` es el gasto real y se corta en `hoy`: los dias que aun no han
    llegado van en null. Antes seguia hasta fin de mes repitiendo el ultimo valor,
    y la grafica dibujaba una linea plana como si ya no se fuera a gastar nada.

    `proyeccion` sigue desde `hoy` hasta el cierre al ritmo historico (el mismo que
    la cifra "proyeccion al cierre" de kpis), y empieza en el acumulado de hoy para
    que las dos lineas se unan. Null si no hay historial suficiente para proyectar o
    si el periodo ya termino.
    """
    por_dia: dict[date, dict[str, int]] = defaultdict(lambda: {"gasto": 0, "ingreso": 0})
    for t in movs:
        if t.direction == Direction.gasto:
            por_dia[t.booking_date]["gasto"] += t.amount_cents
        elif t.direction == Direction.ingreso:
            por_dia[t.booking_date]["ingreso"] += t.amount_cents

    proyectar = dias_historial >= MINIMO_HISTORIAL_DIAS and rango.desde <= hoy < rango.hasta
    serie, acumulado, acumulado_hoy = [], 0, 0
    dia = rango.desde
    while dia <= rango.hasta:
        valores = por_dia.get(dia, {"gasto": 0, "ingreso": 0})
        acumulado += valores["gasto"]
        if dia == hoy:
            acumulado_hoy = acumulado
        futuro = dia > hoy
        serie.append({
            "fecha": dia.isoformat(),
            "gasto": None if futuro else to_amount(valores["gasto"]),
            "ingreso": None if futuro else to_amount(valores["ingreso"]),
            "acumulado": None if futuro else to_amount(acumulado),
            "proyeccion": (
                to_amount(int(acumulado_hoy + ritmo_total * (dia - hoy).days))
                if proyectar and dia >= hoy else None
            ),
        })
        dia += timedelta(days=1)
    return serie


def por_categoria(movs, categorias, total) -> list[dict]:
    """Gasto por categoria raiz. Agrupa por id, no por nombre: una categoria real
    llamada "Sin clasificar" no se funde con los gastos que no tienen categoria."""
    agg: dict[int | None, dict] = {}
    for t in movs:
        if t.direction != Direction.gasto:
            continue
        raiz = arbol_de_categorias.raiz(categorias.get(t.category_id), categorias)
        item = agg.setdefault(raiz.id if raiz else None, {
            "nombre": raiz.name if raiz else "Sin categoria",
            "color": raiz.color if raiz else "#898781",
            "icono": raiz.icon if raiz else "help-circle",
            "cents": 0, "movimientos": 0,
        })
        item["cents"] += t.amount_cents
        item["movimientos"] += 1

    salida = [
        {"id": k, "clave": str(k) if k is not None else SERIE_SIN_CATEGORIA,
         "nombre": v["nombre"], "color": v["color"], "icono": v["icono"],
         "monto": to_amount(v["cents"]), "movimientos": v["movimientos"],
         "pct": pct(v["cents"], total)}
        for k, v in agg.items()
    ]
    return sorted(salida, key=lambda x: x["monto"], reverse=True)


def por_subcategoria(movs, categorias, total, limite: int = 12) -> list[dict]:
    agg: dict[int | None, dict] = {}
    for t in movs:
        if t.direction != Direction.gasto:
            continue
        cat = categorias.get(t.category_id)
        raiz = arbol_de_categorias.raiz(cat, categorias)
        item = agg.setdefault(cat.id if cat else None, {
            "nombre": cat.name if cat else "Sin categoria",
            "padre": raiz.name if raiz else "Sin categoria",
            "color": cat.color if cat else "#898781",
            "cents": 0, "movimientos": 0,
        })
        item["cents"] += t.amount_cents
        item["movimientos"] += 1

    salida = [
        {"id": k, "clave": str(k) if k is not None else SERIE_SIN_CATEGORIA,
         "nombre": v["nombre"], "padre": v["padre"], "color": v["color"],
         "monto": to_amount(v["cents"]), "movimientos": v["movimientos"],
         "pct": pct(v["cents"], total)}
        for k, v in agg.items()
    ]
    return sorted(salida, key=lambda x: x["monto"], reverse=True)[:limite]


ETIQUETA_NECESIDAD = {
    Necessity.esencial: ("Esencial", "#0ca30c"),
    Necessity.discrecional: ("Discrecional", "#fab219"),
    Necessity.evitable: ("Evitable", "#d03b3b"),
    None: ("Sin marcar", "#898781"),
}


def por_necesidad(movs, total) -> list[dict]:
    agg: dict = defaultdict(int)
    for t in movs:
        if t.direction == Direction.gasto:
            agg[t.necessity] += t.amount_cents
    salida = []
    for clave, cents in agg.items():
        etiqueta, color = ETIQUETA_NECESIDAD.get(clave, ("Sin marcar", "#898781"))
        salida.append({
            "clave": clave.value if clave else "sin_marcar",
            "nombre": etiqueta, "color": color,
            "monto": to_amount(cents), "pct": pct(cents, total),
        })
    orden = {"esencial": 0, "discrecional": 1, "evitable": 2, "sin_marcar": 3}
    return sorted(salida, key=lambda x: orden.get(x["clave"], 9))


def por_cuenta(movs, cuentas, total) -> list[dict]:
    agg: dict = defaultdict(lambda: {"cents": 0, "movimientos": 0})
    for t in movs:
        if t.direction != Direction.gasto:
            continue
        cuenta = cuentas.get(t.account_id)
        nombre = cuenta.name if cuenta else "Sin cuenta"
        agg[nombre]["cents"] += t.amount_cents
        agg[nombre]["movimientos"] += 1
    salida = [
        {"nombre": k, "monto": to_amount(v["cents"]), "movimientos": v["movimientos"],
         "pct": pct(v["cents"], total)}
        for k, v in agg.items()
    ]
    return sorted(salida, key=lambda x: x["monto"], reverse=True)


def por_medio_pago(movs, total) -> list[dict]:
    """Con que pagaste, que no es lo mismo que de que cuenta salio: un yapeo
    sale de BCP Debito pero se paga por Yape."""
    agg: dict = defaultdict(lambda: {"cents": 0, "movimientos": 0})
    for t in movs:
        if t.direction != Direction.gasto:
            continue
        agg[t.payment_method]["cents"] += t.amount_cents
        agg[t.payment_method]["movimientos"] += 1
    salida = [
        {"nombre": ETIQUETA_MEDIO.get(k, "Otro"), "clave": k.value if k else "sin_especificar",
         "monto": to_amount(v["cents"]), "movimientos": v["movimientos"],
         "pct": pct(v["cents"], total)}
        for k, v in agg.items()
    ]
    return sorted(salida, key=lambda x: x["monto"], reverse=True)


VENTANA_RITMO_DIAS = 90

MINIMO_HISTORIAL_DIAS = 21

# Clave para el ritmo de los gastos que no tienen ninguna categoria asignada.
# Negativa a proposito: no puede chocar con el id de una categoria real.
SIN_CATEGORIA = -1


def gasto_por_categoria(movs: list[Transaction], categorias: dict) -> dict[int, int]:
    """Gasto del periodo por categoria, propagado hacia arriba: un tope en
    "Alimentacion" tiene que contar tambien lo gastado en "Delivery"."""
    acumulado: dict[int, int] = defaultdict(int)
    for t in movs:
        if t.direction != Direction.gasto or t.category_id is None:
            continue
        for cat in arbol_de_categorias.ancestros(categorias.get(t.category_id), categorias):
            acumulado[cat.id] += t.amount_cents
    return acumulado


def desde_para_ritmo(hasta: date) -> date:
    """Los 90 dias INCLUYENDO `hasta`. Restando 90 entraban 91 dias de gasto que
    despues se dividian entre 90."""
    return hasta - timedelta(days=VENTANA_RITMO_DIAS - 1)


def ritmo_diario(
    movs: list[Transaction], categorias: dict, hasta: date,
) -> tuple[dict[int, float], int]:
    """Gasto medio diario por categoria en los ultimos 90 dias, propagado a los
    padres. Devuelve tambien cuantos dias de historial hay de verdad.

    Por que historico y no "lo gastado este mes dividido entre los dias que van":
    esa extrapolacion es inservible a principios de mes. El dia 5, con el
    alquiler ya pagado, proyectaria un gasto mensual de seis veces el real y
    dispararia todas las alarmas a la vez. Un ritmo sobre 90 dias no se
    desestabiliza porque un gasto grande caiga temprano.
    """
    if not movs:
        return {}, 0

    total: dict[int, int] = defaultdict(int)
    primera = hasta

    # Los gastos sin categoria son gastos igual. Saltarselos hacia que la
    # proyeccion de cierre de mes se quedara corta justo cuando mas movimientos
    # habia pendientes de clasificar, que es cuando mas falta hace avisar.
    sin_categoria = 0
    for t in movs:
        if t.direction != Direction.gasto:
            continue
        primera = min(primera, t.booking_date)
        if t.category_id is None:
            sin_categoria += t.amount_cents
            continue
        for cat in arbol_de_categorias.ancestros(categorias.get(t.category_id), categorias):
            total[cat.id] += t.amount_cents

    dias_historial = (hasta - primera).days + 1
    divisor = max(1, min(dias_historial, VENTANA_RITMO_DIAS))
    ritmo = {k: v / divisor for k, v in total.items()}
    if sin_categoria:
        ritmo[SIN_CATEGORIA] = sin_categoria / divisor
    return ritmo, dias_historial


def ritmo_total(ritmo: dict[int, float], categorias: dict) -> float:
    """Suma del ritmo diario solo sobre categorias raiz: el ritmo ya viene
    propagado hacia arriba, sumar tambien las hijas contaria doble."""
    raices = {c.id for c in categorias.values() if c.parent_id is None}
    raices.add(SIN_CATEGORIA)
    return sum(v for k, v in ritmo.items() if k in raices)


def estado_de_topes(
    topes: list,
    categorias: dict,
    gastado: dict[int, int],
    ritmo: dict[int, float],
    dias_historial: int,
    rango: Rango,
    hoy: date,
) -> list[dict]:
    """Solo las categorias donde TU pusiste un tope. Sin topes, lista vacia y la
    interfaz invita a crear el primero: un tope inventado por el sistema
    dispararia alarmas que no significan nada."""
    corte = min(hoy, rango.hasta)
    dias_restantes = max(0, (rango.hasta - corte).days)
    # Sin historial suficiente no se proyecta: es mas honesto no decir nada que
    # inventar una cifra que el usuario tomaria por buena.
    hay_proyeccion = dias_historial >= MINIMO_HISTORIAL_DIAS

    salida = []
    for b in topes:
        cat = categorias.get(b.category_id)
        if not cat:
            continue
        usado = gastado.get(b.category_id, 0)
        proyeccion = (
            int(usado + ritmo.get(b.category_id, 0.0) * dias_restantes)
            if hay_proyeccion
            else None
        )

        if usado > b.amount_cents:
            estado = "excedido"
        elif proyeccion is not None and proyeccion > b.amount_cents:
            estado = "en_riesgo"       # todavia no te pasaste, pero vas camino
        else:
            estado = "en_curso"

        salida.append({
            "id": b.id,
            "categoria_id": b.category_id,
            "categoria": cat.name,
            "color": cat.color,
            "tope": to_amount(b.amount_cents),
            "gastado": to_amount(usado),
            "restante": to_amount(b.amount_cents - usado),
            "pct": pct(usado, b.amount_cents),
            "proyeccion": to_amount(proyeccion) if proyeccion is not None else None,
            "estado": estado,
        })
    return sorted(salida, key=lambda x: x["pct"], reverse=True)


def estado_meta(
    guardado: str | None,
    gastos_cents: int,
    ingresos_cents: int,
    rango: Rango,
    total_ritmo: float,
    dias_historial: int,
    hoy: date,
) -> dict | None:
    """Meta de ahorro mensual como monto fijo. `guardado`: el valor tal cual esta."""
    if not guardado:
        return None
    try:
        meta = int(guardado)
    except ValueError:
        return None
    if meta <= 0:
        return None

    ahorro = ingresos_cents - gastos_cents

    # Mismo criterio que en los presupuestos: ritmo historico, no extrapolacion
    # de los pocos dias que lleve el mes.
    corte = min(hoy, rango.hasta)
    dias_restantes = max(0, (rango.hasta - corte).days)

    if dias_historial >= MINIMO_HISTORIAL_DIAS:
        gasto_proyectado = int(gastos_cents + total_ritmo * dias_restantes)
        ahorro_proyectado = ingresos_cents - gasto_proyectado
    else:
        ahorro_proyectado = None

    # Cuanto puedes gastar al dia en lo que queda sin incumplir la meta
    margen = ingresos_cents - meta - gastos_cents
    disponible_diario = int(margen / dias_restantes) if dias_restantes > 0 else 0

    return {
        "meta": to_amount(meta),
        "ahorro_actual": to_amount(ahorro),
        "ahorro_proyectado": to_amount(ahorro_proyectado) if ahorro_proyectado is not None else None,
        "pct": pct(max(0, ahorro), meta),
        "cumple_proyeccion": ahorro_proyectado is None or ahorro_proyectado >= meta,
        "faltan": to_amount(max(0, meta - ahorro)),
        "dias_restantes": dias_restantes,
        "disponible_diario": to_amount(max(0, disponible_diario)),
    }


# Categorias cuyo "comercio" es en realidad una persona. Listarlas una por una
# no dice nada util: saber que le pagaste S/25 a Maiker y S/21 a Arvick no es
# una observacion sobre tus gastos, es tu agenda. Se agrupan en una sola fila.
CATEGORIAS_DE_PERSONAS = {"Pago a persona", "Prestamos a terceros", "Familia", "Donaciones"}


def top_comercios(movs, categorias, total, limite: int = 10) -> list[dict]:
    agg: dict = defaultdict(lambda: {"cents": 0, "movimientos": 0, "personas": False})
    for t in movs:
        if t.direction != Direction.gasto:
            continue
        cat = categorias.get(t.category_id)
        if cat and cat.name in CATEGORIAS_DE_PERSONAS:
            nombre, es_grupo = "Pagos a personas", True
        else:
            nombre, es_grupo = (t.merchant or t.merchant_raw or "Sin comercio").title(), False
        agg[nombre]["cents"] += t.amount_cents
        agg[nombre]["movimientos"] += 1
        agg[nombre]["personas"] = es_grupo

    salida = [
        {"nombre": k, "monto": to_amount(v["cents"]), "movimientos": v["movimientos"],
         "pct": pct(v["cents"], total), "agrupado": v["personas"]}
        for k, v in agg.items()
    ]
    return sorted(salida, key=lambda x: x["monto"], reverse=True)[:limite]


def alertas(movs, total_gastos, topes: list[dict], pendientes: int) -> list[dict]:
    """Observaciones accionables, no adornos.

    Los topes en riesgo se limitan a los dos peores: una lista de seis alertas
    no se lee, se ignora entera.
    """
    avisos: list[dict] = []

    for p in [t for t in topes if t["estado"] == "excedido"]:
        avisos.append({
            "tipo": "presupuesto",
            "texto": (
                f"Te pasaste del tope de {p['categoria']}: "
                f"S/ {p['gastado']} de S/ {p['tope']}."
            ),
        })

    en_riesgo = [t for t in topes if t["estado"] == "en_riesgo"]
    for p in sorted(en_riesgo, key=lambda t: t["proyeccion"] - t["tope"], reverse=True)[:2]:
        avisos.append({
            "tipo": "presupuesto",
            "texto": (
                f"A este ritmo, {p['categoria']} cerrara en S/ {p['proyeccion']} "
                f"y el tope es S/ {p['tope']}."
            ),
        })

    if pendientes:
        avisos.append({
            "tipo": "revision",
            "texto": f"{pendientes} movimiento(s) esperan tu revision.",
        })

    # Lo que la app dedujo por su cuenta que NO es gasto tuyo. Son ciento y pico
    # de movimientos: en la bandeja de revision solo servirian para taparla,
    # pero callarselos seria peor, porque mueven el total del periodo.
    deducidos = [t for t in movs if motivo_no_es_gasto(t.notes)]
    if deducidos:
        monto = to_amount(sum(t.amount_cents for t in deducidos))
        avisos.append({
            "tipo": "dinero_propio",
            "texto": (
                f"{len(deducidos)} movimiento(s) por S/ {monto} se dejaron fuera del "
                "gasto: van a tu propio nombre o a una casa de cambio. Si alguno era "
                "un pago de verdad, cambialo a gasto en Movimientos."
            ),
        })

    sin_cat = sum(1 for t in movs if t.category_id is None)
    if sin_cat:
        avisos.append({
            "tipo": "clasificacion",
            "texto": f"{sin_cat} movimiento(s) del periodo siguen sin categoria.",
        })

    evitable = sum(
        t.amount_cents for t in movs
        if t.direction == Direction.gasto and t.necessity == Necessity.evitable
    )
    if total_gastos and evitable / total_gastos > 0.15:
        avisos.append({
            "tipo": "fuga",
            "texto": (
                f"El gasto evitable es S/ {to_amount(evitable)} "
                f"({pct(evitable, total_gastos)}% del total del periodo)."
            ),
        })

    # dia atipico: mas de 3x el promedio
    por_dia: dict[date, int] = defaultdict(int)
    for t in movs:
        if t.direction == Direction.gasto:
            por_dia[t.booking_date] += t.amount_cents
    if por_dia:
        promedio = sum(por_dia.values()) / len(por_dia)
        pico_fecha, pico = max(por_dia.items(), key=lambda kv: kv[1])
        if promedio and pico > promedio * 3:
            avisos.append({
                "tipo": "pico",
                "texto": (
                    f"El {pico_fecha.isoformat()} gastaste S/ {to_amount(pico)}, "
                    f"{round(pico / promedio, 1)}x tu promedio diario."
                ),
            })
    return avisos


def meses_hacia_atras(hoy: date, meses: int) -> list[tuple[int, int]]:
    """(anio, mes) de los ultimos `meses` meses, del mas antiguo al actual."""
    salida = []
    for i in range(meses - 1, -1, -1):
        anio = hoy.year + (hoy.month - 1 - i) // 12
        mes = (hoy.month - 1 - i) % 12 + 1
        salida.append((anio, mes))
    return salida


def fila_mensual(anio: int, mes: int, movs: list[Transaction]) -> dict:
    gastos, ingresos = totales(movs)
    return {
        "periodo": f"{anio}-{mes:02d}",
        "etiqueta": etiqueta_mes(anio, mes),
        "gasto": to_amount(gastos),
        "ingreso": to_amount(ingresos),
        "neto": to_amount(ingresos - gastos),
    }


# Mas de 8 series en una pila no se distinguen por color: 7 categorias y "Otras".
MAX_SERIES_CATEGORIA = 8

# Claves de las series que no son una categoria; las demas son el id en texto.
SERIE_OTRAS = "otras"

SERIE_SIN_CATEGORIA = "sin"


def serie_periodos(
    movs: list[Transaction], categorias: dict, agrupar: str, rango: Rango,
    categoria_id: int | None = None,
) -> dict:
    """Gasto, ingreso y neto agrupados por mes o por anio.

    A diferencia de `serie_mensual`, que siempre mira los ultimos N meses desde
    hoy, esta respeta el rango que pidas: sirve tanto para "todo mi historial
    por anios" como para "los meses del 2026".

    Los meses sin ningun movimiento aparecen en cero en vez de desaparecer: un
    hueco en la serie se lee como "no gaste nada", y saltarselo hace que dos
    barras contiguas parezcan meses consecutivos cuando no lo son.

    Con `categoria_id` solo cuentan los gastos de esa rama, y la pila por
    categoria se desglosa un nivel por debajo de ella.
    """
    # Solo una categoria con hijas separa "lo puesto en ella" de sus subcategorias.
    tiene_hijas = categoria_id is not None and any(
        c.parent_id == categoria_id for c in categorias.values()
    )
    if categoria_id is not None:
        # Solo los gastos de esa rama. Los ingresos no tienen categoria de gasto,
        # asi que con filtro la serie es solo gasto.
        movs = [
            t for t in movs
            if t.direction == Direction.gasto
            and arbol_de_categorias.rama_bajo(categorias.get(t.category_id), categoria_id, categorias)
        ]

    def clave(d: date) -> str:
        return f"{d.year:04d}-{d.month:02d}" if agrupar == "mes" else f"{d.year:04d}"

    cubos: dict[str, dict] = {}
    # Gasto de cada serie, por periodo y en el rango entero (para el ranking).
    # Las series se identifican por el ID de la categoria, nunca por el nombre. Por
    # nombre, una categoria real llamada "Sin clasificar" se fundia con los gastos
    # que no tienen categoria, y una subcategoria llamada "Otras" pisaba el grupo
    # "Otras".
    por_serie: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    total_serie: dict[str, dict] = {}
    for t in movs:
        k = clave(t.booking_date)
        c = cubos.setdefault(k, {"gasto": 0, "ingreso": 0, "n": 0})
        if t.direction == Direction.gasto:
            c["gasto"] += t.amount_cents
            c["n"] += 1
            # Sin filtro, la pila va por categoria raiz; con filtro, un nivel
            # por debajo de la categoria elegida.
            cat = categorias.get(t.category_id)
            grupo = (
                arbol_de_categorias.raiz(cat, categorias) if categoria_id is None
                else arbol_de_categorias.rama_bajo(cat, categoria_id, categorias)
            )
            if grupo is None:
                serie = SERIE_SIN_CATEGORIA
                info = {"id": None, "nombre": "Sin categoria", "color": "#898781"}
            else:
                serie = str(grupo.id)
                nombre = grupo.name
                if grupo.id == categoria_id and tiene_hijas:
                    # Junto a sus hijas, el nombre de la propia categoria parece una
                    # subcategoria mas.
                    nombre = f"{grupo.name} (sin subcategoria)"
                info = {"id": grupo.id, "nombre": nombre, "color": grupo.color}
            total_serie.setdefault(serie, {**info, "cents": 0})["cents"] += t.amount_cents
            por_serie[k][serie] += t.amount_cents
        elif t.direction == Direction.ingreso:
            c["ingreso"] += t.amount_cents
            c["n"] += 1

    # Rellenar el calendario completo entre el primer y el ultimo periodo.
    claves: list[str] = []
    if agrupar == "mes":
        y, m = rango.desde.year, rango.desde.month
        while (y, m) <= (rango.hasta.year, rango.hasta.month):
            claves.append(f"{y:04d}-{m:02d}")
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    else:
        claves = [f"{y:04d}" for y in range(rango.desde.year, rango.hasta.year + 1)]

    # Las series salen del ranking del rango entero, no de cada periodo: con un
    # top por mes, una categoria entraria y saldria de "Otras" segun el mes y
    # la pila dejaria de ser comparable de una barra a la siguiente.
    ranking = sorted(total_serie.items(), key=lambda kv: kv[1]["cents"], reverse=True)
    visibles = dict(
        ranking[:MAX_SERIES_CATEGORIA - 1] if len(ranking) > MAX_SERIES_CATEGORIA else ranking
    )

    def _plegar(montos: dict[str, int]) -> dict[str, float]:
        salida = {s: to_amount(v) for s, v in montos.items() if s in visibles and v}
        resto = sum(v for s, v in montos.items() if s not in visibles)
        if resto:
            salida[SERIE_OTRAS] = to_amount(resto)
        return salida

    gasto_rango = sum(v["cents"] for v in total_serie.values())
    leyenda = [
        {"clave": s, "id": v["id"], "nombre": v["nombre"], "color": v["color"],
         "monto": to_amount(v["cents"]), "pct": pct(v["cents"], gasto_rango)}
        for s, v in visibles.items()
    ]
    resto_rango = gasto_rango - sum(v["cents"] for v in visibles.values())
    if resto_rango:
        leyenda.append({
            "clave": SERIE_OTRAS, "id": None, "nombre": "Otras", "color": "#898781",
            "monto": to_amount(resto_rango), "pct": pct(resto_rango, gasto_rango),
        })

    salida, previo = [], None
    for c in claves:
        datos = cubos.get(c, {"gasto": 0, "ingreso": 0, "n": 0})
        if agrupar == "mes":
            anio, mes = int(c[:4]), int(c[5:])
            etiqueta = etiqueta_mes(anio, mes)
        else:
            etiqueta = c
        salida.append({
            "periodo": c,
            "etiqueta": etiqueta,
            "gasto": to_amount(datos["gasto"]),
            "ingreso": to_amount(datos["ingreso"]),
            "neto": to_amount(datos["ingreso"] - datos["gasto"]),
            "movimientos": datos["n"],
            # Contra el periodo anterior de la misma serie: comparar agosto con
            # julio dice mucho mas que compararlo con un promedio.
            "variacion": variacion(datos["gasto"], previo) if previo is not None else None,
            "por_categoria": _plegar(por_serie.get(c, {})),
        })
        previo = datos["gasto"]

    # Opciones del filtro de la grafica: solo las categorias y subcategorias con
    # gasto en el rango. Ofrecer una sin datos lleva a una grafica vacia.
    arbol: dict[int, dict] = {}
    for t in movs:
        if t.direction != Direction.gasto:
            continue
        cat = categorias.get(t.category_id)
        raiz = arbol_de_categorias.raiz(cat, categorias)
        if not raiz:
            continue      # un gasto sin categoria no tiene id por el que filtrar
        nodo = arbol.setdefault(raiz.id, {"nombre": raiz.name, "cents": 0, "hijas": {}})
        nodo["cents"] += t.amount_cents
        hija = arbol_de_categorias.rama_bajo(cat, raiz.id, categorias)
        if hija and hija.id != raiz.id:
            nodo["hijas"].setdefault(hija.id, {"nombre": hija.name, "cents": 0})
            nodo["hijas"][hija.id]["cents"] += t.amount_cents

    def _mayor_primero(nodos: dict[int, dict]) -> list[tuple[int, dict]]:
        return sorted(nodos.items(), key=lambda kv: kv[1]["cents"], reverse=True)

    arbol_categorias = [
        {"id": rid, "nombre": n["nombre"], "monto": to_amount(n["cents"]),
         "subcategorias": [
             {"id": hid, "nombre": h["nombre"], "monto": to_amount(h["cents"])}
             for hid, h in _mayor_primero(n["hijas"])
         ]}
        for rid, n in _mayor_primero(arbol)
    ]

    con_datos = [p for p in salida if p["movimientos"]]
    gasto_total = sum(p["gasto"] for p in salida)
    return {
        "agrupar": agrupar,
        "rango": {"desde": rango.desde.isoformat(), "hasta": rango.hasta.isoformat()},
        # La interfaz titula con esto: describe lo que se ve, no lo ultimo elegido.
        "categoria_id": categoria_id,
        "periodos": salida,
        "categorias": leyenda,
        "arbol_categorias": arbol_categorias,
        "totales": {
            "gasto": gasto_total,
            "ingreso": sum(p["ingreso"] for p in salida),
            "neto": sum(p["neto"] for p in salida),
            "movimientos": sum(p["movimientos"] for p in salida),
            # El promedio se calcula solo sobre los periodos CON movimientos: si
            # tu historial empieza en agosto, dividir el anio entero entre 12
            # daria un "promedio mensual" que no has vivido.
            "periodos_con_datos": len(con_datos),
            "promedio": round(gasto_total / len(con_datos), 2) if con_datos else 0.0,
            "mayor": max(con_datos, key=lambda p: p["gasto"]) if con_datos else None,
        },
    }
