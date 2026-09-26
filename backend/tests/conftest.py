"""Configuración global de tests.

Garantiza aislamiento estricto: cualquier ejecución de pytest corre
OBLIGATORIAMENTE en una base de datos temporal, impidiendo por completo
que se toque o contamine 'data/finanzas.db'.
"""
import os
import tempfile
from pathlib import Path

from sqlalchemy import event
from sqlmodel import create_engine

_TMP_DIR = tempfile.mkdtemp()
_TEST_DB = Path(_TMP_DIR) / "test_suite.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB.as_posix()}"
os.environ["SYNC_INTERVAL_MINUTES"] = "0"
os.environ["APP_ENV"] = "test"
# Sin respaldos automaticos: escribirian copias de la base temporal en la carpeta
# de respaldos reales, y la poda borraria los buenos.
os.environ["RESPALDO_CADA_DIAS"] = "0"
os.environ["RESPALDO_DIR"] = str(Path(_TMP_DIR) / "respaldos")
# La seccion esta apagada por defecto; los tests del importador la necesitan.
os.environ["IMPORTAR_EXCEL_HABILITADO"] = "true"

from app.plataforma.config import get_settings
get_settings.cache_clear()

import app.plataforma.config as app_config
import app.plataforma.db as app_db
app_db.engine = create_engine(
    f"sqlite:///{_TEST_DB.as_posix()}",
    echo=False,
    connect_args={"check_same_thread": False, "timeout": 30.0},
)
# Las mismas PRAGMA que en produccion. Sin ellas las claves foraneas estaban
# apagadas y los tests no veian los errores 500 que si salian en la app.
event.listen(app_db.engine, "connect", app_db._sqlite_pragmas)

# Red de seguridad. El 13/09/2026 a las 00:05 una ejecucion de los tests escribio
# en data/finanzas.db: borro todos los movimientos y dejo un tope de Delivery de
# S/150. Si la configuracion ya estaba cargada apuntando a la base real (por
# ejemplo, porque otro modulo importo la app antes que este archivo), se para aqui
# antes de tocar nada.
for _url in (app_config.settings.database_url, str(app_db.engine.url)):
    assert _url.endswith("test_suite.db"), (
        f"Los tests iban a usar {_url} en vez de la base temporal. Abortado."
    )
# Y lo mismo con las copias: un test que respalda tambien poda, y podar en la
# carpeta real borraria respaldos buenos.
assert app_config.settings.carpeta_respaldos.resolve().is_relative_to(Path(_TMP_DIR).resolve()), (
    f"Los tests iban a usar {app_config.settings.carpeta_respaldos} para los respaldos. Abortado."
)

app_db.init_db()
