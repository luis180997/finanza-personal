"""Las cuentas con las que arranca la app."""
from __future__ import annotations

from app.movimientos.dominio.entidades import AccountType

# Yape NO es una cuenta: debita directo de BCP Debito y el BCP no manda un
# correo aparte por el yapeo. Es un medio de pago (PaymentMethod.yape) sobre esa
# cuenta. Ponerlo como cuenta separada fingiria un saldo propio que no existe.
DEFAULT_ACCOUNTS = [
    dict(name="BCP Debito", bank="bcp", type=AccountType.debito,
         aliases=["bcp", "cuenta bcp", "ahorro bcp", "clasica", "yape"]),
    dict(name="BCP Credito", bank="bcp", type=AccountType.credito,
         aliases=["tarjeta bcp", "credito bcp"]),
    dict(name="BBVA Debito", bank="bbva", type=AccountType.debito,
         aliases=["bbva", "cuenta bbva"]),
    dict(name="BBVA Credito", bank="bbva", type=AccountType.credito,
         aliases=["tarjeta bbva", "credito bbva"]),
    dict(name="Efectivo", bank="efectivo", type=AccountType.efectivo, aliases=["efectivo", "cash"]),
]
