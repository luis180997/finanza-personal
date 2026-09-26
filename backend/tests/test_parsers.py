"""Pruebas de los parsers.

DATOS INVENTADOS: todos los datos personales de este archivo son ficticios a
proposito. Los cuerpos marcados [REAL] reproducen correos autenticos (setiembre
2026) **conservando la redaccion y la disposicion exactas**, que es lo que leen los
regex, pero con nombres, terminaciones de tarjeta y cuenta, celulares, numeros de
operacion, importes y lugares sustituidos por otros inventados del mismo formato.
El titular es "Carlos Alberto Quispe Mamani"; las tarjetas terminan en 1111, 2222...
Si una herramienta de revision marca algo de aqui como dato personal, es este caso.

Los marcados [DEDUCIDO] son suposiciones sin correo real que las respalde.

Cuando recibas un correo que no se parsee, PEGALO AQUI como caso nuevo antes de
tocar patterns.yaml: asi el patron queda cubierto para siempre. Pero ANTES cambia
sus datos por inventados (ver AGENTS.md, seccion "Pruebas con datos inventados").
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from app.compartido.comercio import normalize_merchant
from app.correo.dominio.correo import RawEmail
from app.correo.adaptadores.salida.patrones import parse_email


def correo(sender: str, subject: str, body: str) -> RawEmail:
    return RawEmail(
        gmail_id="t",
        sender=sender,
        subject=subject,
        body=body,
        received_at=datetime(2026, 9, 5, 12, 0),
    )


# Los correos son tablas HTML: tras aplanarlas, cada celda cae en su propia
# linea. Estos cuerpos reproducen esa disposicion.
YAPE_ENVIO = """¡Hola, Carlos Qui*!
¡Acabas de yapear exitosamente!
Monto de yapeo*
S/ 18.50
Yapero
Carlos Qui*
Tu número de celular
XXXXXXXXX999
Fecha y Hora de la operación
04 septiembre 2026 - 03:38 p. m.
Celular del Beneficiario
XXXXXXXXX111
Nombre del Beneficiario
Mario Lop*
N° de operación
10000004
*Por tu seguridad, te notificaremos por cada yapeo que realices.
"""

BCP_DEBITO = """Hola Carlos Alberto,
Realizaste un consumo de S/ 42.90 con tu Tarjeta de Débito BCP en PYU*CINEMARK PERU.
Por tu seguridad, te enviamos los datos de tu operación.
Monto
Total del consumo
S/ 42.90
Datos de la operación
Operación realizada
Consumo Tarjeta de Débito
Fecha y hora
03 de setiembre de 2026 - 11:24 AM
Número de Tarjeta de Débito
************1111
Empresa
PYU*CINEMARK PERU
Número de operación
100001
"""

BCP_CREDITO = """Hola Carlos Alberto,
Realizaste un consumo de S/ 96.50 con tu Tarjeta de Crédito BCP en PARDOS CHICKEN.
Por tu seguridad, te enviamos los datos de tu operación.
Monto
Total del consumo
S/ 96.50
Datos de la operación
Operación realizada
Consumo Tarjeta de Crédito
Fecha y hora
01 de setiembre de 2026 - 08:42 PM
Número de Tarjeta de Crédito
************2222
Empresa
PARDOS CHICKEN
Número de operación
0000100002
"""

BCP_CREDITO_FARMACIA = """Hola Carlos Alberto,
Realizaste un consumo de S/ 31.70 con tu Tarjeta de Crédito BCP en IKF SAN ISIDRO 9.
Monto
Total del consumo
S/ 31.70
Datos de la operación
Operación realizada
Consumo Tarjeta de Crédito
Fecha y hora
01 de setiembre de 2026 - 09:19 PM
Número de Tarjeta de Crédito
************2222
Empresa
IKF SAN ISIDRO 9
Número de operación
0000100003
"""

BCP_TRANSFERENCIA_PROPIA = """Hola Carlos Alberto,
Realizaste una transferencia de S/ 500.00 desde tu Clasica.
Por tu seguridad, te enviamos los datos de tu operación.
Montos
Monto transferido
S/ 500.00
Datos de la operación
Operación realizada
Transferencia entre mis cuentas
Fecha y hora
05 de Septiembre de 2026 - 01:26 PM
Desde
Clasica
**** 0101
Enviado a
Clasica
**** 0202
Canal
Banca Móvil BCP
"""


BBVA_PLIN = """Hola, CARLOS
Plineaste S/ 10.00 a Pedro J Ramos T
Detalles de tu plineo
Celular:
•8291
Destino:
Yape
ITF:
S/ 0.00
Fecha y hora:
5 de setiembre, 2026 19:39
Numero de operacion:
ABC123DEF456
"""

BBVA_RETIRO = """Hola, Carlos
Has realizado con exito la operacion:
Retiro de efectivo
Monto de retiro
S/ 370.00
Comision
S/ 0.00
ITF
S/ 0.00
Saldo disponible
S/ 250.40
"""

BCP_CREDITO_OXXO = """Hola Carlos Alberto,
Realizaste un consumo de S/ 3.10 con tu Tarjeta de Credito BCP en OXXO JOCKEY PLAZA.
Por tu seguridad, te enviamos los datos de tu operacion.
Monto
Total del consumo
S/ 3.10
Datos de la operacion
Operacion realizada
Consumo Tarjeta de Credito
Fecha y hora
05 de setiembre de 2026 - 05:26 PM
Numero de Tarjeta de Credito
************2222
Empresa
OXXO JOCKEY PLAZA
Numero de operacion
0000100008
"""

REMITENTE_BBVA = "BBVA <procesos@bbva.com.pe>"

REMITENTE_YAPE = "YAPE Notificaciones <notificaciones@yape.pe>"
REMITENTE_BCP = "BCP Notificaciones <notificaciones@notificacionesbcp.com.pe>"


# ---------------------------------------------------------------- casos reales
CASOS = [
    pytest.param(
        correo(REMITENTE_YAPE, "Por tu seguridad, te notificaremos por cada yapeo que realices", YAPE_ENVIO),
        "yape_envio", Decimal("18.50"), "gasto", "mario lop", id="yape_envio_real",
    ),
    pytest.param(
        correo(REMITENTE_BCP, "Realizaste un consumo con tu Tarjeta de Débito BCP", BCP_DEBITO),
        "bcp_consumo_debito", Decimal("42.90"), "gasto", "cinemark", id="bcp_debito_real",
    ),
    pytest.param(
        correo(REMITENTE_BCP, "Realizaste un consumo con tu Tarjeta de Crédito BCP", BCP_CREDITO),
        "bcp_consumo_credito", Decimal("96.50"), "gasto", "pardos chicken", id="bcp_credito_real",
    ),
    pytest.param(
        correo(REMITENTE_BCP, "Realizaste un consumo con tu Tarjeta de Crédito BCP", BCP_CREDITO_FARMACIA),
        "bcp_consumo_credito", Decimal("31.70"), "gasto", "inkafarma", id="bcp_credito_farmacia",
    ),
    pytest.param(
        correo(REMITENTE_BCP, "Realizaste una transferencia", BCP_TRANSFERENCIA_PROPIA),
        # Sin comercio: "Clasica" es el nombre de su propia cuenta, no una tienda.
        "bcp_transferencia_propias", Decimal("500.00"), "transferencia", None,
        id="bcp_transferencia_propia",
    ),
    pytest.param(
        correo(REMITENTE_BCP, "Realizaste un consumo con tu Tarjeta de Credito BCP",
               BCP_CREDITO_OXXO),
        "bcp_consumo_credito", Decimal("3.10"), "gasto", "oxxo", id="bcp_credito_oxxo",
    ),
    pytest.param(
        correo(REMITENTE_BBVA, "Constancia de operacion transferencia PLIN", BBVA_PLIN),
        "bbva_plin", Decimal("10.00"), "gasto", "pedro j ramos t", id="bbva_plin",
    ),
    pytest.param(
        correo(REMITENTE_BBVA, "BBVA - Constancia de Retiro en ATM", BBVA_RETIRO),
        "bbva_retiro_atm", Decimal("370.00"), "transferencia", None, id="bbva_retiro_atm",
    ),
]


@pytest.mark.parametrize("email,parser_id,monto,direccion,comercio", CASOS)
def test_correos_reales(email, parser_id, monto, direccion, comercio):
    parsed, motivo = parse_email(email)
    assert parsed is not None, f"no se parseo: {motivo}"
    assert parsed.parser == parser_id
    assert parsed.amount == monto
    assert parsed.direction == direccion
    assert normalize_merchant(parsed.merchant_raw) == comercio


# ------------------------------------------------- detalles que se rompen solos
def test_yape_lee_la_hora_de_la_tarde():
    """"03:38 p. m." son las 15:38, no las 03:38. Con puntos y espacios,
    dateutil lo leia como madrugada."""
    parsed, _ = parse_email(correo(REMITENTE_YAPE, "Yapeo", YAPE_ENVIO))
    assert parsed.occurred_at.hour == 15
    assert parsed.occurred_at.minute == 38
    assert parsed.occurred_at.date().isoformat() == "2026-09-04"


def test_fecha_sin_la_palabra_de():
    """Yape escribe "04 septiembre 2026"; el BCP "03 de setiembre de 2026"."""
    yape, _ = parse_email(correo(REMITENTE_YAPE, "Yapeo", YAPE_ENVIO))
    bcp, _ = parse_email(correo(REMITENTE_BCP, "Consumo", BCP_DEBITO))
    assert yape.occurred_at.date().isoformat() == "2026-09-04"
    assert bcp.occurred_at.date().isoformat() == "2026-09-03"


def test_debito_y_credito_van_a_cuentas_distintas():
    debito, _ = parse_email(correo(REMITENTE_BCP, "Consumo", BCP_DEBITO))
    credito, _ = parse_email(correo(REMITENTE_BCP, "Consumo", BCP_CREDITO))
    assert debito.account_hint == "BCP Debito"
    assert debito.last4 == "1111"
    assert debito.payment_method == "debito"
    assert credito.account_hint == "BCP Credito"
    assert credito.last4 == "2222"
    assert credito.payment_method == "credito"


def test_yape_se_carga_a_bcp_debito_con_medio_de_pago_yape():
    """Yape debita directo de BCP y el BCP no manda correo aparte: el gasto es
    de BCP Debito, y lo que lo distingue es el medio de pago."""
    parsed, _ = parse_email(correo(REMITENTE_YAPE, "Yapeo", YAPE_ENVIO))
    assert parsed.account_hint == "BCP Debito"
    assert parsed.payment_method == "yape"
    assert parsed.operation_number == "10000004"


def test_transferencia_entre_cuentas_propias_no_es_gasto():
    parsed, _ = parse_email(correo(REMITENTE_BCP, "Transferencia", BCP_TRANSFERENCIA_PROPIA))
    assert parsed.direction == "transferencia"
    assert parsed.amount == Decimal("500.00")
    assert parsed.last4 == "0101"          # la cuenta de origen, no la destino


def test_prefijo_de_pasarela_no_ensucia_el_comercio():
    """"PYU*CINEMARK PERU" es PayU cobrando por Cinemark. Interesa Cinemark."""
    parsed, _ = parse_email(correo(REMITENTE_BCP, "Consumo", BCP_DEBITO))
    assert parsed.merchant_raw.strip() == "PYU*CINEMARK PERU"
    assert normalize_merchant(parsed.merchant_raw) == "cinemark"


def test_remitente_falso_no_cuela():
    """Un phishing con "BCP" en el nombre visible pero otro dominio se descarta."""
    parsed, motivo = parse_email(
        correo("BCP Notificaciones <alertas@bcp-seguridad.xyz>", "Consumo", BCP_DEBITO)
    )
    assert parsed is None
    assert motivo


def test_descarta_promociones():
    parsed, motivo = parse_email(
        correo(REMITENTE_BCP, "Aprovecha 30% de descuento exclusivo",
               "Aprovecha nuestros beneficios del mes con tu tarjeta BCP.")
    )
    assert parsed is None
    assert "asunto" in (motivo or "")


def test_moneda_dolares():
    cuerpo = BCP_CREDITO.replace("S/ 96.50", "US$ 96.50")
    parsed, _ = parse_email(correo(REMITENTE_BCP, "Consumo", cuerpo))
    assert parsed.currency == "USD"


def test_monto_con_separador_de_miles():
    cuerpo = BCP_CREDITO.replace("S/ 96.50", "S/ 1,250.00")
    parsed, _ = parse_email(correo(REMITENTE_BCP, "Consumo", cuerpo))
    assert parsed.amount == Decimal("1250.00")


def test_correo_sin_montos_no_revienta():
    parsed, motivo = parse_email(correo("spam@ejemplo.com", "Hola", "Sin montos aqui"))
    assert parsed is None
    assert motivo


def test_plin_sale_de_bbva_y_no_confunde_el_itf_con_el_monto():
    """El correo trae "ITF: S/ 0.00" ademas del importe. Un patron generico se
    quedaria con el cero."""
    parsed, _ = parse_email(correo(REMITENTE_BBVA, "Constancia PLIN", BBVA_PLIN))
    assert parsed.amount == Decimal("10.00")
    assert parsed.account_hint == "BBVA Debito"
    assert parsed.payment_method == "plin"
    assert parsed.category_hint == "Pago a persona"
    assert parsed.operation_number == "ABC123DEF456"


def test_fecha_bbva_con_coma_antes_del_anio():
    """El BBVA escribe "5 de setiembre, 2026 19:39". La coma rompia el parseo y
    la fecha caia silenciosamente a la del encabezado del correo."""
    parsed, _ = parse_email(correo(REMITENTE_BBVA, "Constancia PLIN", BBVA_PLIN))
    assert parsed.occurred_at.date().isoformat() == "2026-09-05"
    assert (parsed.occurred_at.hour, parsed.occurred_at.minute) == (19, 39)


def test_retirar_del_cajero_no_es_gastar():
    """Sacar plata del ATM la mueve de la cuenta al bolsillo. El gasto ocurre
    despues, al usarla, y ese se registra a mano."""
    parsed, _ = parse_email(correo(REMITENTE_BBVA, "BBVA - Constancia de Retiro en ATM", BBVA_RETIRO))
    assert parsed.direction == "transferencia"
    assert parsed.amount == Decimal("370.00")
    assert parsed.category_hint == "Retiro de efectivo"


def test_el_retiro_no_toma_ni_la_comision_ni_el_saldo():
    """El correo trae "Comision S/ 0.00", "ITF S/ 0.00" y "Saldo disponible
    S/ 250.40". Confundir el saldo con el importe seria un error grave."""
    parsed, _ = parse_email(correo(REMITENTE_BBVA, "Retiro en ATM", BBVA_RETIRO))
    assert parsed.amount == Decimal("370.00")
    assert parsed.amount != Decimal("250.40")   # el saldo que queda
    assert parsed.amount != Decimal("0.00")     # la comision y el ITF
    # y tampoco debe inventarse un comercio a partir del saludo del correo
    assert normalize_merchant(parsed.merchant_raw) is None


