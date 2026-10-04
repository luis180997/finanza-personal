"""Migraciones de esquema (Alembic), cada una sobre su propia base en tmp_path."""
from __future__ import annotations

import shutil
from datetime import date, datetime

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import event, inspect
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine

import app.plataforma.db as app_db
from app.compartido.tipos import Direction, Source, TxStatus
from app.movimientos.dominio.entidades import Transaction
from app.plataforma import esquema


@pytest.fixture()
def base(tmp_path, monkeypatch):
    """Un motor propio con las mismas PRAGMA que la app, puesto como el de la app."""
    engine = create_engine(f"sqlite:///{(tmp_path / 'esquema.db').as_posix()}")
    event.listen(engine, "connect", app_db._sqlite_pragmas)
    monkeypatch.setattr(app_db, "engine", engine)
    yield engine
    engine.dispose()


def _movimiento(engine, n: int, *, protegido: bool) -> int:
    with Session(engine) as s:
        t = Transaction(
            occurred_at=datetime(2026, 9, 1, 12), booking_date=date(2026, 9, 1),
            amount_cents=1000 + n, direction=Direction.gasto, source=Source.manual,
            status=TxStatus.confirmada, dedupe_hash=f"esquema-{n}",
            notes=f"nota {n}", locked_by_user=protegido,
        )
        s.add(t)
        s.commit()
        return t.id


def _cuenta(engine, sql: str) -> int:
    with engine.connect() as conn:
        return conn.exec_driver_sql(sql).scalar_one()


def _deriva(engine) -> list:
    app_db.registrar_tablas()
    with engine.connect() as conn:
        return compare_metadata(MigrationContext.configure(conn), SQLModel.metadata)


def test_hay_una_sola_ultima_version():
    """Dos versiones colgando de la misma madre son dos historias paralelas."""
    assert len(esquema.scripts().get_heads()) == 1


def test_base_nueva_queda_en_la_ultima_version(base):
    app_db.init_db()
    assert esquema.estado(base) == "versionada"
    assert esquema.version_actual(base) == esquema.scripts().get_current_head()
    assert esquema.pendientes(base) == []


def test_el_modelo_y_las_migraciones_dicen_lo_mismo(base):
    """Si falla: cambiaste una entidad sin escribir su version. Desde backend/:
    `alembic revision --autogenerate -m "que cambia"`, revisala y vuelve a probar."""
    app_db.init_db()
    assert _deriva(base) == []


def test_una_base_anterior_a_alembic_se_versiona_sin_perder_nada(base):
    # Una base como las de antes de Alembic: sin una columna que se anadio despues,
    # con una tabla ya retirada y con datos.
    app_db.registrar_tablas()
    SQLModel.metadata.create_all(base)
    protegido = _movimiento(base, 1, protegido=True)
    with base.begin() as conn:
        conn.exec_driver_sql('ALTER TABLE "transaction" DROP COLUMN user_edited_at')
        conn.exec_driver_sql("CREATE TABLE excel_staging (id INTEGER PRIMARY KEY)")

    assert esquema.estado(base) == "sin_versionar"
    pendientes = app_db.cambios_pendientes()
    assert "esquema: pasa a Alembic (version 0001)" in pendientes
    assert "columna transaction.user_edited_at" in pendientes

    app_db.init_db()

    assert esquema.version_actual(base) == esquema.scripts().get_current_head()
    tablas = set(inspect(base).get_table_names())
    assert "excel_staging" not in tablas
    assert _cuenta(base, 'SELECT COUNT(*) FROM "transaction"') == 1
    assert _deriva(base) == []
    # Las de DATOS siguen pendientes (las aplica migraciones.py, no init_db).
    assert [c for c in app_db.cambios_pendientes() if not c.startswith("migracion ")] == []
    with pytest.raises(IntegrityError, match="protegido"):
        with base.begin() as conn:
            conn.exec_driver_sql(f'DELETE FROM "transaction" WHERE id = {protegido}')


VERSION_DE_PRUEBA = '''
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("transaction") as batch:
        batch.alter_column("notes", new_column_name="notas")


def downgrade():
    with op.batch_alter_table("transaction") as batch:
        batch.alter_column("notas", new_column_name="notes")
'''


def test_renombrar_una_columna_conserva_datos_y_proteccion(base, tmp_path, monkeypatch):
    """El caso que Alembic viene a resolver: SQLite recrea la tabla para renombrar.

    Recrearla es borrar la vieja. Tiene que hacerse sin que salte el trigger de
    proteccion, sin llenar la papelera con todos los movimientos y sin perder datos.
    """
    app_db.init_db()
    protegido = _movimiento(base, 1, protegido=True)
    _movimiento(base, 2, protegido=False)

    carpeta = tmp_path / "migraciones_esquema"
    shutil.copytree(esquema.CARPETA, carpeta, ignore=shutil.ignore_patterns("__pycache__"))
    (carpeta / "versions" / "0002_renombrar_notas.py").write_text(VERSION_DE_PRUEBA, "utf-8")
    monkeypatch.setattr(esquema, "CARPETA", carpeta)

    assert esquema.pendientes(base) == ["0002"]
    assert esquema.actualizar(base) == ["0002"]
    with base.begin() as conn:
        app_db._proteger_movimientos(conn)       # lo que hace init_db despues

    columnas = {c["name"] for c in inspect(base).get_columns("transaction")}
    assert "notas" in columnas and "notes" not in columnas
    assert _cuenta(base, 'SELECT COUNT(*) FROM "transaction" WHERE notas LIKE \'nota %\'') == 2
    assert _cuenta(base, "SELECT COUNT(*) FROM transaction_papelera") == 0
    assert esquema.version_actual(base) == "0002"
    with pytest.raises(IntegrityError, match="protegido"):
        with base.begin() as conn:
            conn.exec_driver_sql(f'DELETE FROM "transaction" WHERE id = {protegido}')


def test_una_migracion_que_falla_no_deja_la_base_a_medias(base, tmp_path, monkeypatch):
    app_db.init_db()
    _movimiento(base, 1, protegido=True)

    rota = VERSION_DE_PRUEBA.replace(
        'batch.alter_column("notes", new_column_name="notas")',
        'batch.alter_column("notes", new_column_name="notas")\n'
        '    op.execute("SELECT columna_que_no_existe FROM kv")',
        1,
    )
    carpeta = tmp_path / "migraciones_esquema"
    shutil.copytree(esquema.CARPETA, carpeta, ignore=shutil.ignore_patterns("__pycache__"))
    (carpeta / "versions" / "0002_rota.py").write_text(rota, "utf-8")
    monkeypatch.setattr(esquema, "CARPETA", carpeta)

    with pytest.raises(Exception):
        esquema.actualizar(base)

    columnas = {c["name"] for c in inspect(base).get_columns("transaction")}
    assert "notes" in columnas and "notas" not in columnas
    assert esquema.version_actual(base) == "0001"
    assert _cuenta(base, 'SELECT COUNT(*) FROM "transaction"') == 1


def test_desde_la_terminal_no_se_aplican_migraciones():
    """Aplicarlas a mano se saltaria el respaldo previo y dejaria la base sin triggers."""
    from pathlib import Path

    from alembic.config import main

    ini = Path(__file__).resolve().parents[1] / "alembic.ini"
    with pytest.raises(SystemExit, match="arrancando la app"):
        main(argv=["-c", str(ini), "upgrade", "head"])
