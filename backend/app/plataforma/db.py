"""Motor de base de datos y sesiones."""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from app.plataforma.config import settings

connect_args = (
    {"check_same_thread": False, "timeout": 30.0}
    if settings.database_url.startswith("sqlite")
    else {}
)
engine = create_engine(settings.database_url, echo=False, connect_args=connect_args)


def registrar_tablas() -> None:
    """Importa las entidades de todos los modulos para que SQLModel conozca sus tablas.

    Cada modulo declara las suyas en `<modulo>/dominio/entidades.py`. Las claves
    foraneas entre modulos van por nombre de tabla, asi que basta con que esten
    todas importadas antes de `create_all`.
    """
    import app.analitica.dominio.entidades  # noqa: F401
    import app.clasificacion.dominio.entidades  # noqa: F401
    import app.correo.dominio.entidades  # noqa: F401
    import app.excel.dominio.entidades  # noqa: F401
    import app.movimientos.dominio.entidades  # noqa: F401
    import app.plataforma.kv  # noqa: F401
    import app.seguimiento.dominio.entidades  # noqa: F401


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _):
    """DELETE + foreign keys: seguro para carpetas locales / bind mounts en Windows."""
    if settings.database_url.startswith("sqlite"):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=DELETE")
        cur.execute("PRAGMA foreign_keys=ON")
        # Sin esto, un INSERT OR REPLACE que pisa una fila la borra por dentro SIN
        # disparar los triggers de proteccion ni de papelera: un registro protegido
        # se sobrescribia sin dejar copia (comprobado el 13/09/2026).
        cur.execute("PRAGMA recursive_triggers=ON")
        cur.close()


# Tablas que existieron y ya no se usan. Se borran al arrancar para no dejar datos
# huerfanos que nadie lee ni actualiza.
#   excel_staging: la seccion "Comparativa Excel", retirada en set. 2026. Era una
#                  copia del Excel recalculable desde el propio archivo.
TABLAS_OBSOLETAS = ("excel_staging",)

# Columnas anadidas despues de crear la tabla. `create_all` crea las tablas que
# faltan, pero NO anade columnas a una tabla que ya existe: sin esto, una base
# creada antes del cambio reventaria al leer el modelo nuevo.
COLUMNAS_NUEVAS: dict[str, list[tuple[str, str]]] = {
    "transaction": [
        ("locked_by_user", "BOOLEAN NOT NULL DEFAULT 0"),
        ("user_edited_at", "DATETIME"),
    ],
}


def _columnas(conn, tabla: str) -> list[str]:
    return [fila[1] for fila in conn.exec_driver_sql(f'PRAGMA table_info("{tabla}")')]


def _proteger_movimientos(conn) -> None:
    """Dos triggers que protegen tus datos aunque falle el codigo que los rodea.

    Viven en la base y no en Python a proposito. El 13/09/2026 se perdieron
    registros manuales por procesos que borraban sin pasar por la app: un script de
    limpieza por rango de ids, otro que borraba todo lo anterior a agosto y una
    ejecucion de los tests contra la base real. Ninguna regla escrita en el codigo
    de la app los habria parado; un trigger si.

    1. tx_protegido_no_se_borra: un movimiento que registraste o corregiste
       (locked_by_user = 1) no se puede borrar. Quien lo intente recibe un error y
       su operacion entera se deshace: un DELETE masivo no borra "lo demas", no
       borra nada. Para borrarlo a proposito hay que quitarle antes la proteccion,
       que es lo que hace la app cuando borras un registro manual tuyo.

    2. tx_a_papelera: todo movimiento borrado, protegido o no, se copia antes a
       transaction_papelera. Se regenera en cada arranque con las columnas reales
       de la tabla, asi una columna nueva nunca se queda fuera de la copia.
    """
    pares = ", ".join(f"'{c}', OLD.\"{c}\"" for c in _columnas(conn, "transaction"))

    conn.exec_driver_sql("DROP TRIGGER IF EXISTS tx_protegido_no_se_borra")
    conn.exec_driver_sql(
        """
        CREATE TRIGGER tx_protegido_no_se_borra
        BEFORE DELETE ON "transaction"
        WHEN OLD.locked_by_user = 1
        BEGIN
            SELECT RAISE(ABORT, 'Movimiento protegido: lo registraste o corregiste tu. Para borrarlo a proposito, quitale antes la proteccion (locked_by_user = 0).');
        END
        """
    )
    conn.exec_driver_sql("DROP TRIGGER IF EXISTS tx_a_papelera")
    conn.exec_driver_sql(
        f"""
        CREATE TRIGGER tx_a_papelera
        AFTER DELETE ON "transaction"
        BEGIN
            INSERT INTO transaction_papelera
                (tx_id, email_id, dedupe_hash, source, editado_por_usuario, datos, borrado_en)
            VALUES
                (OLD.id, OLD.email_id, OLD.dedupe_hash, OLD.source,
                 OLD.user_edited_at IS NOT NULL, json_object({pares}), CURRENT_TIMESTAMP);
        END
        """
    )


def init_db() -> None:
    registrar_tablas()

    SQLModel.metadata.create_all(engine)
    with engine.begin() as conn:
        for tabla, columnas in COLUMNAS_NUEVAS.items():
            existentes = set(_columnas(conn, tabla))
            for nombre, definicion in columnas:
                if nombre not in existentes:
                    conn.exec_driver_sql(f'ALTER TABLE "{tabla}" ADD COLUMN "{nombre}" {definicion}')
        for tabla in TABLAS_OBSOLETAS:
            conn.exec_driver_sql(f'DROP TABLE IF EXISTS "{tabla}"')
        if conn.dialect.name == "sqlite":
            _proteger_movimientos(conn)


def cambios_pendientes() -> list[str]:
    """Lo que el arranque va a cambiar en una base que ya tiene movimientos.

    Lo usa main.py para copiar la base ANTES de tocarla. Vacio si no hay nada
    pendiente o si la base todavia no tiene movimientos que proteger. Crear tablas
    nuevas no cuenta: no toca nada de lo que ya existe.
    """
    from sqlalchemy import inspect

    from app.plataforma.migraciones import MIGRACIONES

    inspector = inspect(engine)
    tablas = set(inspector.get_table_names())
    if "transaction" not in tablas:
        return []

    cambios = []
    for tabla, columnas in COLUMNAS_NUEVAS.items():
        if tabla in tablas:
            existentes = {c["name"] for c in inspector.get_columns(tabla)}
            cambios += [f"columna {tabla}.{n}" for n, _ in columnas if n not in existentes]
    cambios += [f"tabla retirada {t}" for t in TABLAS_OBSOLETAS if t in tablas]

    hechas: set[str] = set()
    if "kv" in tablas:
        with engine.connect() as conn:
            hechas = {
                fila[0] for fila in
                conn.exec_driver_sql("SELECT key FROM kv WHERE key LIKE 'migracion:%'")
            }
    cambios += [f"migracion {c}" for c, _ in MIGRACIONES if f"migracion:{c}" not in hechas]
    return cambios


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session


class UnidadDeTrabajoSqlite:
    """El puerto `UnidadDeTrabajo` sobre una sesion de SQLAlchemy, que ya es una
    unidad de trabajo: aqui solo se le da el nombre que usan los casos de uso."""

    def __init__(self, session: Session):
        self.session = session

    def confirmar(self) -> None:
        self.session.commit()

    def deshacer(self) -> None:
        self.session.rollback()

    def volcar(self) -> None:
        self.session.flush()

    def refrescar(self, entidad) -> None:
        self.session.refresh(entidad)