def test_oxxo_se_agrupa_aunque_cambie_el_local():
    """"OXXO JOCKEY PLAZA" y "OXXO SAN BORJA" son el mismo comercio."""
    assert normalize_merchant("OXXO JOCKEY PLAZA") == "oxxo"
    assert normalize_merchant("OXXO SAN BORJA") == "oxxo"


# NOTA: aqui habia una prueba del "yapeo de servicio" construida a partir del
# proyecto legacy, no de un correo real. Se elimino a peticion del usuario: la
# calibracion del legacy resulto mala, y una prueba que pasa sobre un correo
# inventado es peor que no tenerla, porque parece verificacion y no lo es.
#
# El patron sigue en patterns.yaml marcado [SIN VERIFICAR]. Cuando llegue un
# correo real de un yapeo de servicio, pegalo aqui como caso nuevo.


# Pie de pagina REAL de los correos del BCP. Lo lleva cada notificacion.
PIE_SEGURIDAD_BCP = """
Recuerda que el BCP nunca te pedira tu clave de internet, OTP o clave token,
para resolver supuestos problemas con tus cuentas o para participar en sorteos
o promociones. Nuestros correos personalizados con boton o link, unicamente...
"""


def test_el_aviso_de_seguridad_no_descarta_el_correo():
    """Este fallo tiro a la basura 22 consumos reales del BCP.

    El pie de pagina del banco dice "...para participar en sorteos o
    promociones", y "sorteo" estaba en la lista de descarte, que miraba el
    cuerpo entero. Ahora el descarte mira SOLO el asunto: un correo promocional
    se delata ahi, mientras que el pie de uno legitimo siempre trae publicidad.
    """
    email = correo(
        REMITENTE_BCP,
        "Realizaste un consumo con tu Tarjeta de Credito BCP",
        BCP_CREDITO + PIE_SEGURIDAD_BCP,
    )
    parsed, motivo = parse_email(email)
    assert parsed is not None, f"se descarto un consumo real: {motivo}"
    assert parsed.amount == Decimal("96.50")


