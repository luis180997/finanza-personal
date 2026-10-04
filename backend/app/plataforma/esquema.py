"""Migraciones de ESQUEMA con Alembic: cambiar tablas y columnas sin perder datos.

Antes, `create_all` creaba las tablas que faltaban y `COLUMNAS_NUEVAS` (db.py)
anadia columnas sueltas. Renombrar, quitar o partir una columna no tenia
herramienta. Ahora cada cambio es un script numerado en
`migraciones_esquema/versions/`, la base guarda en `alembic_version` en cual esta, y
al arrancar se aplican los que falten, en orden.

Una base puede llegar en tres estados:

    nueva          sin tablas      -> se aplican todas las versiones desde la 0001
    sin_versionar  anterior a      -> se completa hasta la 0001 con lo de siempre
                   Alembic            (create_all, COLUMNAS_NUEVAS, tablas
                                      obsoletas), se marca como 0001 y se sigue
    versionada     con alembic_    -> solo las versiones pendientes
                   version

Las migraciones de DATOS (renombrar una categoria, descartar los correos de agosto)
siguen en `migraciones.py`: corren despues, sobre el esquema ya al dia.
"""
from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlalchemy.engine import Connection, Engine

log = logging.getLogger("finanzas.esquema")

CARPETA = Path(__file__).with_name("migraciones_esquema")
VERSION_BASE = "0001"

# Las tablas que tenia la base cuando se adopto Alembic (version 0001). Una base
# sin versionar solo se completa con estas: si se creara con el modelo de HOY, una
# copia vieja restaurada recibiria tablas que una migracion posterior intentaria
# crear otra vez.
TABLAS_BASE = (
    "account", "budget", "category", "email_message", "import_batch", "kv", "rule",
    "saldo_corte", "saldo_cuenta", "transaction", "transaction_papelera",
)

# Los triggers de proteccion viven sobre "transaction". Una migracion "batch" recrea
# la tabla (crea una nueva, copia, borra la vieja), y al borrarla SQLite se lleva sus
# triggers. Se quitan antes a proposito y db.py los rehace despues con las columnas
# nuevas.
TRIGGERS = ("tx_protegido_no_se_borra", "tx_a_papelera")


def configuracion(conexion: Connection | None = None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(CARPETA))
    cfg.attributes["connection"] = conexion
    return cfg


def scripts() -> ScriptDirectory:
    return ScriptDirectory.from_config(configuracion())


def estado(engine: Engine) -> str:
    tablas = set(inspect(engine).get_table_names())
    if "alembic_version" in tablas:
        return "versionada"
    if tablas & set(TABLAS_BASE):
        return "sin_versionar"
    return "nueva"


def version_actual(engine: Engine) -> str | None:
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def pendientes(engine: Engine) -> list[str]:
    """Versiones por aplicar, de la mas vieja a la mas nueva."""
    actual = version_actual(engine) if estado(engine) == "versionada" else VERSION_BASE
    por_aplicar = [
        s.revision for s in scripts().iterate_revisions("heads", actual)
        if s.revision != actual
    ]
    return list(reversed(por_aplicar))


def marcar_como_base(engine: Engine) -> None:
    """Anota en una base anterior a Alembic que esta en la 0001, sin tocar nada mas."""
    with engine.begin() as conn:
        command.stamp(configuracion(conn), VERSION_BASE)


def actualizar(engine: Engine) -> list[str]:
    """Aplica las versiones pendientes. Todas o ninguna."""
    por_aplicar = pendientes(engine) if estado(engine) != "nueva" else ["todas"]
    if not por_aplicar:
        return []

    with engine.connect() as conn:
        es_sqlite = conn.dialect.name == "sqlite"
        crudo = conn.connection.dbapi_connection
        nivel_previo = crudo.isolation_level if es_sqlite else None
        try:
            if es_sqlite:
                # Batch recrea tablas: con las claves foraneas activas, borrar la
                # tabla vieja haria saltar las referencias. Se comprueban al final.
                conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
                # El driver de SQLite de Python no abre transaccion antes de un
                # CREATE o un ALTER: cada paso se confirmaba solo y un fallo a mitad
                # dejaba la base a medio cambiar. Con BEGIN explicito, todo o nada.
                crudo.isolation_level = None
                conn.exec_driver_sql("BEGIN")
                for trigger in TRIGGERS:
                    conn.exec_driver_sql(f"DROP TRIGGER IF EXISTS {trigger}")
            command.upgrade(configuracion(conn), "heads")
            if es_sqlite:
                rotas = conn.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
                if rotas:
                    raise RuntimeError(f"La migracion dejo referencias rotas: {rotas[:5]}")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            if es_sqlite:
                crudo.isolation_level = nivel_previo
                conn.exec_driver_sql("PRAGMA foreign_keys=ON")

    log.info("esquema actualizado a %s (%s)", version_actual(engine), ", ".join(por_aplicar))
    return por_aplicar
