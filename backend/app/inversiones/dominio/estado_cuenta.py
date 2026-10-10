"""Lector del estado de cuenta mensual de Apex Clearing (el custodio de Hapi).

Recibe las paginas ya convertidas en palabras con su posicion horizontal y
devuelve lo que dice el documento. No sabe nada de PDFs: eso lo hace el
adaptador. Asi se prueba con paginas inventadas.

POR QUE ES FIABLE SIN UN LLM

El PDF lo genera una maquina con el mismo formato desde hace anios y trae
texto real, no una imagen. Y sobre todo trae sus propios totales: cada seccion
termina en "Total ...", la portada repite los saldos y las posiciones de un mes
deben salir de las del anterior mas lo que se compro y vendio. `validacion.py`
exige que todo eso cuadre al centavo; si algo no cuadra, el documento no se usa.
Este modulo solo lee; la confianza la da la validacion.

LO QUE HAY QUE SABER DEL FORMATO (comprobado contra el historial completo del
usuario, cuatro anios de estados):

1. **Las columnas se distinguen por posicion, no por orden.** En la tabla de
   movimientos un numero puede ser cantidad, precio, debito o credito, y una
   columna vacia no deja hueco en el texto. Se asigna cada numero a la cabecera
   cuyo borde derecho tiene mas cerca (los numeros van alineados a la derecha).
   Lo que queda a la izquierda de QUANTITY es descripcion: el "500" de
   "VANGUARD S&P 500 ETF" no es una cantidad.

2. **La fecha de compras y ventas es la de LIQUIDACION**, no la de la orden:
   T+2 hasta mayo de 2024 y T+1 desde entonces. La fecha de ejecucion sale del
   correo de Hapi. La excepcion son las operaciones de los ultimos dias del mes,
   que aparecen en "TRADE SETTLEMENT ACCOUNT" con su fecha de ejecucion y vuelven
   a aparecer el mes siguiente, ya liquidadas y con la otra fecha.

3. **Las posiciones son por fecha de liquidacion**: no incluyen lo pendiente.

4. **Un movimiento ocupa varias lineas.** La primera empieza con el codigo
   (BOUGHT, SOLD, DIVIDEND, JOURNAL...) y la fecha; las siguientes son detalle:
   "CASH DIV ON 2 SHS", "REC ... PAY ...", "CUSIP: ...", y "WH 0.55", la
   retencion del 30% a no residentes, que cae en la columna de debito.

5. **Los splits llegan como BOUGHT sin precio ni importe**, con el detalle
   "STK SPLIT ON <acciones previas> SHS". La cantidad es lo que se anade.

6. **El prestamo de valores** (Fully Paid Securities Lending) mueve acciones
   entre el tipo de cuenta 1 y el 7 con cuatro JOURNAL que suman cero, y el
   dividendo de una accion prestada llega como "SUB PAY" (pago sustitutivo).

7. **El efectivo sobrante se barre a un deposito asegurado (FDIC)** con su
   propia tabla de saldos. Esa tabla no siempre trae titulo; se reconoce por
   sus filas, que son las unicas que empiezan por una fecha.
"""
from __future__ import annotations

import enum
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

# ----------------------------------------------------------------------------- entrada


@dataclass(frozen=True)
class Palabra:
    texto: str
    x0: float
    x1: float


@dataclass
class Linea:
    palabras: list[Palabra]

    @property
    def texto(self) -> str:
        return " ".join(p.texto for p in self.palabras).strip()


@dataclass
class Pagina:
    numero: int
    lineas: list[Linea]


# ----------------------------------------------------------------------------- salida


class Seccion(str, enum.Enum):
    posiciones = "posiciones"
    compraventa = "compraventa"
    pendientes = "pendientes"      # ejecutadas, sin liquidar al cierre del mes
    dividendos = "dividendos"
    fondos = "fondos"              # depositos, retiros, transferencias cripto
    valores = "valores"            # entregas y recepciones de acciones
    barrido = "barrido"            # deposito asegurado FDIC
    fin = "fin"                    # avisos legales: ya no hay datos


SECCIONES_DE_ACTIVIDAD = (
    Seccion.compraventa, Seccion.pendientes, Seccion.dividendos, Seccion.fondos, Seccion.valores,
)


@dataclass
class Posicion:
    simbolo: str
    nombre: str
    tipo_cuenta: str
    cantidad: Decimal
    precio: Decimal
    valor_cents: int
    detalle: list[str] = field(default_factory=list)
    # "LAST PERIOD'S MARKET VALUE": lo que valia al empezar el mes (None si es nueva)
    valor_anterior_cents: int | None = None