def test_una_promocion_de_verdad_si_se_descarta():
    """El descarte sigue funcionando para lo que se hizo: publicidad, que se
    anuncia en el asunto."""
    parsed, motivo = parse_email(
        correo(REMITENTE_BCP, "Aprovecha 30% de descuento exclusivo con tu tarjeta",
               "Realizaste un consumo de S/ 10.00 con tu Tarjeta de Credito BCP en X.")
    )
    assert parsed is None
    assert "asunto" in (motivo or "")


# ------------------------------------------------- correos reales (6 set 2026)
BBVA_TARJETA = """Estimado Cliente,
El 29/08/2022 realizo un consumo en CAJE 2698 por S/ 50.00
Se cargara en su tarjeta terminada en **5555
BBVA
000000000
"""

YAPE_PAGO_COMERCIO = """Hola CARLOS,
¡Tu pago en PEDIDOS YA fue exitoso!
Monto total
S/ 24.90
Fecha y hora:
23 agosto 2026 - 04:39 p. m.
Titular:
CARLOS ALBERTO QUISPE MAMANI
Celular:
*** *** 999
ID de operación:
1000000000005
"""

YAPE_PAGO_SERVICIO = """Hola CARLOS,
¡Tu servicio fue yapeado con éxito!
Monto total
S/ 119.90
Yapero(a):
CARLOS ALBERTO QUISPE MAMANI
Número de celular:
*** *** 999
Fecha y hora:
22 Ago. 2026 - 05:28 pm
Nº de operación Yape:
01000006
Detalle del servicio:
Empresa:
WIN Internet
Servicio:
Pago soles
Titular del servicio:
Torres Ruiz Ana
"""


