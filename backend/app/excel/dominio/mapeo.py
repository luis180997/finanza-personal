"""Importador del Excel historico.

CONTEXTO DEL ARCHIVO REAL (analizado el 5 set 2026, 1353 filas, dic 2022 -> ago 2026):

    Fecha | Ingresos | Alimentos | Transporte | Taxi | Deliverry | Otros gastos |
    Gastos totales | Observaciones | Beneficios

Tres hechos que determinan como se importa:

1. **"Otros gastos" se lleva el 75% de todo**. Como
   categoria no informa de nada. Pero el 28% de las filas trae una Observacion
   que SI dice que fue: "cafe", "subway", "cine", "claro"...
   Por eso el importador mina ese texto y reparte lo que puede. Es la diferencia
   entre importar cuatro anios de "otros" y importar cuatro anios utiles.

2. **Las columnas derivadas cuadran al centimo.** Se comprobo: 0 filas donde
   "Gastos totales" != suma de componentes, y 0 donde "Beneficios" != Ingresos -
   Gastos totales. Por eso NO se importan: el backend las recalcula y volver a
   meterlas duplicaria los importes.

3. **Cada fila es un DIA, no un movimiento.** Un "Otros gastos: 192" pueden ser
   tres compras. Lo importado es un agregado diario y se marca como tal
   (source=excel); no se puede fingir un detalle que el Excel nunca tuvo.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any

from app.compartido.corte import ANIO_MAX, ANIO_MIN, ULTIMO_DIA_EXCEL
from app.compartido.dinero import parse_money, to_cents
from app.compartido.tipos import Direction, Necessity, Source, TxStatus
from app.movimientos.dominio.entidades import Transaction
from app.movimientos.dominio.huella import build_hash

ESE, DIS, EVI = Necessity.esencial, Necessity.discrecional, Necessity.evitable

# Cabecera normalizada -> (direccion, categoria destino, necesidad)
COLUMNAS = {
    "ingresos": (Direction.ingreso, "Otros ingresos", None),
    "alimentos": (Direction.gasto, "Alimentacion", ESE),
    "alimentacion": (Direction.gasto, "Alimentacion", ESE),
    "transporte": (Direction.gasto, "Transporte", ESE),
    "taxi": (Direction.gasto, "Taxi", DIS),
    "deliverry": (Direction.gasto, "Delivery", EVI),
    "delivery": (Direction.gasto, "Delivery", EVI),
    "otros gastos": (Direction.gasto, "Sin clasificar", None),
    "otros": (Direction.gasto, "Sin clasificar", None),
}

# Columnas derivadas: se ignoran a proposito (ver nota 2 de la cabecera).
DERIVADAS = {"gastos totales", "beneficios", "total", "saldo", "neto"}

# --------------------------------------------------------------------------------
# Mineria de la columna Observaciones.
#
# El vocabulario sale del archivo real: 102 terminos distintos en 381 filas. El
# orden importa, gana la primera coincidencia, asi que lo especifico va antes que
# lo generico ("compras plaza vea" antes que "compras").
# --------------------------------------------------------------------------------
PISTAS: list[tuple[str, str, Necessity | None]] = [
    # --- comida
    (r"\bcaf[eé]\b", "Cafe", DIS),
    (r"\bsub\s?a?way\b", "Restaurante", DIS),
    (r"\btorta\b|\byogurt\b|\bempanada\b|\bhelado\b|\bsnacks?\b", "Snacks", DIS),
    (r"\bmakis?\b|\bchifa\b|\bpollo\b|\bcevich", "Restaurante", DIS),
    (r"\balmuerzo\b|\bmenu\b", "Almuerzo", ESE),
    (r"\bcena\b|\bdesayuno\b", "Restaurante", DIS),
    (r"plaza\s*vea|\btottus\b|\bmetro\b|\bwong\b|\bvivanda\b|\bmakro\b|supermercado",
     "Mercado y supermercado", ESE),
    # --- salud
    (r"\bdentista\b|\bortodon", "Dentista", ESE),
    (r"medicament|\bfarmacia\b|\bpastilla|minoxidil|\bvitamina", "Farmacia", ESE),
    (r"consulta\s*m[eé]dica|examen(es)?\s*m[eé]dico|\bbiopsia\b|\bcita\b|tratamiento|\bcl[ií]nica\b",
     "Consultas", ESE),
    (r"\bgimnasio\b|smart\s*fit|\bgym\b", "Gimnasio", DIS),
    # --- cuidado personal
    (r"\bcrema|\bperfume\b|dermaroller|\bshampoo\b|\bjab[oó]n\b",
     "Cosmetica e higiene", ESE),
    (r"\blentes?\b|\bmontura\b|[oó]ptica", "Optica", ESE),
    (r"\bcorte de pelo\b|barber|peluquer", "Peluqueria y barberia", ESE),
    # --- servicios y suscripciones
    (r"\bclaro\b|\bmovistar\b|\bentel\b|\bbitel\b|servicio del celular|linea de celular",
     "Plan movil", ESE),
    (r"\bwin\b|\binternet\b|\bhikari\b|\bcable\b", "Internet y cable", ESE),
    (r"\bnetflix\b|\bspotify\b|\bdisney\b|\bhbo\b|\bmax\b|crunchyroll", "Streaming", DIS),
    (r"azure|\baws\b|coursera|\bgithub\b|openai|\bnube\b|office\s*365", "Software y nube", DIS),
    (r"\bluz\b|\bagua\b|sedapal|luz del sur|\benel\b|calidda", "Luz", ESE),
    (r"\balquiler\b|\barriendo\b", "Alquiler", ESE),
    # --- educacion
    # "mestria" es como aparece escrito en el archivo real
    (r"\bicpna\b|\bcurso\b|\bcertificaci|\bdiplomad|big data|\bingl[eé]s\b|"
     r"\bma?e?stria\b|\bmaestria\b|\bposgrado\b|\bmatricula\b|\bpension\b",
     "Cursos", ESE),
    (r"\blibro\b|\blibros\b", "Libros", ESE),
    # --- ocio y compras
    (r"\bcine\b|cineplanet|cinemark|\bteatro\b|\bconcierto\b|happy\s*land|wargaming",
     "Cine y eventos", DIS),
    (r"\bropa\b|\bcamisa\b|\bzapatilla|\bpantal[oó]n\b|\bcorrea\b|\bpolo\b|\bcalzado\b",
     "Ropa y calzado", DIS),
    (r"\bcelular\b|aud[ií]fonos|\bhdmi\b|\bcable hdmi\b|\blaptop\b|\bmouse\b|\btecl",
     "Tecnologia", DIS),
    (r"\bv[aá]lvula\b|\bferreter|sodimac|promart|\bhogar\b", "Hogar", DIS),
    (r"\bregalo\b|\bcumplea", "Regalos", DIS),
    # --- transporte
    (r"\btaxi\b|\buber\b|\bcabify\b|indriver|\bdidi\b", "Taxi", DIS),
    (r"\bpasaje\b|metropolitano|\bcombi\b|\bl[ií]nea 1\b", "Transporte publico", ESE),
    (r"\bgrifo\b|\bprimax\b|\brepsol\b|combustible|\bgasolina\b", "Combustible", ESE),
    # --- ingresos (solo aplican a la columna Ingresos)
    (r"\bsueldo\b|pago del mes|\bcts\b|\bplanilla\b", "Sueldo", None),
    (r"\bsorteo\b|\bpremio\b", "Otros ingresos", None),
]

# Marcas de gasto evitable. Con sus erratas: en el archivo aparecen
# "Gastos inncesarios", "Gasto Innecesario", "gastos innecesarios"...
EVITABLE = re.compile(r"gastos?\s*inn?[ce]?[ce]?sari|innecesari|inncesari", re.IGNORECASE)

# Categorias de ingreso: hacen falta para no cruzar los cables, por ejemplo
# mandar un gasto a "Sueldo" porque la nota decia "pago del mes".
CATEGORIAS_INGRESO = {
    "Sueldo", "Freelance", "Reembolso", "Venta", "Intereses ganados", "Otros ingresos",
}

# Los dos cajones de sastre que una observacion puede afinar. En "Alimentos" ya
# sabemos que fue comida; en estos dos no sabemos nada.
CAJONES = {"Sin clasificar", "Otros ingresos"}


def norm(texto: Any) -> str:
    t = "".join(
        c for c in unicodedata.normalize("NFD", str(texto or "").lower())
        if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"\s+", " ", t).strip()


def clasificar_observacion(observacion: str | None) -> tuple[str | None, Necessity | None]:
    """Devuelve (categoria sugerida, necesidad) a partir del texto libre.

    REGLA CLAVE: si la nota menciona VARIAS categorias distintas, no se elige
    ninguna. La nota describe el dia entero pero el importe es uno solo, asi que
    repartirlo es imposible y quedarse con la primera pista es peligroso.

    El caso que lo demostro: una fila de varios miles de soles con la nota "Claro,
    Mestria". Ese dia se pago el recibo de Claro (unas decenas de soles) y una
    maestria (miles). Quedarse con la primera pista mandaba todo el importe a
    "Plan movil" e inflaba esa categoria al 32% del anio.

    Cuando hay ambiguedad, el movimiento se queda sin clasificar y la bandeja de
    revision se encarga. Es preferible no saber a saber mal.
    """
    if not observacion:
        return None, None
    texto = norm(observacion)
    evitable = EVI if EVITABLE.search(texto) else None

    encontradas: list[tuple[str, Necessity | None]] = []
    for patron, categoria, necesidad in PISTAS:
        if re.search(patron, texto, re.IGNORECASE):
            if categoria not in [c for c, _ in encontradas]:
                encontradas.append((categoria, necesidad))

    if len(encontradas) == 1:
        categoria, necesidad = encontradas[0]
        # Si la nota trae la marca explicita de gasto innecesario (fuga / gasto compuesto),
        # no forzamos una subcategoria puntual (Caso B: "gasto innecesario y cafe").
        # En ese caso, la necesidad es evitable, pero la categoria se mantiene sin clasificar.
        if evitable == EVI:
            return None, EVI
        return categoria, necesidad
    return None, evitable



# --------------------------------------------------------------------------------
def aplica_observacion(cat_columna: str, cat_observacion: str | None, direccion: Direction) -> bool:
    """La observacion solo pisa a la columna cuando la columna es un cajon de
    sastre Y la categoria sugerida es del mismo signo. Sin esa segunda condicion,
    una nota como "pago del mes" mandaria un gasto a la categoria "Sueldo"."""
    if not cat_observacion or cat_columna not in CAJONES:
        return False
    es_ingreso = cat_observacion in CATEGORIAS_INGRESO
    return es_ingreso == (direccion == Direction.ingreso)


@dataclass
class FilaPrevista:
    fecha: date
    columna: str
    monto: float
    direccion: str
    categoria: str | None
    necesidad: str | None
    observacion: str | None
    origen_categoria: str        # columna | observacion


@dataclass
class Analisis:
    hoja: str
    hojas_disponibles: list[str] = field(default_factory=list)
    columnas_detectadas: list[str] = field(default_factory=list)
    columnas_importadas: list[str] = field(default_factory=list)
    columnas_derivadas: list[str] = field(default_factory=list)
    columnas_sin_mapeo: list[str] = field(default_factory=list)
    filas_leidas: int = 0
    filas_con_fecha: int = 0
    movimientos: int = 0
    rescatados_por_observacion: int = 0
    sin_clasificar: int = 0
    desde: date | None = None
    hasta: date | None = None
    total_ingresos: float = 0.0
    total_gastos: float = 0.0
    muestra: list[FilaPrevista] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)


def numero(valor: Any) -> float:
    if valor is None or valor == "":
        return 0.0
    if isinstance(valor, (int, float)):
        return float(valor)
    # Texto: "1,234.56", "1.234,56" o "S/ 39.63". Quitar todas las comas, como se
    # hacia antes, convertia "1.234,56" en 1.23456.
    importe = parse_money(str(valor))
    return float(importe) if importe is not None else 0.0


def fecha_de(valor: Any) -> date | None:
    """La fecha de la fila, o None si no la tiene o es imposible: una celda con un
    numero mal formateado da fechas de 1900 que estiraban el historial."""
    f = leer_fecha(valor)
    return f if f is not None and ANIO_MIN <= f.year <= ANIO_MAX else None


def leer_fecha(valor: Any) -> date | None:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = str(valor or "").strip()
    for formato in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    return None


def limite_de_importacion(fecha_hasta: date | None) -> date:
    """Hasta que fecha se importa: la que pidas, pero nunca despues de la frontera
    (compartido/corte.py).

    Despues de ella la fuente de verdad son los correos y los registros manuales
    (CLAUDE.md, regla 3): una fila posterior duplicaria un gasto que ya llego por
    correo. Antes el corte dependia de que quien llamara mandara
    `fecha_hasta`, y la interfaz no lo mandaba nunca.
    """
    return min(fecha_hasta, ULTIMO_DIA_EXCEL) if fecha_hasta else ULTIMO_DIA_EXCEL


def elegir_hoja(nombres: list[str], hoja: str | None) -> str:
    """La que pidas; si no, la que se llame "ingresos y gastos"; si no, la primera."""
    if hoja and hoja in nombres:
        return hoja
    return next((n for n in nombres if "ingreso" in norm(n) and "gasto" in norm(n)), nombres[0])


def indice_fecha(cabecera: list[str]) -> int | None:
    return next((i for i, c in enumerate(cabecera) if c.startswith("fecha")), None)


def indice_observacion(cabecera: list[str]) -> int | None:
    return next((i for i, c in enumerate(cabecera) if c.startswith("observacion")), None)


def mapeo_de(cabecera: list[str]) -> dict[int, tuple]:
    """Columna -> (direccion, categoria destino, necesidad), solo las conocidas."""
    return {i: COLUMNAS[c] for i, c in enumerate(cabecera) if c in COLUMNAS}


def observacion_de(fila: tuple, idx_obs: int | None) -> str | None:
    if idx_obs is not None and idx_obs < len(fila) and fila[idx_obs]:
        return str(fila[idx_obs]).strip()
    return None


def categoria_de_celda(
    cat_col: str,
    nec_col: Necessity | None,
    direccion: Direction,
    cat_obs: str | None,
    nec_obs: Necessity | None,
) -> tuple[str, Necessity | None, str]:
    """(categoria, necesidad, origen) de un importe: la columna, o la observacion si
    la columna es un cajon de sastre y la nota dice algo mas preciso."""
    if aplica_observacion(cat_col, cat_obs, direccion):
        return cat_obs, nec_obs or nec_col, "observacion"
    if nec_obs == EVI and cat_col in CAJONES:
        # La nota "Gastos innecesarios" es del DIA entero, no de cada
        # columna. Marcar como evitable el pasaje de S/2 de ese dia
        # inflaria el indicador de fuga. Se aplica solo al cajon de
        # sastre, que es donde cae lo que de verdad no estaba previsto.
        return cat_col, EVI, "columna"
    return cat_col, nec_col, "columna"


def movimiento_del_excel(
    *,
    fecha: date,
    monto: float,
    direccion: Direction,
    etiqueta: str,
    category_id: int | None,
    necesidad: Necessity | None,
    observacion: str | None,
    cuenta_id: int | None,
    lote_id: int,
) -> Transaction:
    """Un importe de una celda: un agregado diario, no un movimiento suelto."""
    cents = to_cents(round(monto, 2))
    momento = datetime.combine(fecha, time(12, 0))
    return Transaction(
        occurred_at=momento,
        booking_date=fecha,
        amount_cents=cents,
        currency="PEN",
        direction=direccion,
        account_id=cuenta_id,
        category_id=category_id,
        merchant=None,
        description=f"Excel · {etiqueta}",
        necessity=necesidad,
        notes=observacion,
        tags=["excel"],
        source=Source.excel,
        status=TxStatus.confirmada,
        confidence=1.0,
        # El hash incluye la columna: si un dia tuvo el mismo importe en
        # Alimentos y en Taxi, son dos movimientos distintos.
        dedupe_hash=build_hash(
            source="excel", operation_number=None, occurred_at=momento,
            amount_cents=cents, merchant=etiqueta, account_id=cuenta_id,
        ),
        import_batch_id=lote_id,
    )
