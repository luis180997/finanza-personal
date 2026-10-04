"""Taxonomia de categorias y reglas de ejemplo.

La taxonomia es de 2 niveles (categoria > subcategoria). Nace de tu Excel
(Alimentos, Transporte, Taxi, Delivery, Otros gastos) pero corrige tres cosas:

  1. "Taxi" y "Delivery" no son hermanos de "Transporte" y "Alimentos":
     son subcategorias. Asi puedes ver "Transporte total" y ademas el detalle.
  2. "Otros gastos" era un cajon de sastre que en tu muestra se llevaba el 82%
     de un dia (385.89 de 472.5). Se desglosa en categorias reales.
  3. Los ingresos tambien se clasifican (sueldo, freelance, reembolso).

La NECESIDAD se define por subcategoria, no por categoria: "Alimentacion" es
esencial, pero dentro de ella el mercado es esencial y el delivery no. Si se
heredara del padre, el indicador de fuga marcaria cero siempre.
"""
from __future__ import annotations

from app.compartido.tipos import Necessity

ESE = Necessity.esencial
DIS = Necessity.discrecional
EVI = Necessity.evitable

# categoria, color, icono, necesidad por defecto, [(subcategoria, necesidad)]
EXPENSE_TREE: list[tuple[str, str, str, Necessity | None, list[tuple[str, Necessity | None]]]] = [
    ("Alimentacion", "#2a78d6", "utensils", ESE, [
        ("Mercado y supermercado", ESE),
        ("Almuerzo", ESE),   # hasta set. 2026, "Almuerzo diario" (plataforma/migraciones.py)
        ("Restaurante", DIS),
        ("Delivery", EVI),
        # Hasta set. 2026 eran una sola, "Cafe y snacks" (ver app/plataforma/migraciones.py).
        ("Cafe", DIS),       # cafeterias: Starbucks, Juan Valdez...
        ("Snacks", DIS),     # tiendas: Tambo, Oxxo, Listo...
    ]),
    ("Transporte", "#eb6834", "car", ESE, [
        ("Transporte publico", ESE),
        # Oct. 2026: el colectivo (auto compartido con ruta fija, informal) no es
        # transporte publico ni taxi. Se paga en efectivo o por Yape a una persona,
        # asi que no hay comercio que reconocer: se elige a mano.
        ("Colectivo", ESE),
        ("Taxi", DIS),
        ("Combustible", ESE),
        ("Mantenimiento vehiculo", ESE),
        ("Estacionamiento", DIS),
        ("Peajes", ESE),
    ]),
    ("Vivienda", "#1baf7a", "home", ESE, [
        ("Alquiler", ESE), ("Luz", ESE), ("Agua", ESE),
        ("Internet y cable", ESE), ("Gas", ESE), ("Mantenimiento", ESE),
    ]),
    ("Salud", "#eda100", "heart-pulse", ESE, [
        ("Farmacia", ESE), ("Consultas", ESE), ("Dentista", ESE),
        ("Seguro de salud", ESE), ("Gimnasio", DIS),
    ]),
    # Nuevas (set. 2026): gastos frecuentes que antes caian en "Otros gastos".
    ("Cuidado personal", "#e87ba4", "scissors", DIS, [
        ("Peluqueria y barberia", ESE), ("Cosmetica e higiene", ESE), ("Optica", ESE),
    ]),
    ("Mascotas", "#1baf7a", "paw-print", ESE, [
        ("Alimento", ESE), ("Veterinario", ESE), ("Accesorios y aseo", DIS),
    ]),
    ("Telefonia y suscripciones", "#e87ba4", "smartphone", DIS, [
        ("Plan movil", ESE), ("Internet movil", ESE),
        ("Streaming", DIS), ("Software y nube", DIS), ("Otras suscripciones", DIS),
    ]),
    ("Compras", "#008300", "shopping-bag", DIS, [
        ("Ropa y calzado", DIS), ("Tecnologia", DIS), ("Hogar", DIS), ("Regalos", DIS),
    ]),
    ("Entretenimiento", "#4a3aa7", "party-popper", DIS, [
        ("Salidas y bares", DIS), ("Cine y eventos", DIS), ("Viajes", DIS), ("Hobbies", DIS),
    ]),
    ("Educacion", "#e34948", "graduation-cap", ESE, [
        ("Cursos", ESE), ("Libros", ESE), ("Certificaciones", ESE),
    ]),
    ("Financiero", "#898781", "landmark", ESE, [
        ("Comisiones bancarias", EVI),      # casi siempre se pueden evitar
        ("Intereses", EVI),                 # intereses de tarjeta = fuga pura
        ("Impuestos", ESE), ("Seguros", ESE), ("Ahorro e inversion", ESE),
    ]),
    ("Personas", "#898781", "users", DIS, [
        ("Familia", ESE),
        # Un yapeo a una persona no dice para que fue. Cae aqui y la bandeja de
        # revision te lo recuerda hasta que lo muevas a su categoria real.
        ("Pago a persona", DIS),
        ("Prestamos a terceros", DIS),
        ("Donaciones", DIS),
    ]),
    ("Tramites y servicios", "#4a3aa7", "file-text", ESE, [
        ("Notaria y legal", ESE), ("Tramites del Estado", ESE), ("Envios y courier", DIS),
    ]),
    ("Sin clasificar", "#898781", "help-circle", None, []),
]

INCOME_TREE: list[tuple[str, str, str, list[str]]] = [
    ("Ingresos", "#0ca30c", "wallet",
     ["Sueldo", "Freelance", "Reembolso", "Venta", "Intereses ganados", "Otros ingresos"]),
]

TRANSFER_TREE: list[tuple[str, str, str, list[str]]] = [
    ("Movimientos internos", "#898781", "arrow-left-right",
     ["Pago de tarjeta", "Recarga de Yape", "Retiro de efectivo", "Entre cuentas propias"]),
]

# Reglas de ejemplo: muestran la sintaxis y cubren los casos mas frecuentes.
SEED_RULES = [
    ("Delivery por app", "merchant", "contains", "rappi", "Delivery", EVI, 10),
    ("PedidosYa es delivery", "merchant", "contains", "pedidosya", "Delivery", EVI, 10),
    ("Taxi", "merchant", "regex", r"uber|cabify|indriver|didi|beat", "Taxi", None, 20),
    ("Supermercados", "merchant", "regex",
     r"plaza vea|tottus|metro|wong|vivanda|makro|mass", "Mercado y supermercado", ESE, 30),
    ("Farmacias", "merchant", "regex", r"inkafarma|mifarma|boticas|farmacia", "Farmacia", ESE, 30),
    ("Grifos", "merchant", "regex", r"primax|repsol|petroperu|grifo", "Combustible", ESE, 30),
    ("Streaming", "merchant", "regex",
     r"netflix|spotify|hbo|disney|prime video|crunchyroll", "Streaming", DIS, 40),
    ("Telefonia", "merchant", "regex", r"claro|movistar|entel|bitel", "Plan movil", ESE, 40),
    ("Servicios del hogar", "merchant", "regex", r"sedapal|luz del sur|enel|calidda", "Luz", ESE, 40),
]