def test_bbva_consumo_con_tarjeta():
    """El BBVA pone el comercio ANTES del importe, al reves que el BCP:
    "realizo un consumo en CAJE 2698 por S/ 50.00"."""
    parsed, motivo = parse_email(
        correo(REMITENTE_BBVA, "BBVA", BBVA_TARJETA)
    )
    assert parsed is not None, motivo
    assert parsed.parser == "bbva_consumo_tarjeta"
    assert parsed.amount == Decimal("50.00")
    assert parsed.direction == "gasto"
    assert parsed.last4 == "5555"            # "terminada en **5555", dos asteriscos
    assert parsed.occurred_at.date().isoformat() == "2022-08-29"


def test_yape_pagando_en_un_comercio():
    """"Titular" es el usuario, no el comercio. El comercio esta en la frase
    "Tu pago en X fue exitoso"."""
    parsed, motivo = parse_email(
        correo(REMITENTE_YAPE, "Pago exitoso", YAPE_PAGO_COMERCIO)
    )
    assert parsed is not None, motivo
    assert parsed.parser == "yape_pago_comercio"
    assert parsed.amount == Decimal("24.90")
    assert normalize_merchant(parsed.merchant_raw) == "pedidosya"
    assert parsed.operation_number == "1000000000005"    # "ID de operación"
    assert parsed.occurred_at.hour == 16                 # "04:39 p. m."


def test_yape_pagando_un_servicio():
    """El comercio bueno esta en "Empresa:", dentro de "Detalle del servicio".
    Ni "Yapero(a)" ni "Titular del servicio" lo son: son personas."""
    parsed, motivo = parse_email(
        correo(REMITENTE_YAPE, "Tu yapeo de servicio ha sido confirmado", YAPE_PAGO_SERVICIO)
    )
    assert parsed is not None, motivo
    assert parsed.parser == "yape_servicio"
    assert parsed.amount == Decimal("119.90")
    assert normalize_merchant(parsed.merchant_raw) == "win"
    # "Nº de operación Yape: 01000006" -> la palabra "Yape" no es el numero
    assert parsed.operation_number == "01000006"


def test_mes_abreviado_con_punto():
    """Yape escribe "22 Ago. 2026" en los pagos de servicio. Sin la abreviatura
    la fecha caia en silencio a la de llegada del correo."""
    parsed, _ = parse_email(
        correo(REMITENTE_YAPE, "Yapeo de servicio", YAPE_PAGO_SERVICIO)
    )
    assert parsed.occurred_at.date().isoformat() == "2026-08-22"
    assert (parsed.occurred_at.hour, parsed.occurred_at.minute) == (17, 28)


