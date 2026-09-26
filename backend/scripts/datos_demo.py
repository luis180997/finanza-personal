"""Genera movimientos de ejemplo para explorar la interfaz sin conectar Gmail.

Son datos INVENTADOS con un patron de gasto verosimil para Lima. Sirven para
ver el panel con contenido antes de tener datos reales.

    python scripts/datos_demo.py            # ultimos 90 dias
    python scripts/datos_demo.py --borrar   # elimina solo los datos de demo
"""
from __future__ import annotations

import argparse
import random
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session, select  # noqa: E402

from app.plataforma.config import settings  # noqa: E402
from app.plataforma.db import engine, init_db  # noqa: E402
from app.compartido.dinero import to_cents  # noqa: E402
from app.movimientos.dominio.huella import build_hash  # noqa: E402
from app.compartido.comercio import normalize_merchant  # noqa: E402
from app.movimientos.dominio.entidades import Account, AccountType, Transaction  # noqa: E402
from app.clasificacion.dominio.entidades import Category  # noqa: E402
from app.compartido.tipos import Direction, PaymentMethod, Source, TxStatus  # noqa: E402
from app.plataforma.semilla import seed  # noqa: E402
from app.clasificacion.adaptadores import fabrica as clasificacion  # noqa: E402
from app.plataforma import respaldo  # noqa: E402

ETIQUETA_DEMO = "demo"

# comercio, categoria, cuenta, (monto minimo, maximo), probabilidad diaria
CATALOGO = [
    ("Menu La Esquina", "Almuerzo", "Efectivo", (12, 18), 0.62),
    ("Metropolitano", "Transporte publico", "Efectivo", (2.5, 5), 0.55),
    ("Tambo", "Snacks", "BCP Debito", (4, 14), 0.40),
    ("Rappi", "Delivery", "BCP Credito", (22, 55), 0.24),
    ("Pedidosya", "Delivery", "BCP Credito", (18, 48), 0.12),
    ("Uber", "Taxi", "BCP Credito", (9, 32), 0.30),
    ("Plaza Vea", "Mercado y supermercado", "BBVA Debito", (45, 190), 0.16),
    ("Tottus", "Mercado y supermercado", "BCP Debito", (35, 160), 0.10),
    ("Inkafarma", "Farmacia", "BCP Debito", (12, 70), 0.09),
    ("Starbucks", "Cafe", "BBVA Credito", (12, 26), 0.10),
    ("Cineplanet", "Cine y eventos", "BCP Credito", (25, 60), 0.05),
    ("Primax", "Combustible", "BCP Credito", (60, 140), 0.07),
    ("Sodimac", "Hogar", "BBVA Credito", (40, 260), 0.04),
    ("La Lucha Sangucheria", "Restaurante", "BCP Debito", (20, 48), 0.14),
]

# gastos fijos: dia del mes, comercio, categoria, cuenta, monto
RECURRENTES = [
    (3, "Alquiler", "Alquiler", "BCP Debito", 1200.0),
    (5, "Claro", "Plan movil", "BCP Credito", 69.9),
    (8, "Netflix", "Streaming", "BBVA Credito", 44.9),
    (8, "Spotify", "Streaming", "BBVA Credito", 26.9),
    (12, "Luz Del Sur", "Luz", "BCP Debito", 98.0),
    (12, "Sedapal", "Agua", "BCP Debito", 46.0),
    (15, "Smart Fit", "Gimnasio", "BCP Credito", 89.9),
]


# Comercios donde lo natural es pagar yapeando (bodegas, menus, sanguicherias).
# Yape no es una cuenta: es un medio de pago sobre BCP Debito.
COMERCIOS_YAPE = {"Tambo", "La Lucha Sangucheria", "Menu La Esquina"}

_MEDIO_POR_TIPO = {
    AccountType.efectivo: PaymentMethod.efectivo,
    AccountType.debito: PaymentMethod.debito,
    AccountType.credito: PaymentMethod.credito,
}


