"""Migraciones de DATOS, versionadas y de una sola vez.

El esquema lo crea SQLModel (`create_all`), pero `create_all` no sabe mover datos
cuando cambia la taxonomia. Cada migracion tiene una clave: al terminar se anota
en la tabla `kv` y no vuelve a ejecutarse. Corren al arrancar, antes de la
semilla, y cada una se confirma entera o no se confirma: si falla a mitad, la
sesion se descarta sin commit y la app no arranca con datos a medio mover.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import date, datetime, timezone

from sqlmodel import Session, col, select

from app.analitica.dominio.entidades import Budget
from app.clasificacion.dominio.entidades import Category, Rule
from app.compartido.tipos import Direction, Source, TxStatus
from app.movimientos.dominio.entidades import Transaction
from app.movimientos.dominio.movimiento import descartar
from app.plataforma.config import settings
from app.plataforma.kv import KV

log = logging.getLogger("finanzas.migraciones")

# Tiendas de conveniencia: lo que se compra ahi es snack. Nombres ya normalizados
# (normalize.py convierte "TAMBO MENDIOLA-C20" en "tambo").
COMERCIOS_SNACKS = {"oxxo", "tambo", "listo"}
_NOTA_SNACK = re.compile(r"\btorta\b|\byogurt\b|\bempanada\b|\bhelado\b|\bsnacks?\b", re.I)
_NOTA_CAFE = re.compile(r"\bcaf[eé]\b", re.I)


def _fundir(session: Session, origen: Category, destino: Category) -> None:
    """Pasa a `destino` todo lo que apunta a `origen` y borra `origen`."""
    for t in session.exec(select(Transaction).where(Transaction.category_id == origen.id)).all():
        t.category_id = destino.id
        session.add(t)
    for r in session.exec(select(Rule).where(Rule.set_category_id == origen.id)).all():
        r.set_category_id = destino.id
        session.add(r)
    destino_tiene_tope = session.exec(
        select(Budget).where(Budget.category_id == destino.id)
    ).first()
    for b in session.exec(select(Budget).where(Budget.category_id == origen.id)).all():
        if destino_tiene_tope:
            session.delete(b)
        else:
            b.category_id = destino.id
            session.add(b)
    session.flush()
    session.delete(origen)


def _cafe_y_snacks(session: Session) -> str:
    """Set. 2026: "Cafe y snacks" se parte en "Cafe" y "Snacks".

    - La categoria existente se RENOMBRA a "Cafe". Conserva su id, y con el todo
      lo que la apunta: movimientos, topes, reglas y la memoria de comercio.
    - A "Snacks" pasan solo los movimientos donde el propio dato lo dice sin duda:
      compras en tiendas de conveniencia (Tambo, Oxxo, Listo), y filas del Excel
      cuya nota habla de snack (torta, empanada, yogurt, helado) sin mencionar cafe.
    - Un movimiento del correo o manual que corregiste a mano (confianza 1.0) no
      se mueve: tu decision manda (CLAUDE.md, regla 1). Se queda en "Cafe".
    """
    vieja = session.exec(select(Category).where(Category.name == "Cafe y snacks")).first()
    if vieja is None:
        return "no habia 'Cafe y snacks': nada que migrar"
    padre_id = vieja.parent_id

    def hermana(nombre: str) -> Category | None:
        return session.exec(
            select(Category).where(Category.name == nombre, Category.parent_id == padre_id)
        ).first()

    cafe = hermana("Cafe")
    if cafe is None:
        vieja.name = "Cafe"
        session.add(vieja)
        cafe = vieja
    else:
        _fundir(session, vieja, cafe)
    session.flush()

    snacks = hermana("Snacks")
    if snacks is None:
        snacks = Category(
            name="Snacks", parent_id=padre_id, kind=cafe.kind, color=cafe.color,
            icon=cafe.icon, default_necessity=cafe.default_necessity,
            is_system=True, sort=cafe.sort + 1,
        )
        session.add(snacks)
        session.flush()

    movidos = 0
    for t in session.exec(select(Transaction).where(Transaction.category_id == cafe.id)).all():
        if t.source == Source.excel:
            nota = t.notes or ""
            es_snack = bool(_NOTA_SNACK.search(nota)) and not _NOTA_CAFE.search(nota)
        else:
            es_snack = t.confidence < 1.0 and (t.merchant or "") in COMERCIOS_SNACKS
        if es_snack:
            t.category_id = snacks.id
            session.add(t)
            movidos += 1
    return f"'Cafe y snacks' renombrada a 'Cafe'; {movidos} movimiento(s) pasaron a 'Snacks'"


def _tiendas_a_snacks(session: Session) -> str:
    """Set. 2026: dos tiendas pasaron de "Cafe" a "Snacks".

    Ya se aplico en su base (con otra clave). Sus nombres no se escriben aqui a
    proposito: el repositorio es publico y son datos personales (ver
    AGENTS.md, seccion 5). En una base nueva no hay nada que mover, asi que no hace
    nada; se conserva para que la lista de migraciones cuente la historia completa.
    """
    return "sin cambios: se aplico en la base del usuario con su clave original"


def _proteger_tus_registros(session: Session) -> str:
    """Set. 2026: marca como protegidos los movimientos que registraste o corregiste.

    Hasta ahora "lo edito el usuario" se deducia de confidence = 1.0, y no bastaba:
    el importador del Excel tambien pone 1.0, y los borrados masivos no miraban
    nada. Se protegen:
      - los registros manuales;
      - los del correo con confianza 1.0: la app sola nunca llega a 1.0 (el tope
        automatico es 0.98), asi que solo pudiste ponerla tu al corregirlos;
      - cualquiera que se modifico mas de un minuto despues de crearse.
    """
    protegidos = 0
    for t in session.exec(select(Transaction)).all():
        editado = (
            t.updated_at is not None and t.created_at is not None
            and (t.updated_at - t.created_at).total_seconds() > 60
        )
        if (
            t.source == Source.manual
            or (t.source != Source.excel and t.confidence >= 1.0)
            or editado
        ):
            t.locked_by_user = True
            t.user_edited_at = t.updated_at
            session.add(t)
            protegidos += 1
    return f"{protegidos} movimiento(s) protegidos"


def _dolares_a_revisar(session: Session) -> str:
    """Set. 2026: el BCP avisa algunos cobros en dolares ("$ 8.85") y los debita en
    soles, pero el correo no dice cuantos. La app los sumaba como si fueran soles.
    Pasan a Por revisar para que escribas el importe que te cobro el banco.

    No se tocan los que corregiste tu (protegidos), las transferencias (no cuentan
    como gasto) ni lo ya ignorado o marcado como duplicado.
    """
    movidos = 0
    for t in session.exec(
        select(Transaction).where(
            Transaction.currency != settings.base_currency,
            Transaction.direction != Direction.transferencia,
            Transaction.status == TxStatus.confirmada,
            Transaction.locked_by_user == False,  # noqa: E712
        )
    ).all():
        t.status = TxStatus.por_revisar
        session.add(t)
        movidos += 1
    return f"{movidos} movimiento(s) en otra moneda pasaron a Por revisar"


def _almuerzo(session: Session) -> str:
    """Set. 2026: "Almuerzo diario" pasa a llamarse "Almuerzo".

    Se RENOMBRA, no se crea otra: conserva su id, y con el todo lo que la apunta
    (movimientos, topes, reglas, memoria de comercio). Sin esta migracion la
    semilla, que busca por nombre, crearia "Almuerzo" al lado de la vieja.
    """
    vieja = session.exec(select(Category).where(Category.name == "Almuerzo diario")).first()
    if vieja is None:
        return "no habia 'Almuerzo diario': nada que migrar"
    nueva = session.exec(
        select(Category).where(Category.name == "Almuerzo", Category.parent_id == vieja.parent_id)
    ).first()
    if nueva is not None:
        _fundir(session, vieja, nueva)
        return "'Almuerzo diario' fundida en la 'Almuerzo' que ya existia"
    vieja.name = "Almuerzo"
    session.add(vieja)
    return "'Almuerzo diario' renombrada a 'Almuerzo'"


def _agosto_pasa_al_excel(session: Session) -> str:
    """26/09/2026: agosto de 2026 pasa a salir del Excel.

    Hasta hoy el Excel mandaba hasta el 31/07/2026 y el correo desde el 01/08. El usuario
    decidio que agosto tambien saliera del Excel (la frontera vive en
    compartido/corte.py). Tener los dos contaria el gasto de agosto dos veces, asi que
    los movimientos del correo de agosto se DESCARTAN: quedan como ignorados y
    protegidos, no cuentan en ningun total, el siguiente sincronizado no los resucita
    y se pueden recuperar cambiandoles el estado. No se borra ninguno. Las filas de
    agosto del Excel entran aparte, en su propio lote de importacion (deshacible).

    No se tocan los protegidos (tus decisiones, CLAUDE.md regla 1) ni los que ya no
    contaban (duplicados e ignorados).
    """
    ahora = datetime.now(timezone.utc)
    nota = "Descartado el 26/09/2026: desde entonces agosto de 2026 sale del Excel."
    descartados = protegidos = 0
    for t in session.exec(
        select(Transaction).where(
            Transaction.source == Source.gmail,
            Transaction.booking_date >= date(2026, 8, 1),
            Transaction.booking_date <= date(2026, 8, 31),
            col(Transaction.status).in_([TxStatus.confirmada, TxStatus.por_revisar]),
        )
    ).all():
        if t.locked_by_user:
            protegidos += 1
            continue
        descartar(t, ahora)
        t.notes = f"{t.notes}\n{nota}" if t.notes else nota
        session.add(t)
        descartados += 1
    return (
        f"{descartados} movimiento(s) del correo de agosto descartados; "
        f"{protegidos} protegido(s) sin tocar"
    )


MIGRACIONES: list[tuple[str, Callable[[Session], str]]] = [
    ("2026-09-cafe-y-snacks", _cafe_y_snacks),
    ("2026-09-tiendas-a-snacks", _tiendas_a_snacks),
    ("2026-09-proteger-tus-registros", _proteger_tus_registros),
    ("2026-09-dolares-a-revisar", _dolares_a_revisar),
    ("2026-09-almuerzo", _almuerzo),
    ("2026-09-agosto-pasa-al-excel", _agosto_pasa_al_excel),
]


def aplicar(session: Session, antes: Callable[[], None] | None = None) -> list[str]:
    """Ejecuta las migraciones pendientes. Devuelve las claves que se aplicaron.

    `antes` se llama una sola vez y solo si hay algo pendiente: es el respaldo
    previo. Mover datos sin una copia es justo lo que no se vuelve a hacer.
    """
    pendientes = [
        (clave, migracion) for clave, migracion in MIGRACIONES
        if not session.get(KV, f"migracion:{clave}")
    ]
    if pendientes and antes is not None:
        antes()
    aplicadas = []
    for clave, migracion in pendientes:
        marca = f"migracion:{clave}"
        resultado = migracion(session)
        session.add(KV(key=marca, value=resultado[:500]))
        session.commit()
        log.info("migracion %s: %s", clave, resultado)
        aplicadas.append(clave)
    return aplicadas