def test_los_tres_tipos_de_yape_no_se_pisan():
    """Persona, comercio y servicio son tres parsers distintos porque el
    comercio se extrae de sitios diferentes. Cada uno debe coger el suyo."""
    casos = [
        (YAPE_ENVIO, "yape_envio"),
        (YAPE_PAGO_COMERCIO, "yape_pago_comercio"),
        (YAPE_PAGO_SERVICIO, "yape_servicio"),
    ]
    for cuerpo, esperado in casos:
        parsed, motivo = parse_email(correo(REMITENTE_YAPE, "Yape", cuerpo))
        assert parsed is not None, motivo
        assert parsed.parser == esperado


BCP_CONSUMO_DOLARES = """Hola Carlos Alberto,
Realizaste un consumo de $ 7.25 con tu Tarjeta de Debito BCP en PLIN-DIEGO SALAS.
Monto
Total del consumo
$ 7.25
Datos de la operacion
Operacion realizada
Consumo Tarjeta de Debito
Fecha y hora
25 de agosto de 2026 - 06:53 PM
Empresa
PLIN-DIEGO SALAS
"""

BCP_PAGO_TARJETA = """Hola Carlos Alberto,
Realizaste un pago a tu tarjeta de S/ 615.30 desde tu Cuenta sueldo .
Montos
Monto pagado
S/ 615.30
Datos de la operacion
Operacion realizada
Pago de tarjeta propia BCP
Fecha y hora
28 de Agosto de 2026 - 07:55 AM
Pagado a
Visa Oro BCP Qore **** 2222
"""

BBVA_CAJERO = """Hola, CARLOS
OPERACION APROBADA
Por tu seguridad, te enviamos los datos de su operacion en cajero.
DETALLES DE OPERACION
Fecha y hora
05/09/2026 16:12:34
Numero de cajero
1488
Moneda
PEN
Importe
370.00
Ultimos digitos de tarjeta
*4444
"""

YAPE_RECARGA = """S/ 6
Numero recargado: 900 000 000
Yapero: Carlos Alberto Quispe Mamani
Fecha: 31 ago. 2026 - 12:06 p. m.
Operadora: Claro
Nº de operacion Yape: 00100007
AMERICA MOVIL PERU S.A.C
Recarga Efectiva : S/ 6.0
Valor Venta : S/ 5.08
Descuento : S/ 0.0
I.G.V. : S/ 0.92
"""


def test_consumo_en_dolares_con_simbolo_pelado():
    """El BCP escribe los consumos en dolares con "$" a secas, no "US$".
    Sin esto, dos consumos reales se quedaban sin importe y se perdian."""
    parsed, motivo = parse_email(
        correo(REMITENTE_BCP, "Realizaste un consumo con tu Tarjeta de Debito BCP",
               BCP_CONSUMO_DOLARES)
    )
    assert parsed is not None, motivo
    assert parsed.amount == Decimal("7.25")
    assert parsed.currency == "USD"


def test_pagar_tu_propia_tarjeta_no_es_gasto():
    """El gasto ya se conto al usar la tarjeta. Contar tambien el pago
    duplicaria el consumo entero del mes."""
    parsed, motivo = parse_email(
        correo(REMITENTE_BCP, "Constancia de Pago de Tarjeta de Credito Propia",
               BCP_PAGO_TARJETA)
    )
    assert parsed is not None, motivo
    assert parsed.parser == "bcp_pago_tarjeta_propia"
    assert parsed.direction == "transferencia"
    assert parsed.amount == Decimal("615.30")
    # Los "**** 2222" son de la tarjeta de DESTINO: usarlos sacaria el dinero
    # de la cuenta equivocada.
    assert parsed.last4 is None
    assert parsed.account_hint == "BCP Debito"


def test_operacion_en_cajero_bbva():
    """Este correo no lleva simbolo de moneda: "Importe 370.00" a secas."""
    parsed, motivo = parse_email(
        correo(REMITENTE_BBVA, "Tu operacion en nuestros cajeros automaticos ha sido aprobada",
               BBVA_CAJERO)
    )
    assert parsed is not None, motivo
    assert parsed.parser == "bbva_cajero"
    assert parsed.amount == Decimal("370.00")
    assert parsed.currency == "PEN"
    assert parsed.direction == "transferencia"
    assert parsed.last4 == "4444"            # "*4444", un solo asterisco
    assert parsed.occurred_at.date().isoformat() == "2026-09-05"


def test_recarga_de_celular_no_confunde_el_igv_con_el_importe():
    """El correo trae cuatro importes: recarga efectiva 6.00, valor venta 5.08,
    descuento 0.0 e IGV 0.92. Lo que sale de la cuenta es la recarga."""
    parsed, motivo = parse_email(
        correo(REMITENTE_YAPE, "Tu recarga en Yape ha sido confirmada", YAPE_RECARGA)
    )
    assert parsed is not None, motivo
    assert parsed.parser == "yape_recarga"
    assert parsed.amount == Decimal("6.00")
    assert parsed.amount != Decimal("5.08")   # valor venta
    assert parsed.amount != Decimal("0.92")   # IGV
    assert normalize_merchant(parsed.merchant_raw) == "claro"
    assert parsed.category_hint == "Plan movil"


def test_una_preposicion_no_es_un_comercio():
    """El pie de los correos del BCP dice "Servicio de\r\n Notificaciones BCP".
    Un patron capturaba "de\r" y quince transferencias acababan con el comercio
    "de", encabezando el ranking de gastos como si fuera una tienda real."""
    assert normalize_merchant("de") is None
    assert normalize_merchant("de\r") is None
    assert normalize_merchant("  el  ") is None
    # pero un comercio de verdad sigue pasando
    assert normalize_merchant("Cross Payments S.") == "cross payments s"


