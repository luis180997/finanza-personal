"""La frontera entre las dos fuentes de verdad (CLAUDE.md, regla 3), y las fechas
que pueden existir.

Hasta el 31/08/2026 manda el Excel; desde el 01/09/2026, los correos del banco y
lo que registras a mano. Vive en un solo sitio para que el importador, el pipeline
de correo y la edicion de movimientos no puedan discrepar: los mensajes tambien
salen de aqui, asi que mover la frontera es cambiar estas dos fechas.

Hasta el 26/09/2026 la frontera era el 31/07/2026. Ese dia el usuario decidio que agosto
de 2026 tambien saliera del Excel (plataforma/migraciones.py, "agosto-pasa-al-excel").
"""
from datetime import date

ULTIMO_DIA_EXCEL = date(2026, 8, 31)
FECHA_INICIO_AUTOMATIZADO = date(2026, 9, 1)

# Las mismas fechas, como se escriben en los mensajes.
ULTIMO_DIA_EXCEL_TEXTO = f"{ULTIMO_DIA_EXCEL:%d/%m/%Y}"
FECHA_INICIO_AUTOMATIZADO_TEXTO = f"{FECHA_INICIO_AUTOMATIZADO:%d/%m/%Y}"

# Fuera de estos años no puede haber movimientos tuyos. Un movimiento del año 1 o
# del 9999 (un tecleo, un script, un correo mal leido) estiraba "todo el historial"
# a decenas de miles de meses y colgaba Tendencia.
ANIO_MIN = 2000
ANIO_MAX = 2100
