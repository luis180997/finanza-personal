"""Migraciones de datos, sobre una base propia en tmp_path (nunca la de la app)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.plataforma import migraciones
from app.analitica.dominio.entidades import Budget
from app.clasificacion.dominio.entidades import Category
from app.compartido.tipos import Direction, Necessity, Source, TxStatus
from app.movimientos.dominio.entidades import Transaction
from app.plataforma.semilla import seed

TODAS = [
    "2026-09-cafe-y-snacks",
    "2026-09-tiendas-a-snacks",
    "2026-09-proteger-tus-registros",
    "2026-09-dolares-a-revisar",
    "2026-09-almuerzo",
    "2026-09-agosto-pasa-al-excel",
]


@pytest.fixture()
def sesion(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'migraciones.db').as_posix()}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
    engine.dispose()


def _tx(s: Session, cat_id: int | None, cents: int, n: int, *, source: Source,
        merchant: str | None = None, notes: str | None = None, confianza: float = 0.95,
        editado_seg: int = 0) -> int:
    creado = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
    t = Transaction(
        occurred_at=datetime(2026, 9, 1, 12), booking_date=date(2026, 9, 1),
        amount_cents=cents, direction=Direction.gasto, category_id=cat_id,
        merchant=merchant, notes=notes, source=source, status=TxStatus.confirmada,
        confidence=confianza, dedupe_hash=f"migracion-{n}",
        created_at=creado, updated_at=creado + timedelta(seconds=editado_seg),
    )
    s.add(t)
    s.commit()
    return t.id


def test_cafe_y_snacks_se_parte_sin_perder_nada(sesion):
    s = sesion
    alimentacion = Category(name="Alimentacion", kind=Direction.gasto, color="#2a78d6",
                            icon="utensils", is_system=True, sort=0)
    s.add(alimentacion)
    s.commit()
    vieja = Category(name="Cafe y snacks", parent_id=alimentacion.id, kind=Direction.gasto,
                     color="#2a78d6", icon="utensils",
                     default_necessity=Necessity.discrecional, is_system=True, sort=4)
    s.add(vieja)
    s.commit()
    vieja_id = vieja.id
    s.add(Budget(category_id=vieja_id, amount_cents=5000))
    s.commit()

    starbucks = _tx(s, vieja_id, 1750, 1, source=Source.gmail, merchant="starbucks")
    tambo = _tx(s, vieja_id, 449, 2, source=Source.gmail, merchant="tambo")
    tambo_corregido = _tx(s, vieja_id, 500, 3, source=Source.gmail, merchant="tambo",
                          confianza=1.0)
    torta = _tx(s, vieja_id, 2190, 4, source=Source.excel, notes="Torta", confianza=1.0)
    cafe_y_torta = _tx(s, vieja_id, 3000, 5, source=Source.excel, notes="Café y torta",
                       confianza=1.0)
    cafe_excel = _tx(s, vieja_id, 1640, 6, source=Source.excel, notes="Café", confianza=1.0)

    assert migraciones.aplicar(s) == TODAS
    seed(s)       # la semilla, que ya conoce la taxonomia nueva, no duplica nada

    cafe = s.exec(select(Category).where(Category.name == "Cafe")).one()
    snacks = s.exec(select(Category).where(Category.name == "Snacks")).one()
    assert cafe.id == vieja_id                      # renombrada: conserva el id
    assert snacks.parent_id == alimentacion.id
    assert s.exec(select(Category).where(Category.name == "Cafe y snacks")).first() is None

    def categoria(tx_id: int) -> int:
        return s.get(Transaction, tx_id).category_id

    assert categoria(starbucks) == cafe.id
    assert categoria(tambo) == snacks.id
    assert categoria(tambo_corregido) == cafe.id    # tu correccion manual manda
    assert categoria(torta) == snacks.id
    assert categoria(cafe_y_torta) == cafe.id       # menciona cafe: no se adivina
    assert categoria(cafe_excel) == cafe.id
    assert s.exec(select(Budget)).one().category_id == cafe.id

    assert migraciones.aplicar(s) == []             # no se repite


def test_en_una_base_nueva_no_hay_nada_que_mover(sesion):
    assert migraciones.aplicar(sesion) == TODAS
    seed(sesion)
    nombres = {c.name for c in sesion.exec(select(Category)).all()}
    assert {"Cafe", "Snacks"} <= nombres
    assert "Cafe y snacks" not in nombres


def test_se_protegen_los_registros_que_hiciste_o_corregiste(sesion):
    s = sesion
    manual = _tx(s, None, 1000, 11, source=Source.manual, confianza=1.0)
    corregido = _tx(s, None, 1001, 12, source=Source.gmail, confianza=1.0)
    automatico = _tx(s, None, 1002, 13, source=Source.gmail, confianza=0.9)
    excel = _tx(s, None, 1003, 14, source=Source.excel, confianza=1.0)
    excel_editado = _tx(s, None, 1004, 15, source=Source.excel, confianza=1.0,
                        editado_seg=3600)

    migraciones.aplicar(s)

    def protegido(tx_id: int) -> bool:
        return s.get(Transaction, tx_id).locked_by_user

    assert protegido(manual) and protegido(corregido) and protegido(excel_editado)
    # Ni lo que clasifico la app sola ni el Excel tal cual se importo
    assert not protegido(automatico) and not protegido(excel)
    assert s.get(Transaction, manual).user_edited_at is not None


def test_los_cobros_en_dolares_pasan_a_revisar_salvo_lo_tuyo_y_las_transferencias(sesion):
    s = sesion

    def en_dolares(n: int, direccion=Direction.gasto, protegido=False) -> int:
        t = Transaction(
            occurred_at=datetime(2026, 9, 18, 3, 30), booking_date=date(2026, 9, 18),
            amount_cents=885, currency="USD", direction=direccion, source=Source.gmail,
            status=TxStatus.confirmada, confidence=0.9, dedupe_hash=f"dolares-{n}",
            locked_by_user=protegido,
        )
        s.add(t)
        s.commit()
        return t.id

    netflix = en_dolares(1)
    ya_corregido = en_dolares(2, protegido=True)
    casa_de_cambio = en_dolares(3, Direction.transferencia)
    en_soles = _tx(s, None, 900, 4, source=Source.gmail)

    migraciones.aplicar(s)

    def estado(tx_id: int) -> TxStatus:
        return s.get(Transaction, tx_id).status

    assert estado(netflix) == TxStatus.por_revisar
    assert estado(ya_corregido) == TxStatus.confirmada
    assert estado(casa_de_cambio) == TxStatus.confirmada
    assert estado(en_soles) == TxStatus.confirmada


def test_almuerzo_diario_se_renombra_sin_duplicarse(sesion):
    s = sesion
    alimentacion = Category(name="Alimentacion", kind=Direction.gasto, color="#2a78d6",
                            icon="utensils", is_system=True, sort=0)
    s.add(alimentacion)
    s.commit()
    vieja = Category(name="Almuerzo diario", parent_id=alimentacion.id, kind=Direction.gasto,
                     color="#2a78d6", icon="utensils", default_necessity=Necessity.esencial,
                     is_system=True, sort=1)
    s.add(vieja)
    s.commit()
    vieja_id = vieja.id
    menu = _tx(s, vieja_id, 1500, 21, source=Source.manual, confianza=1.0)

    migraciones.aplicar(s)
    seed(s)       # busca por nombre: sin la migracion crearia otra "Almuerzo"

    almuerzos = s.exec(select(Category).where(Category.name == "Almuerzo")).all()
    assert [c.id for c in almuerzos] == [vieja_id]      # renombrada: conserva el id
    assert s.exec(select(Category).where(Category.name == "Almuerzo diario")).first() is None
    assert s.get(Transaction, menu).category_id == vieja_id


def test_peluqueria_pasa_a_esencial_en_una_base_existente(sesion):
    s = sesion
    cuidado = Category(name="Cuidado personal", kind=Direction.gasto, color="#e87ba4",
                       icon="scissors", is_system=True, sort=4)
    s.add(cuidado)
    s.commit()
    s.add(Category(name="Peluqueria y barberia", parent_id=cuidado.id, kind=Direction.gasto,
                   color="#e87ba4", icon="scissors",
                   default_necessity=Necessity.discrecional, is_system=True, sort=0))
    s.commit()

    seed(s)

    peluqueria = s.exec(select(Category).where(Category.name == "Peluqueria y barberia")).one()
    assert peluqueria.default_necessity == Necessity.esencial


def test_agosto_pasa_al_excel_sin_borrar_nada(sesion):
    """26/09/2026: agosto sale del Excel. Lo del correo de agosto que contaba queda
    descartado (ignorado y protegido); nada se borra y nada mas se toca."""
    s = sesion

    def mov(n: int, dia: date, *, source=Source.gmail, status=TxStatus.confirmada,
            protegido=False, notas=None) -> int:
        t = Transaction(
            occurred_at=datetime(dia.year, dia.month, dia.day, 12), booking_date=dia,
            amount_cents=1000 + n, direction=Direction.gasto, source=source, status=status,
            confidence=0.9, dedupe_hash=f"agosto-{n}", locked_by_user=protegido, notes=notas,
        )
        s.add(t)
        s.commit()
        return t.id

    primero = mov(1, date(2026, 8, 1))
    ultimo = mov(2, date(2026, 8, 31), notas="nota previa")
    por_revisar = mov(3, date(2026, 8, 15), status=TxStatus.por_revisar)
    duplicado = mov(4, date(2026, 8, 15), status=TxStatus.duplicada)
    protegido = mov(5, date(2026, 8, 20), protegido=True)
    setiembre = mov(6, date(2026, 9, 1))
    julio = mov(7, date(2026, 7, 31))
    excel = mov(8, date(2026, 8, 10), source=Source.excel)
    manual = mov(9, date(2026, 8, 12), source=Source.manual)

    migraciones.aplicar(s)

    def tx(tx_id: int) -> Transaction:
        return s.get(Transaction, tx_id)

    for descartado in (primero, ultimo, por_revisar):
        assert tx(descartado).status == TxStatus.ignorada
        assert tx(descartado).locked_by_user            # el sincronizado no lo resucita
        assert "agosto de 2026 sale del Excel" in tx(descartado).notes
    assert tx(ultimo).notes.startswith("nota previa")  # la nota anterior se conserva
    assert tx(duplicado).status == TxStatus.duplicada
    assert tx(protegido).status == TxStatus.confirmada   # tu decision manda
    for intacto in (setiembre, julio, excel, manual):
        assert tx(intacto).status == TxStatus.confirmada
        assert not (tx(intacto).notes or "").endswith("sale del Excel.")
    # (el manual si queda protegido, pero por la migracion "proteger-tus-registros")
    assert not any(tx(i).locked_by_user for i in (setiembre, julio, excel))
    assert len(s.exec(select(Transaction)).all()) == 9    # no se borro nada


def test_el_respaldo_previo_se_hace_una_sola_vez_y_solo_si_hay_pendientes(sesion):
    llamadas = []
    migraciones.aplicar(sesion, antes=lambda: llamadas.append(1))
    migraciones.aplicar(sesion, antes=lambda: llamadas.append(1))
    assert llamadas == [1]