# --------------------------------------------------------------------- titular
def test_envio_a_uno_mismo_no_es_gasto():
    """Mover dinero del BCP al BBVA propio no es gastarlo.

    El correo es identico al de un pago a un tercero; lo unico que los distingue
    es que el destinatario se llama como el titular al que saluda el correo.
    Sin esto entraban doce movimientos y varios miles de soles como gasto, y el nombre del
    propio titular encabezaba el ranking de comercios.
    """
    from app.correo.dominio.dinero_propio import es_envio_a_uno_mismo, nombre_del_titular

    cuerpo = (
        "Hola Carlos Alberto, \n\n Realizaste una transferencia de S/ 400.00 desde tu "
        "Clasica.\n Enviado a \n Carlos Alberto Quispe M. \n **** 0404 \n Banco destino \n Bbva"
    )
    assert nombre_del_titular(cuerpo) == ["carlos", "alberto"]
    assert es_envio_a_uno_mismo(cuerpo, "Carlos Alberto Quispe M.")
    # El banco enmascara los nombres de personas; sigue siendo el mismo titular.
    assert es_envio_a_uno_mismo(cuerpo, "Ca*** Al*** Qu*** Er*** C.")
    # Un tercero que comparte solo el primer nombre no es el titular.
    assert not es_envio_a_uno_mismo(cuerpo, "Carlos Jorge Perez")
    assert not es_envio_a_uno_mismo(cuerpo, "Kambista S.")


def test_saludo_de_una_palabra_no_identifica_al_titular():
    """"Hola, Carlos" no distingue al titular de cualquier otro Carlos.

    Yape y BBVA saludan solo con el nombre de pila. Darlo por bueno marcaria
    como propios los envios a cualquier tocayo, que si son gasto.
    """
    from app.correo.dominio.dinero_propio import es_envio_a_uno_mismo, nombre_del_titular

    cuerpo = "Hola, Carlos\n Tu yapeo fue confirmado"
    assert nombre_del_titular(cuerpo) == []
    assert not es_envio_a_uno_mismo(cuerpo, "Carlos Ramirez Soto")


# [REAL] El BCP notifica los pagos por Plin como un consumo con tarjeta de
# debito cualquiera. Lo unico que los delata es el "PLIN-" del descriptor.
BCP_PLIN = """Hola Carlos Alberto,
Realizaste un consumo de S/ 8.50 con tu Tarjeta de Debito BCP en PLIN-JORGE DE LA TORRE.
A continuacion, te enviamos los datos de tu operacion.
Empresa
PLIN-JORGE DE LA TORRE
Tarjeta
**** 1111
Fecha y hora
27 de Agosto de 2026 - 07:15 PM
Numero de operacion
00100009
El BCP nunca te solicitara datos confidenciales por correo para resolver
supuestos problemas con tus cuentas o para participar en sorteos o promociones.
"""


def test_pago_por_plin_desde_el_bcp_es_un_pago_a_persona():
    """El BCP lo manda como "consumo con tarjeta de debito", pero salio por Plin.

    Sin este parser, ocho pagos a personas entraban como comercios distintos
    ("Plin Fulano Perez", "Plin Mengano Torres"...) y ensuciaban el
    ranking, ademas de contarse como debito cuando el medio real es Plin.
    """
    parsed, _ = parse_email(correo(REMITENTE_BCP, "Consumo", BCP_PLIN))
    assert parsed.parser == "bcp_plin_persona"
    assert parsed.payment_method == "plin"          # no "debito"
    assert parsed.category_hint == "Pago a persona"  # para que agrupe
    assert parsed.amount == Decimal("8.50")
    assert parsed.last4 == "1111"
    # El "PLIN-" no forma parte del nombre, y el apellido no se corta.
    assert normalize_merchant(parsed.merchant_raw) == "jorge de la torre"


def test_un_consumo_normal_sigue_siendo_debito():
    """El parser de Plin va antes que el de consumo: no debe robarle los suyos."""
    parsed, _ = parse_email(correo(REMITENTE_BCP, "Consumo", BCP_DEBITO))
    assert parsed.parser == "bcp_consumo_debito"
    assert parsed.payment_method == "debito"


# ------------------------------------------- formatos vistos al cargar todo 2026
# [REAL] El formato nuevo del BBVA: una tabla sin simbolo de moneda.
BBVA_CONSUMO_TABLA = """Hola, CARLOS
Has realizado el siguiente consumo:
Comercio:
Q_ UMA SOLUCIONES
Monto:
10.50
Moneda:
PEN
Fecha:
07/04/2026
Hora:
10:21:46
Este se cargara a tu tarjeta terminada en *3333
"""

# [REAL] Promocion del BBVA. NO es un movimiento, pero su letra pequeña habla de
# "un consumo de S/1,000": entraba como gasto de mil soles.
BBVA_PROMO = """¡Solo con tus Tarjetas BBVA!
Carlos Alberto,
Arcangel llega a Lima. Asegura tu entrada con 15% de descuento
en la preventa exclusiva con tu Tarjeta de Credito BBVA.
¿Ya no quieres recibir nuestras comunicaciones? Puedes desuscribirte de nuestra lista
TCEA Maxima Referencial 156,60%: calculada considerando TEA 79,99% aplicable a un
consumo de S/1,000 a 12 meses y cargos que incluye
"""

