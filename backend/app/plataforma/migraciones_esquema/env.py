"""Entorno de Alembic: las migraciones de ESQUEMA (tablas y columnas).

Las de DATOS (renombrar una categoria, mover movimientos) siguen en
`app/plataforma/migraciones.py`. Ver `app/plataforma/esquema.py` para el porque de
cada paso.

Desde la terminal solo se usa para ESCRIBIR migraciones:

    alembic revision --autogenerate -m "que cambia"

Aplicarlas (`upgrade`, `downgrade`, `stamp`) se hace arrancando la app, que antes
copia la base y despues rehace los triggers de proteccion. Por eso aqui se bloquean.
"""
from __future__ import annotations

from alembic import context
from sqlmodel import SQLModel

from app.plataforma import db

db.registrar_tablas()
target_metadata = SQLModel.metadata

_SOLO_DESDE_LA_APP = {"upgrade", "downgrade", "stamp"}


def _bloquear_desde_la_terminal() -> None:
    opciones = context.config.cmd_opts
    if opciones is None or not getattr(opciones, "cmd", None):
        return                                  # llamada desde la app (esquema.py)
    if opciones.cmd[0].__name__ in _SOLO_DESDE_LA_APP:
        raise SystemExit(
            "Las migraciones se aplican arrancando la app: asi se hace antes la copia "
            "de la base y despues se rehacen los triggers de proteccion. "
            "Ejecuta `docker compose up -d --build`."
        )


def _configurar(conexion) -> None:
    context.configure(
        connection=conexion,
        target_metadata=target_metadata,
        # SQLite no sabe renombrar ni quitar columnas con ALTER: batch recrea la
        # tabla copiando los datos.
        render_as_batch=True,
        compare_type=True,
    )


def run_migrations_online() -> None:
    _bloquear_desde_la_terminal()
    conexion = context.config.attributes.get("connection")
    if conexion is not None:
        # La app ya abrio la transaccion y la confirma ella (esquema.actualizar).
        _configurar(conexion)
        context.run_migrations()
        return
    with db.engine.connect() as conexion:      # `alembic revision --autogenerate`
        _configurar(conexion)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise SystemExit("El modo --sql no se usa en este proyecto.")
run_migrations_online()