@dataclass
class Movimiento:
    seccion: Seccion
    codigo: str
    fecha: date
    tipo_cuenta: str
    descripcion: str
    cantidad: Decimal | None = None
    precio: Decimal | None = None
    debito_cents: int = 0
    credito_cents: int = 0
    retencion_cents: int = 0
    detalle: list[str] = field(default_factory=list)

    @property
    def es_split(self) -> bool:
        return self.codigo == "BOUGHT" and any("STK SPLIT" in d for d in self.detalle)

    @property
    def cusip(self) -> str | None:
        for d in self.detalle:
            m = re.match(r"CUSIP: ?(\S+)", d)
            if m:
                return m.group(1)
        return None


@dataclass
class MovimientoBarrido:
    fecha: date
    actividad: str
    importe_cents: int
    saldo_cents: int
    mueve_saldo: bool  # los INTEREST solo informan; el abono llega como DIV REINV


@dataclass
class EstadoDeCuenta:
    inicio: date
    fin: date
    posiciones: list[Posicion] = field(default_factory=list)
    fdic_cents: int = 0
    movimientos: list[Movimiento] = field(default_factory=list)
    barrido: list[MovimientoBarrido] = field(default_factory=list)
    barrido_apertura_cents: int | None = None
    barrido_cierre_cents: int | None = None
    # concepto de la portada -> (apertura, cierre)
    portada: dict[str, tuple[int, int]] = field(default_factory=dict)
    # "Total ..." de la cartera -> importe; de la actividad -> (debito, credito)
    totales_cartera: dict[str, int] = field(default_factory=dict)
    totales_actividad: dict[str, tuple[int, int]] = field(default_factory=dict)
    no_reconocidas: list[str] = field(default_factory=list)

    @property
    def periodo(self) -> str:
        return f"{self.fin:%Y-%m}"


class NoEsEstadoDeCuenta(ValueError):
    """El documento no tiene ninguna pagina de estado de cuenta."""


# ----------------------------------------------------------------------------- numeros

_NUM = re.compile(r"^[<]?-?\$?-?[\d,]*\.?\d+%?$")


def es_numero(tok: str) -> bool:
    return bool(_NUM.match(tok)) and any(c.isdigit() for c in tok)


def decimal_de(tok: str) -> Decimal:
    limpio = tok.replace("$", "").replace(",", "").replace("%", "").replace("<", "")
    try:
        return Decimal(limpio)
    except InvalidOperation as exc:
        raise ValueError(f"no es un numero: {tok!r}") from exc


def cents_de(tok: str) -> int:
    return int((decimal_de(tok) * 100).quantize(Decimal(1)))


def _fecha(tok: str) -> date:
    return datetime.strptime(tok, "%m/%d/%y").date()


# ----------------------------------------------------------------------------- lector

_PERIODO = re.compile(r"([A-Z][a-z]+ \d{1,2}, \d{4}) - ([A-Z][a-z]+ \d{1,2}, \d{4})")