# [REAL] Pagar tu propia tarjeta no es gastar: el gasto fue el consumo que financio.
BBVA_PAGO_TARJETA = """Hola, Carlos Has realizado con exito la operacion:
Pagar tarjetas propias
Importe transferido
S/ 210.75
Comision
S/ 0.00
Importe cargado
S/ 210.75
Titular de la cuenta
Carlos Alberto Quispe Mamani
Numero de operacion
000000110
Fecha y hora de la operacion
31 diciembre, 2025 23:46
Cuenta de origen
• 0303
Numero de tarjeta
• 3333
"""

# [REAL] Retiro en cajero BCP. Sacar tu dinero no es gastarlo.
BCP_RETIRO_CAJERO = """Hola Carlos Alberto,
Realizaste un retiro de S/ 350.00 con tu Tarjeta de Debito BCP en un Cajero BCP.
Montos
Total retirado
S/ 350.00
Comision por operacion
GRATIS
Operacion realizada
Retiro
Fecha y hora
13 de junio de 2026 - 07:30 PM
Numero de Tarjeta de Debito
************1111
Numero de operacion
1011
"""


def test_bbva_consumo_sin_simbolo_de_moneda():
    """El importe viene en una tabla "Monto: 10.50 / Moneda: PEN", sin S/.

    Todos los patrones exigian simbolo, asi que treinta y tres consumos reales
    coincidian con el parser y se tiraban por no encontrar importe.
    """
    parsed, motivo = parse_email(correo(REMITENTE_BBVA, "Has realizado un consumo con tu tarjeta BBVA", BBVA_CONSUMO_TABLA))
    assert parsed is not None, motivo
    assert parsed.amount == Decimal("10.50")
    assert parsed.currency == "PEN"
    assert parsed.last4 == "3333"
    assert normalize_merchant(parsed.merchant_raw) == "q uma soluciones"


def test_una_promocion_del_bbva_no_es_un_consumo_de_mil_soles():
    """La letra pequeña del TCEA menciona importes que no son movimientos."""
    parsed, motivo = parse_email(correo(REMITENTE_BBVA, "Arcangel en Lima, tienes 15% de desct.", BBVA_PROMO))
    assert parsed is None
    assert motivo


def test_pagar_tu_propia_tarjeta_bbva_no_es_gasto():
    parsed, motivo = parse_email(correo(REMITENTE_BBVA, "BBVA - Constancia Pago de Tarjetas propias", BBVA_PAGO_TARJETA))
    assert parsed is not None, motivo
    assert parsed.parser == "bbva_pago_tarjeta_propia"
    assert parsed.direction == "transferencia"
    assert parsed.amount == Decimal("210.75")
    assert parsed.last4 == "0303"          # la cuenta de origen, no la tarjeta pagada
    assert parsed.occurred_at.year == 2025 and parsed.occurred_at.month == 12


def test_retirar_del_cajero_bcp_no_es_gasto_ni_tiene_comercio():
    """El correo dice "con tu Tarjeta de Debito BCP en un Cajero BCP", asi que el
    parser de consumos lo cazaba primero: gasto de S/350 en "un cajero bcp"."""
    parsed, motivo = parse_email(correo(REMITENTE_BCP, "Realizaste un retiro en un cajero automatico BCP", BCP_RETIRO_CAJERO))
    assert parsed is not None, motivo
    assert parsed.parser == "bcp_retiro"
    assert parsed.direction == "transferencia"
    assert parsed.amount == Decimal("350.00")
    assert parsed.last4 == "1111"
    assert normalize_merchant(parsed.merchant_raw) is None


def test_recarga_de_celular_toma_el_precio_de_venta_no_el_desglose():
    """La boleta trae "Valor de venta 4.24" e "IGV 0.76"; se paga 5.00."""
    cuerpo = """S/
5
Numero recargado:
900 000 001
Fecha:
30 ene. 2026 - 11:21 a. m.
Operadora:
Bitel
Nº de operacion Yape:
00100012
Precio de venta
: S/
5.00
Valor de venta
: S/
4.24
IGV 18%
: S/
0.76
"""
    parsed, motivo = parse_email(correo(REMITENTE_YAPE, "Tu recarga en Yape ha sido confirmada", cuerpo))
    assert parsed is not None, motivo
    assert parsed.amount == Decimal("5.00")
    assert normalize_merchant(parsed.merchant_raw) == "bitel"


def test_el_saludo_de_una_palabra_se_completa_con_el_nombre_aprendido():
    """El BBVA saluda "Hola, CARLOS" y eso no identifica a nadie.

    Pero otros correos tuyos dicen el nombre entero ("Yapero: Carlos Alberto
    Quispe Mamani"). Aprendiendolo de ahi, un plineo a "Carlos A Quispe M"
    —tu, con las iniciales— se reconoce. Sin esto eran cuatro envios a ti mismo
    contados como gasto.
    """
    from app.correo.dominio.dinero_propio import es_envio_a_uno_mismo, nombre_completo_del_titular

    titular = nombre_completo_del_titular(
        "Yapero:\nCarlos Alberto Quispe Mamani\nNumero de yapero:\n*** *** 999"
    )
    assert titular == ["carlos", "alberto", "quispe", "mamani"]

    plineo = "Hola, CARLOS\nPlineaste S/ 30.00 a Carlos A Quispe M\nDestino:\nYape"
    assert not es_envio_a_uno_mismo(plineo, "Carlos A Quispe M")           # sin aprender
    assert es_envio_a_uno_mismo(plineo, "Carlos A Quispe M", titular)      # con el nombre

    # Y sigue sin colar un tercero que comparta el nombre de pila.
    assert not es_envio_a_uno_mismo(plineo, "Carlos Ramirez Soto", titular)
    assert not es_envio_a_uno_mismo(plineo, "Carlos M Perez", titular)