def crear(session, *, cuando, monto, direccion, comercio, cuenta, categoria, nota=None):
    cents = to_cents(round(monto, 2))
    merchant = normalize_merchant(comercio)
    dh = build_hash(
        source="demo", operation_number=None, occurred_at=cuando,
        amount_cents=cents, merchant=merchant, account_id=cuenta.id if cuenta else None,
    )
    if session.exec(select(Transaction).where(Transaction.dedupe_hash == dh)).first():
        return False

    tx = Transaction(
        occurred_at=cuando,
        booking_date=cuando.date(),
        amount_cents=cents,
        currency="PEN",
        direction=direccion,
        account_id=cuenta.id if cuenta else None,
        payment_method=(
            PaymentMethod.yape
            if comercio in COMERCIOS_YAPE and cuenta and cuenta.bank == "bcp"
            else _MEDIO_POR_TIPO.get(cuenta.type) if cuenta else None
        ),
        category_id=categoria.id if categoria else None,
        merchant=merchant,
        merchant_raw=comercio,
        description=comercio,
        necessity=categoria.default_necessity if categoria else None,
        tags=[ETIQUETA_DEMO],
        notes=nota,
        source=Source.manual,
        status=TxStatus.confirmada,
        confidence=1.0,
        dedupe_hash=dh,
    )
    if categoria is None:
        clasificacion.clasificador(session).aplicar(tx, {})
        tx.status = TxStatus.confirmada
    session.add(tx)
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=90)
    ap.add_argument("--borrar", action="store_true", help="elimina los movimientos de demo")
    ap.add_argument(
        "--aunque-haya-datos-reales", action="store_true",
        help="crea datos de demo aunque la base tenga movimientos reales (no recomendado)",
    )
    args = ap.parse_args()

    # Escribe en la base de DATABASE_URL, que por defecto es la de verdad. Los datos
    # inventados entran como registros manuales y solo la etiqueta los separa de los
    # tuyos: por eso primero se copia la base, y nunca se escribe sobre datos reales
    # salvo que lo pidas.
    origen = respaldo.ruta_sqlite(settings.database_url)
    if origen is not None and origen.is_file():
        copia = respaldo.copia_previa("datos de demostracion")
        print(f"Copia de seguridad previa: {copia.ruta}")

    init_db()
    random.seed(7)

    with Session(engine) as session:
        if args.borrar:
            n = protegidos = 0
            for tx in session.exec(select(Transaction)).all():
                if ETIQUETA_DEMO not in (tx.tags or []):
                    continue
                if tx.locked_by_user:
                    protegidos += 1       # lo corregiste tu: no se borra a ciegas
                    continue
                session.delete(tx)
                n += 1
            session.commit()
            if n and origen is not None:
                # Borrarlos es a proposito: que el aviso de copias no lo tome por perdida.
                respaldo.aceptar_perdida(settings.database_url, settings.carpeta_respaldos)
            print(f"Eliminados {n} movimientos de demostracion.")
            if protegidos:
                print(f"{protegidos} no se borraron porque los corregiste tu (estan protegidos).")
            return 0

        reales = sum(
            1 for tx in session.exec(select(Transaction)).all()
            if ETIQUETA_DEMO not in (tx.tags or [])
        )
        if reales and not args.aunque_haya_datos_reales:
            print(
                f"La base {settings.database_url} tiene {reales} movimientos reales y no se "
                "mezclan con datos inventados. Usa una base aparte, por ejemplo:\n"
                "  DATABASE_URL=sqlite:///data/demo.db python scripts/datos_demo.py"
            )
            return 1

        seed(session)

        cuentas = {a.name: a for a in session.exec(select(Account)).all()}
        categorias = {c.name: c for c in session.exec(select(Category)).all()}
        hoy = date.today()
        creados = 0

        for i in range(args.dias, -1, -1):
            dia = hoy - timedelta(days=i)
            finde = dia.weekday() >= 5

            for comercio, cat, cuenta, (lo, hi), prob in CATALOGO:
                p = prob * (1.35 if finde and cat in ("Delivery", "Restaurante", "Cine y eventos") else 1.0)
                p = p * (0.35 if not finde and cat == "Cine y eventos" else 1.0)
                if random.random() > p:
                    continue
                cuando = datetime.combine(dia, time(random.randint(7, 22), random.randint(0, 59)))
                creados += crear(
                    session, cuando=cuando, monto=random.uniform(lo, hi),
                    direccion=Direction.gasto, comercio=comercio,
                    cuenta=cuentas.get(cuenta), categoria=categorias.get(cat),
                )

            for dia_mes, comercio, cat, cuenta, monto in RECURRENTES:
                if dia.day != dia_mes:
                    continue
                creados += crear(
                    session, cuando=datetime.combine(dia, time(9, 0)), monto=monto,
                    direccion=Direction.gasto, comercio=comercio,
                    cuenta=cuentas.get(cuenta), categoria=categorias.get(cat),
                )

            if dia.day == 1:
                creados += crear(
                    session, cuando=datetime.combine(dia, time(10, 0)), monto=4200.0,
                    direccion=Direction.ingreso, comercio="Sueldo",
                    cuenta=cuentas.get("BCP Debito"), categoria=categorias.get("Sueldo"),
                )
            if dia.day == 20 and random.random() < 0.6:
                creados += crear(
                    session, cuando=datetime.combine(dia, time(16, 0)),
                    monto=random.uniform(300, 900), direccion=Direction.ingreso,
                    comercio="Proyecto freelance", cuenta=cuentas.get("BCP Debito"),
                    categoria=categorias.get("Freelance"),
                )
            # pago de tarjeta: transferencia, NO debe contar como gasto
            if dia.day == 25:
                creados += crear(
                    session, cuando=datetime.combine(dia, time(11, 0)),
                    monto=random.uniform(600, 1400), direccion=Direction.transferencia,
                    comercio="Pago de tarjeta BCP", cuenta=cuentas.get("BCP Debito"),
                    categoria=categorias.get("Pago de tarjeta"),
                )

        session.commit()
        print(f"Creados {creados} movimientos de demostracion en los ultimos {args.dias} dias.")
        print("Para borrarlos:  python scripts/datos_demo.py --borrar")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