_TITULOS = {
    "PORTFOLIO SUMMARY": Seccion.posiciones,
    "EQUITIES / OPTIONS": Seccion.posiciones,
    "FDIC INSURED DEPOSITS": Seccion.posiciones,
    "BUY / SELL TRANSACTIONS": Seccion.compraventa,
    "TRADE SETTLEMENT ACCOUNT": Seccion.pendientes,
    "EXECUTED TRADES PENDING SETTLEMENT": Seccion.pendientes,
    "DIVIDENDS AND INTEREST": Seccion.dividendos,
    "FUNDS PAID AND RECEIVED": Seccion.fondos,
    "SECURITIES RECEIVED AND DELIVERED": Seccion.valores,
    "FDIC INSURED DEPOSITS BANK ACTIVITY": Seccion.barrido,
    "FDIC SWEEP PROGRAM": Seccion.barrido,
    "THE INSURED DEPOSIT PROGRAM": Seccion.barrido,
    "ANNOUNCEMENTS": Seccion.fin,
    "IMPORTANT INFORMATION": Seccion.fin,
}
# Algunos titulos llegan con espacios de mas ("IMPORTANT INFORMATIO N"): se
# comparan sin espacios.
_TITULOS_SIN_ESPACIOS = {k.replace(" ", ""): v for k, v in _TITULOS.items()}
# Cabeceras de tabla, numeracion y textos fijos que no aportan datos.
_RUIDO = re.compile(
    r"^(PAGE \d+ OF ?\d+|ACCOUNT NUMBER .*|ACCOUNT ACTIVITY( \(CONTINUED\))?|ACCOUNT"
    r"|TRANSACTION DATE .*|SYMBOL/ .*|DESCRIPTION CUSIP .*|DATE ACTIVITY .*|TRANSACTION CASH"
    r"|THIS PERIOD YEAR TO DATE"
    r"|DESCRIPTION LOCATION BANK BALANCE|Please contact your Registered Representative.*)$"
)
# Prosa legal: muchas palabras y ningun importe. Solo sirve para no llenar los
# avisos de texto legal; nunca descarta una linea, porque una fila de datos larga
# y sin decimales (un split, una entrega de acciones) tiene la misma forma.
_PROSA = re.compile(r"^(?!.*\d\.\d\d)(\S+\s+){7,}\S+")
_FILA_POSICION = re.compile(
    r"^(?P<nombre>.+?) (?P<simbolo>[A-Z][A-Z0-9.]{0,7}) (?P<tipo>[CMO]) (?P<cantidad>[\d,]*\.?\d+) "
    r"\$?(?P<precio>[\d,]*\.\d+) \$?(?P<valor>[\d,]+\.\d\d)(?: \$?(?P<anterior>[\d,]+\.\d\d))?(?: .*)?$"
)
_FILA_MOVIMIENTO = re.compile(
    r"^(?P<codigo>[A-Z][A-Z .]*?) (?P<fecha>\d\d/\d\d/\d\d)(?: \d\d/\d\d/\d\d)? (?P<tipo>[A-Z]) "
)
_FECHA = re.compile(r"\d\d/\d\d/\d\d")
_FILA_BARRIDO = re.compile(r"^(?P<fecha>\d\d/\d\d/\d\d) (?P<resto>.+)$")
# Lineas de detalle de la tabla del deposito asegurado.
_DETALLE_BARRIDO = {
    "FROM CASH ACCOUNT BALANCE", "FUNDS REDEEMED", "FROM PROCEEDS OF SALE", "INTEREST",
    "INTEREST REINVESTMENT",
}
# Saldos de la portada: apertura y cierre. Las etiquetas del grafico circular
# ("Cash", "Equities", "1.044%") caen a veces en la misma linea, por eso se toman
# los dos primeros importes que siguen a la etiqueta y no se ancla el final.
# La caja es NET ACCOUNT BALANCE: "Cash account" falta en muchos meses.
_IMPORTE = r"\$?(-?[\d,]*\.\d\d)"
_PORTADA = {
    "caja": re.compile(rf"NET ACCOUNT BALANCE {_IMPORTE} {_IMPORTE}"),
    "fdic": re.compile(rf"FDIC Insured Deposits {_IMPORTE} {_IMPORTE}"),
    "valores": re.compile(rf"^Securities {_IMPORTE} {_IMPORTE}"),
    "patrimonio": re.compile(rf"Total Equity Holdings {_IMPORTE} {_IMPORTE}"),
}
_COLUMNAS = ("QUANTITY", "PRICE", "DEBIT", "CREDIT")


@dataclass
class _Columnas:
    """Bordes horizontales de las cabeceras de la tabla de movimientos."""

    bordes: dict[str, tuple[float, float]] = field(default_factory=dict)

    @classmethod
    def de(cls, linea: Linea) -> _Columnas | None:
        bordes = {p.texto: (p.x0, p.x1) for p in linea.palabras if p.texto in _COLUMNAS}
        return cls(bordes) if set(bordes) == set(_COLUMNAS) else None

    def de_numero(self, p: Palabra) -> str | None:
        """Columna de un numero, o None si cae en la descripcion."""
        if p.x1 < self.bordes["QUANTITY"][0] - 15:
            return None
        return min(self.bordes, key=lambda c: abs(self.bordes[c][1] - p.x1))


def es_pagina_de_estado(pagina: Pagina) -> bool:
    textos = [l.texto for l in pagina.lineas[:8]]
    con_cuenta = any(t.startswith("ACCOUNT NUMBER") for t in textos)
    return con_cuenta and any(_PERIODO.search(t) for t in textos)


def leer(paginas: list[Pagina]) -> EstadoDeCuenta:
    """Lee un estado de cuenta. Ignora las paginas de avisos que Apex antepone."""
    paginas = [p for p in paginas if es_pagina_de_estado(p)]
    if not paginas:
        raise NoEsEstadoDeCuenta("ninguna pagina tiene numero de cuenta y periodo")
    return _Lector(paginas).leer()