def test_el_saludo_del_propio_correo_manda_sobre_el_nombre_aprendido():
    """Lo que dice ESTE correo va primero: es autocontenido y no depende del
    orden en que se procesen los correos."""
    from app.correo.dominio.dinero_propio import es_envio_a_uno_mismo

    titular = ["carlos", "alberto", "quispe", "mamani"]
    bcp = "Hola Carlos Alberto,\nRealizaste una transferencia de S/ 400.00"
    assert es_envio_a_uno_mismo(bcp, "Carlos Alberto Quispe M.", titular)
    assert not es_envio_a_uno_mismo(bcp, "Kambista S.", titular)


# ---------------------------------------- falsos positivos hallados en la auditoria
def test_una_pasarela_de_pago_no_es_el_comercio():
    """"Culqui *LUNARIA" es LUNARIA cobrando por Culqi, no una tienda "Culqui".

    La regla era "si el primer fragmento es corto, quedate con el mas largo", y
    solo funcionaba con prefijos de tres letras como "PYU*". Con "Culqui*" se
    quedaba con la pasarela: catorce movimientos aparecian repartidos entre los
    comercios "culqui", "culqi" y "lunaria", que son el mismo sitio.
    """
    assert normalize_merchant("Culqui *LUNARIA") == "lunaria"
    assert normalize_merchant("Culqi *LUNARIA") == "lunaria"
    assert normalize_merchant("PYU*CINEMARK PERU") == "cinemark"
    # Y un comercio que simplemente empiece por algo corto sigue igual.
    assert normalize_merchant("RAPPI*RAPPI PERU LIMA PE") == "rappi"


def test_el_codigo_de_local_de_mifarma_varia_en_letras():
    """"MFAG36", "MFAA11", "MFA604", "MFA517" son todos Mifarma."""
    for crudo in ("MFAG36 LARCOMAR 2", "MFAA11 SAN MIGUEL MET",
                  "MFA604 SAN ISIDRO 1B", "MFA517 BARRANCO 2"):
        assert normalize_merchant(crudo) == "mifarma", crudo


def test_el_recorte_a_cuatro_palabras_no_deja_una_preposicion_al_final():
    """"EL RINCON DE LOS ABUELOS" se recorta a cuatro y quedaba "el rincon de"."""
    assert normalize_merchant("EL RINCON DE LOS ABUELOS") == "el rincon"


def test_pago_por_bim_desde_el_bcp_es_un_pago_a_persona():
    """BIM es otra billetera, y el BCP la notifica como consumo con tarjeta."""
    cuerpo = """Hola Carlos Alberto,
Realizaste un consumo de S/ 9.00 con tu Tarjeta de Debito BCP en BIM-MILTON DOUGLAS GARC.
Empresa
BIM-MILTON DOUGLAS GARC
Tarjeta
**** 1111
Fecha y hora
08 de abril de 2026 - 10:00 AM
Numero de operacion
00481034
"""
    parsed, motivo = parse_email(correo(REMITENTE_BCP, "Consumo", cuerpo))
    assert parsed is not None, motivo
    assert parsed.parser == "bcp_bim_persona"
    assert parsed.category_hint == "Pago a persona"
    assert normalize_merchant(parsed.merchant_raw) == "milton douglas garc"


def test_el_nombre_del_titular_se_aprende_en_su_forma_mas_completa():
    """El mismo buzon trae el nombre entero, abreviado y con los apellidos
    delante. Quedarse con el primero que aparezca hacia que la deteccion de
    envios a uno mismo dependiera del orden de la bandeja."""
    from app.correo.dominio.dinero_propio import _coincide_con_titular

    completo = ["carlos", "alberto", "quispe", "mamani"]
    al_reves = ["quispe", "mamani", "carlos", "alberto"]

    # La comparacion no mira el orden: las dos formas reconocen al mismo.
    for titular in (completo, al_reves):
        assert _coincide_con_titular(titular, "Carlos A Quispe M"), titular
        assert _coincide_con_titular(titular, "Quispe Mamani Carlos Alberto"), titular
        # Y ninguna de las dos deja pasar a un tercero que comparte dos nombres.
        assert not _coincide_con_titular(titular, "Carlos Alberto Perez Garcia"), titular
        assert not _coincide_con_titular(titular, "Carlos Ramirez Soto"), titular


def test_una_marca_de_dos_letras_no_se_confunde_con_una_pasarela():
    """"mp" era demasiado corto: se comia el fragmento bueno del descriptor."""
    assert normalize_merchant("MP HOGAR*LIMA") == "mp hogar"
    assert normalize_merchant("Culqui *LUNARIA") == "lunaria"      # esta si es pasarela


def test_la_pasarela_izipay_no_se_queda_con_el_comercio():
    """El BCP escribe "IZI*DATACELL": IZI es Izipay cobrando por la tienda.

    Funcionaba de chiripa (la regla de "si el primer trozo mide menos de 4, coge
    el mas largo"), pero con un comercio de nombre corto se habria quedado con
    la pasarela.
    """
    assert normalize_merchant("IZI*DATACELL") == "datacell"
    assert normalize_merchant("IZI*RC") == "rc"
