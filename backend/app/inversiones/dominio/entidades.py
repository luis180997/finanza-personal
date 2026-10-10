"""Tablas de inversiones (Hapi / Apex). En dolares: no se convierten a soles.

Unidades, todas enteras para no arrastrar errores de coma flotante:

    *_cents  dinero en centavos de dolar
    *_micro  cantidades de acciones y precios en millonesimas (0.39073 acciones
             -> 390730; un precio de 344.6632 -> 344663200). Los estados de cuenta
             traen hasta 5 decimales en cantidades y 6 en precios.

Las horas se guardan en UTC sin zona; la API las devuelve con "+00:00".
"""
from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from app.compartido.entidad import enum_requerido, utcnow


class TipoOperacion(str, enum.Enum):
    compra = "compra"
    venta = "venta"
    split = "split"                       # acciones que se anaden sin pagar nada
    dividendo = "dividendo"               # bruto en monto, retencion aparte
    ajuste_impuesto = "ajuste_impuesto"   # devolucion o cargo de retencion (NRA)
    interes = "interes"                   # del deposito asegurado
    deposito = "deposito"
    retiro = "retiro"
    # Dinero que sale hacia cripto (Bakkt) o vuelve de ella. Las criptos no se
    # siguen: para las metricas es como un retiro o un deposito.
    cripto_salida = "cripto_salida"
    cripto_entrada = "cripto_entrada"
    # Diferencia entre lo que cuentan los correos anteriores al primer estado de
    # cuenta y el saldo inicial de ese estado: algo de entonces no llego por correo.
    ajuste_saldo = "ajuste_saldo"
    # Acciones con las que empieza el primer estado sin historia previa. No mueven
    # efectivo; su costo es su valor de mercado de ese dia y cuentan como aporte.
    posicion_inicial = "posicion_inicial"


class EstadoOperacion(str, enum.Enum):
    provisional = "provisional"   # del correo; espera al estado de cuenta del mes
    oficial = "oficial"           # figura en un estado de cuenta: sus importes mandan
    descartada = "descartada"     # el estado de cuenta del mes no la recoge


class FuenteOperacion(str, enum.Enum):
    correo = "correo"
    estado_cuenta = "estado_cuenta"


class EstadoCuentaImportado(SQLModel, table=True):
    """Un estado de cuenta mensual de Apex ya validado e importado."""

    __tablename__ = "inv_estado_cuenta"

    id: int | None = Field(default=None, primary_key=True)
    inicio: date
    fin: date = Field(index=True, unique=True)
    huella: str = Field(unique=True)          # sha256 del PDF
    # Un nombre neutro ("estado_2026-09.pdf"), no el del PDF: Apex mete en el nombre
    # del archivo el numero de cuenta, y aqui no hace falta para nada.
    archivo: str
    # Saldos oficiales al empezar y al cerrar el periodo.
    caja_apertura_cents: int = 0
    fdic_apertura_cents: int = 0
    caja_cents: int = 0
    fdic_cents: int = 0
    valores_cents: int = 0
    importado_at: datetime = Field(default_factory=utcnow)


def archivo_de(fin: date) -> str:
    return f"estado_{fin:%Y-%m}.pdf"


class PosicionCierre(SQLModel, table=True):
    """Lo que el estado de cuenta dice que habia al cierre del mes."""

    __tablename__ = "inv_posicion_cierre"

    id: int | None = Field(default=None, primary_key=True)
    estado_cuenta_id: int = Field(foreign_key="inv_estado_cuenta.id", index=True)
    simbolo: str
    nombre: str
    tipo_cuenta: str = "C"
    cantidad_micro: int
    precio_micro: int
    valor_cents: int
    valor_anterior_cents: int | None = None    # al empezar el mes

    __table_args__ = (
        UniqueConstraint(
            "estado_cuenta_id", "simbolo", "tipo_cuenta", name="uq_inv_posicion_cierre",
        ),
    )


class Operacion(SQLModel, table=True):
    """Todo lo que mueve acciones o dinero en la cuenta de inversion.

    `monto_cents` es el efecto en el efectivo: positivo si entra, negativo si sale.
    En un dividendo es el bruto; lo que llega de verdad es monto - retencion.
    """

    __tablename__ = "inv_operacion"

    id: int | None = Field(default=None, primary_key=True)
    tipo: TipoOperacion = Field(sa_column=enum_requerido(TipoOperacion))
    simbolo: str | None = Field(default=None, index=True)
    nombre: str | None = None
    # Dia de la orden (o del pago). Sin correo se deduce de la liquidacion: estimada.
    fecha: date = Field(index=True)
    fecha_estimada: bool = False
    ejecutada_at: datetime | None = None      # hora del correo, UTC
    fecha_liquidacion: date | None = None
    cantidad_micro: int | None = None
    precio_micro: int | None = None
    monto_cents: int = 0
    retencion_cents: int = 0
    comision_cents: int | None = None
    estado: EstadoOperacion = Field(
        default=EstadoOperacion.provisional, sa_column=enum_requerido(EstadoOperacion),
    )
    fuente: FuenteOperacion = Field(sa_column=enum_requerido(FuenteOperacion))
    nota: str | None = None
    correo_id: str | None = Field(default=None, unique=True)   # Message-ID
    estado_cuenta_id: int | None = Field(
        default=None, foreign_key="inv_estado_cuenta.id", index=True,
    )
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class CorreoHapiLeido(SQLModel, table=True):
    """Ficha de cada correo de Hapi ya procesado. No se guarda el texto.

    Sirve para no procesar dos veces el mismo correo y para quitar las ejecuciones
    repetidas: se cuentan las ordenes colocadas de cada valor.
    """

    __tablename__ = "inv_correo"

    id: int | None = Field(default=None, primary_key=True)
    message_id: str = Field(unique=True)
    recibido_at: datetime = Field(index=True)  # UTC
    tipo: str
    # operacion | repetido | sin_cuadre | informativo | ignorado | ilegible
    # | usada (una solicitud de deposito que ya dio su importe a un deposito)
    resultado: str
    detalle: str | None = None
    ticker: str | None = None
    lado: str | None = None
    cantidad_micro: int | None = None
    monto_cents: int | None = None             # solicitudes de deposito
    pagado_cents: int | None = None
    operacion_id: int | None = Field(default=None, foreign_key="inv_operacion.id")


class PrecioDiario(SQLModel, table=True):
    """Cierre diario de un valor, tres veces.

    - `cierre_micro`: el precio de ese dia tal cual. Con el se valora lo que
      tenias entonces (antes de un split tenias menos acciones a mas precio).
    - `cierre_split_micro`: ajustado por splits, para dibujar sin saltos.
    - `cierre_total_micro`: ajustado ademas por dividendos (rentabilidad total),
      para comparar con el S&P 500.
    """

    __tablename__ = "inv_precio_diario"

    id: int | None = Field(default=None, primary_key=True)
    simbolo: str = Field(index=True)
    fecha: date
    cierre_micro: int
    cierre_split_micro: int
    cierre_total_micro: int

    __table_args__ = (UniqueConstraint("simbolo", "fecha", name="uq_inv_precio_diario"),)


class PrecioIntradia(SQLModel, table=True):
    """Precio durante la sesion, cada pocos minutos. Se conservan unos dias."""

    __tablename__ = "inv_precio_intradia"

    id: int | None = Field(default=None, primary_key=True)
    simbolo: str = Field(index=True)
    momento: datetime                          # UTC, cierre de la barra
    precio_micro: int

    __table_args__ = (UniqueConstraint("simbolo", "momento", name="uq_inv_precio_intradia"),)