class _Lector:
    def __init__(self, paginas: list[Pagina]):
        self.paginas = paginas
        self.estado: EstadoDeCuenta | None = None
        self.titular: str | None = None
        self.seccion: Seccion | None = None
        self.columnas: _Columnas | None = None
        self.movimiento: Movimiento | None = None
        self.posicion: Posicion | None = None

    def leer(self) -> EstadoDeCuenta:
        for pagina in self.paginas:
            for linea in pagina.lineas:
                self._linea(pagina, linea)
        assert self.estado is not None
        return self.estado

    def _linea(self, pagina: Pagina, linea: Linea) -> None:
        t = linea.texto
        m = _PERIODO.search(t)
        if m:
            if self.estado is None:
                inicio, fin = (datetime.strptime(g, "%B %d, %Y").date() for g in m.groups())
                self.estado = EstadoDeCuenta(inicio=inicio, fin=fin)
            return
        if self.estado is None:
            return
        if t.startswith("ACCOUNT NUMBER"):
            # El titular es la linea siguiente. No se guarda: solo se salta.
            i = pagina.lineas.index(linea)
            if self.titular is None and i + 1 < len(pagina.lineas):
                self.titular = pagina.lineas[i + 1].texto
            return
        if t == self.titular or _RUIDO.match(t):
            columnas = _Columnas.de(linea)
            if columnas:
                self.columnas = columnas
            return
        if not t:
            return

        titulo = re.sub(r" \((CONTINUED|continued)\)$", "", t)
        clave = titulo.replace(" ", "")
        if clave in _TITULOS_SIN_ESPACIOS:
            nueva = _TITULOS_SIN_ESPACIOS[clave]
            # "FDIC INSURED DEPOSITS" titula la cartera, pero tambien la tabla de saldos
            if not (titulo == "FDIC INSURED DEPOSITS" and self.seccion is Seccion.barrido):
                self.seccion = nueva
            self.movimiento = None
            self.posicion = None
            return
        if self.seccion is Seccion.fin:
            return
        if self.seccion is not Seccion.posiciones and (
            _FILA_BARRIDO.match(t) or t.startswith(("Opening Balance", "Closing Balance"))
        ):
            self.seccion = Seccion.barrido
        if self.seccion is None:
            self._portada(t)
        elif self.seccion is Seccion.posiciones:
            self._cartera(t)
        elif self.seccion is Seccion.barrido:
            self._barrido(t)
        else:
            self._actividad(linea)

    def _aviso(self, donde: str, t: str) -> None:
        if not _PROSA.match(t):
            self.estado.no_reconocidas.append(f"[{donde}] {t}")

    # --- portada ------------------------------------------------------------------

    def _portada(self, t: str) -> None:
        for concepto, regex in _PORTADA.items():
            m = regex.search(t)
            if m and concepto not in self.estado.portada:
                self.estado.portada[concepto] = (cents_de(m.group(1)), cents_de(m.group(2)))
                return

    # --- cartera ------------------------------------------------------------------

    def _cartera(self, t: str) -> None:
        if t.startswith(("Total ", "TOTAL ")):
            nombre = re.split(r" \$| \(|\s-?[\d,]*\.\d", t, maxsplit=1)[0]
            numeros = [x for x in t.split() if es_numero(x)]
            if numeros:
                self.estado.totales_cartera[nombre] = cents_de(numeros[0])
            self.posicion = None
            return
        m = _FILA_POSICION.match(t)
        if m:
            posicion = Posicion(
                simbolo=m["simbolo"], nombre=m["nombre"], tipo_cuenta=m["tipo"],
                cantidad=decimal_de(m["cantidad"]), precio=decimal_de(m["precio"]),
                valor_cents=cents_de(m["valor"]),
                valor_anterior_cents=cents_de(m["anterior"]) if m["anterior"] else None,
            )
            if posicion.simbolo == "ISPAZ":  # el deposito asegurado figura como una posicion
                self.estado.fdic_cents = posicion.valor_cents
                self.posicion = None
            else:
                self.estado.posiciones.append(posicion)
                self.posicion = posicion
        elif self.posicion is not None and not re.search(r"\d\.\d|\$", t):
            self.posicion.detalle.append(t)
        else:
            self._aviso("cartera", t)

    # --- deposito asegurado -------------------------------------------------------

    def _barrido(self, t: str) -> None:
        if t.startswith(("Opening Balance", "Closing Balance")):
            numeros = [x for x in t.split() if es_numero(x)]
            if not numeros:
                self._aviso("barrido", t)
            elif t.startswith("Opening"):
                self.estado.barrido_apertura_cents = cents_de(numeros[-1])
            else:
                self.estado.barrido_cierre_cents = cents_de(numeros[-1])
            return
        m = _FILA_BARRIDO.match(t)
        if m:
            tokens = m["resto"].split()
            numeros = [x for x in tokens if es_numero(x)]
            if len(numeros) < 2:
                self._aviso("barrido", t)
                return
            self.estado.barrido.append(MovimientoBarrido(
                fecha=_fecha(m["fecha"]), actividad=tokens[0],
                importe_cents=cents_de(numeros[0]), saldo_cents=cents_de(numeros[-1]),
                mueve_saldo=len(numeros) >= 3,
            ))
        elif t not in _DETALLE_BARRIDO and re.search(r"\d", t):
            # Sin cifras es la cola de un parrafo legal; con cifras, algo que no sabemos leer.
            self._aviso("barrido", t)

    # --- movimientos --------------------------------------------------------------

    def _actividad(self, linea: Linea) -> None:
        t = linea.texto
        if t.startswith("Total "):
            nombre = re.split(r" \$?-?[\d,]*\.\d", t, maxsplit=1)[0]
            debito = credito = 0
            for p in linea.palabras:
                if es_numero(p.texto) and self.columnas:
                    columna = self.columnas.de_numero(p)
                    if columna == "DEBIT":
                        debito = cents_de(p.texto)
                    elif columna == "CREDIT":
                        credito = cents_de(p.texto)
            self.estado.totales_actividad[nombre] = (debito, credito)
            self.movimiento = None
            return
        m = _FILA_MOVIMIENTO.match(t)
        if m:
            if self.columnas is None:
                self._aviso(self.seccion.value, f"sin cabecera de columnas: {t}")
                return
            self.movimiento = self._nuevo_movimiento(linea, m)
            self.estado.movimientos.append(self.movimiento)
        elif self.movimiento is not None:
            self._detalle(linea)
        else:
            self._aviso(self.seccion.value, t)

    def _nuevo_movimiento(self, linea: Linea, m: re.Match) -> Movimiento:
        mov = Movimiento(
            seccion=self.seccion, codigo=m["codigo"], fecha=_fecha(m["fecha"]),
            tipo_cuenta=m["tipo"], descripcion="",
        )
        # Las palabras que siguen al tipo de cuenta: descripcion y columnas numericas.
        palabras = linea.palabras
        inicio = next(
            i for i, p in enumerate(palabras)
            if i > 0 and p.texto == m["tipo"] and _FECHA.fullmatch(palabras[i - 1].texto)
        )
        descripcion = []
        for p in palabras[inicio + 1:]:
            columna = self.columnas.de_numero(p) if es_numero(p.texto) else None
            if columna == "QUANTITY":
                mov.cantidad = decimal_de(p.texto)
            elif columna == "PRICE":
                mov.precio = decimal_de(p.texto)
            elif columna == "DEBIT":
                mov.debito_cents += cents_de(p.texto)
            elif columna == "CREDIT":
                mov.credito_cents += cents_de(p.texto)
            else:
                descripcion.append(p.texto)
        mov.descripcion = " ".join(descripcion)
        # Los estados antiguos ponen las ventas en negativo; el codigo ya dice el sentido.
        # En las entregas de valores, en cambio, el signo es lo que importa.
        if mov.codigo in ("BOUGHT", "SOLD") and mov.cantidad is not None:
            mov.cantidad = abs(mov.cantidad)
        return mov

    def _detalle(self, linea: Linea) -> None:
        mov = self.movimiento
        texto = []
        palabras = linea.palabras
        for i, p in enumerate(palabras):
            if p.texto == "WH" and i + 1 < len(palabras) and es_numero(palabras[i + 1].texto):
                continue
            if i > 0 and palabras[i - 1].texto == "WH" and es_numero(p.texto):
                mov.retencion_cents += cents_de(p.texto)
                continue
            columna = self.columnas.de_numero(p) if es_numero(p.texto) else None
            if columna == "DEBIT":
                mov.debito_cents += cents_de(p.texto)
            elif columna == "CREDIT":
                mov.credito_cents += cents_de(p.texto)
            else:
                texto.append(p.texto)
        if texto:
            mov.detalle.append(" ".join(texto))
