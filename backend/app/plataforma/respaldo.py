"""Copias de seguridad automaticas de la base SQLite.

Cinco decisiones, y por que:

1. **Se mira la FECHA del ultimo respaldo, no una hora fija.** La app no corre
   todo el tiempo: un "todos los domingos a las 3:00" se lo saltaria cada vez que
   el equipo estuviera apagado a esa hora. Al arrancar y luego cada hora se
   pregunta "¿han pasado N dias desde la ultima copia?". Si el equipo estuvo
   apagado dos semanas, la copia sale en cuanto vuelve a encenderse.

2. **La fecha sale del nombre del archivo, no de la base.** Si restauras una copia
   vieja, la base no puede "recordar" un respaldo posterior que en disco no esta.
   Y la carpeta es la unica fuente de verdad de que copias existen.

3. **API de backup en linea de SQLite, escrita a un .tmp y verificada.** Copiar
   finanzas.db con el sincronizador escribiendo puede dejar una copia a medias.
   `sqlite3.Connection.backup` copia con el bloqueo adecuado; despues se pasa
   `PRAGMA integrity_check` y solo entonces se renombra (os.replace es atomico).
   Un corte de luz a mitad nunca deja un archivo con nombre de respaldo valido
   que en realidad esta roto.

4. **Se conserva por antiguedad, no por cantidad.** Guardar "las 8 ultimas"
   dejaba que ocho copias seguidas (varios respaldos manuales, varios arranques
   con migraciones) se llevaran todo el historial en una tarde. Ahora se guardan
   las mas recientes Y la ultima de cada uno de los ultimos 7 dias, 8 semanas y
   12 meses con copia: un dia de muchas copias solo reemplaza copias de ese dia.

5. **Una copia con claramente mas movimientos que la ultima no se poda.**
   `integrity_check` dice si el archivo esta roto, no si le faltan datos: una base
   vaciada por error se copia "sana" (comprobado). Esa copia anterior puede ser la
   unica con lo que se perdio, asi que se queda hasta que la borres tu. `estado()`
   ademas lo avisa, y compara la base en uso con la ultima copia para dar la
   alarma antes de que llegue la siguiente.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock

log = logging.getLogger("finanzas.respaldo")

_FORMATO = "%Y%m%dT%H%M%SZ"
# Solo cuenta (y solo se poda) lo que tiene EXACTAMENTE el nombre que genera este
# modulo. Un archivo que dejes a mano en la carpeta no se toma por respaldo ni se
# borra nunca.
_PATRON = re.compile(r"^finanzas_(\d{8}T\d{6}Z)\.db$")
_candado = Lock()

# Ademas de las `conservar` mas recientes, la ultima copia de cada uno de los
# ultimos N dias, semanas y meses que tengan alguna.
TRAMOS_DIAS = 7
TRAMOS_SEMANAS = 8
TRAMOS_MESES = 12

# Cuantos movimientos de menos cuentan como "se perdieron datos": al menos 10 y
# al menos el 1 %. Borrar a proposito un par de registros tuyos no dispara nada.
PERDIDA_MINIMA = 10
PERDIDA_RELATIVA = 0.01
# Donde se anota "lo borre a proposito". Vive junto a las copias y no en la base: si
# restauras una copia vieja, lo que diste por bueno no debe viajar con ella.
ARCHIVO_PERDIDA_ACEPTADA = "perdida_aceptada.json"

# Resultado del ultimo intento de copia de este proceso. Un fallo se enseña en la
# interfaz en vez de quedarse solo en el log, donde nadie lo ve.
_ultimo_intento: dict | None = None
# Movimientos de cada copia, por (ruta, tamano, fecha de modificacion): una copia
# no cambia, y el estado se pide cada vez que se abre la pantalla.
_movimientos_por_copia: dict[tuple[str, int, int], int | None] = {}


@dataclass
class Respaldo:
    ruta: Path
    fecha: datetime
    bytes: int

    @property
    def movimientos(self) -> int | None:
        return contar_movimientos(self.ruta)

    def a_dict(self) -> dict:
        return {
            "archivo": self.ruta.name,
            "fecha": self.fecha.isoformat(),
            "bytes": self.bytes,
            "movimientos": self.movimientos,
        }


def ruta_sqlite(database_url: str) -> Path | None:
    """`sqlite:///C:/x/finanzas.db` -> Path. None si no es SQLite en un archivo."""
    if not database_url.startswith("sqlite:///"):
        return None
    ruta = database_url.removeprefix("sqlite:///")
    if not ruta or ruta.startswith(":memory:"):
        return None
    return Path(ruta)


def _contar(ruta: Path) -> int | None:
    try:
        con = sqlite3.connect(f"{ruta.resolve().as_uri()}?mode=ro", uri=True)
    except (sqlite3.Error, ValueError):
        return None
    try:
        return con.execute('SELECT COUNT(*) FROM "transaction"').fetchone()[0]
    except sqlite3.Error:
        return None
    finally:
        con.close()


def contar_movimientos(ruta: Path, memorizar: bool = True) -> int | None:
    """Filas de la tabla de movimientos, abriendo el archivo en solo lectura.

    None si no se puede leer o no es una base de esta app. La base en uso se
    cuenta sin memorizar: cambia con cada escritura.
    """
    if not memorizar:
        return _contar(ruta)
    try:
        info = ruta.stat()
    except OSError:
        return None
    clave = (str(ruta), info.st_size, info.st_mtime_ns)
    if clave not in _movimientos_por_copia:
        _movimientos_por_copia[clave] = _contar(ruta)
    return _movimientos_por_copia[clave]


def hubo_perdida(antes: int | None, despues: int | None) -> bool:
    """True si de `antes` a `despues` desaparecieron claramente movimientos."""
    if antes is None or despues is None:
        return False
    return antes - despues >= max(PERDIDA_MINIMA, antes * PERDIDA_RELATIVA)


def listar(carpeta: Path) -> list[Respaldo]:
    """Respaldos de la carpeta, del mas nuevo al mas viejo."""
    if not carpeta.is_dir():
        return []
    salida = []
    for p in carpeta.iterdir():
        m = _PATRON.match(p.name)
        if m and p.is_file():
            fecha = datetime.strptime(m.group(1), _FORMATO).replace(tzinfo=timezone.utc)
            salida.append(Respaldo(p, fecha, p.stat().st_size))
    return sorted(salida, key=lambda r: r.fecha, reverse=True)


def toca_respaldo(carpeta: Path, cada_dias: int, ahora: datetime | None = None) -> bool:
    if cada_dias <= 0:
        return False
    existentes = listar(carpeta)
    if not existentes:
        return True
    ahora = ahora or datetime.now(timezone.utc)
    transcurrido = ahora - existentes[0].fecha
    # Un respaldo "del futuro" (el reloj del equipo se atraso) no puede bloquear
    # las copias durante dias: se trata como vencido.
    return transcurrido >= timedelta(days=cada_dias) or transcurrido < -timedelta(days=1)


def crear(origen: Path, carpeta: Path, ahora: datetime | None = None) -> Respaldo:
    """Copia consistente de `origen` en `carpeta`. Lanza si algo sale mal."""
    if not origen.is_file():
        raise FileNotFoundError(f"No existe la base de datos {origen}")
    ahora = (ahora or datetime.now(timezone.utc)).replace(microsecond=0)
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / f"finanzas_{ahora.strftime(_FORMATO)}.db"
    tmp = destino.with_name(destino.name + ".tmp")
    tmp.unlink(missing_ok=True)     # restos de un intento anterior interrumpido

    fuente = sqlite3.connect(origen, timeout=30)
    try:
        copia = sqlite3.connect(tmp)
        try:
            fuente.backup(copia)
            estado = copia.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            copia.close()
    finally:
        fuente.close()

    if estado != "ok":
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"La copia no paso la verificacion de integridad: {estado}")
    tmp.replace(destino)
    return Respaldo(destino, ahora, destino.stat().st_size)


def _a_conservar(existentes: list[Respaldo], conservar: int) -> set[Path]:
    """Las copias que manda guardar la politica de antiguedad, sin mirar su contenido.

    `existentes` va del mas nuevo al mas viejo, asi que la primera copia que
    aparece de cada dia, semana o mes es la ultima de ese tramo.
    """
    quedan = {r.ruta for r in existentes[:conservar]}
    tramos = (
        (TRAMOS_DIAS, lambda f: f.date()),
        (TRAMOS_SEMANAS, lambda f: tuple(f.isocalendar())[:2]),
        (TRAMOS_MESES, lambda f: (f.year, f.month)),
    )
    for cuantos, tramo in tramos:
        vistos: set = set()
        for r in existentes:
            clave = tramo(r.fecha)
            if clave in vistos:
                continue
            if len(vistos) == cuantos:
                break
            vistos.add(clave)
            quedan.add(r.ruta)
    return quedan


def podar(carpeta: Path, conservar: int) -> list[Path]:
    """Borra las copias que ya no hacen falta. `conservar` = 0 no borra nada.

    Se guardan siempre las `conservar` mas recientes y la ultima de cada uno de
    los ultimos 7 dias, 8 semanas y 12 meses con copia. Y ninguna con claramente
    mas movimientos que la ultima, pase el tiempo que pase.
    """
    if conservar <= 0:
        return []
    existentes = listar(carpeta)
    if not existentes:
        return []
    ultima = existentes[0].movimientos
    if ultima is None:
        # Sin saber cuantos movimientos tiene la ultima no hay con que comparar:
        # mejor no borrar nada que borrar justo la copia buena.
        log.warning("no se pudo leer %s: no se poda ninguna copia", existentes[0].ruta.name)
        return []

    quedan = _a_conservar(existentes, conservar)
    borrados = []
    for r in existentes:
        if r.ruta in quedan:
            continue
        if hubo_perdida(r.movimientos, ultima):
            log.warning(
                "se conserva %s: tiene %s movimientos y la ultima copia %s",
                r.ruta.name, r.movimientos, ultima,
            )
            continue
        r.ruta.unlink(missing_ok=True)
        borrados.append(r.ruta)
    return borrados


def respaldar(
    database_url: str,
    carpeta: Path,
    conservar: int,
    *,
    forzar: bool = False,
    cada_dias: int = 0,
    ahora: datetime | None = None,
    esperar: bool = False,
) -> Respaldo | None:
    """Crea un respaldo si toca (o siempre, con `forzar`) y poda los viejos.

    Devuelve None si no tocaba o si ya habia otro respaldo en curso. Con `esperar`
    no se rinde: espera hasta dos minutos a que termine el otro. Lo usan las copias
    previas a algo que no debe hacerse sin copia.
    """
    global _ultimo_intento

    origen = ruta_sqlite(database_url)
    if origen is None:
        raise ValueError("Los respaldos solo funcionan con una base SQLite en archivo.")
    # Un respaldo manual y el programado a la vez escribirian el mismo .tmp.
    obtenido = _candado.acquire(timeout=120) if esperar else _candado.acquire(blocking=False)
    if not obtenido:
        return None
    try:
        if not forzar and not toca_respaldo(carpeta, cada_dias, ahora):
            return None
        momento = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        try:
            nuevo = crear(origen, carpeta, ahora)
        except Exception as exc:
            _ultimo_intento = {"fecha": momento, "ok": False, "error": str(exc)}
            raise
        _ultimo_intento = {"fecha": momento, "ok": True, "error": None}
        try:
            for viejo in podar(carpeta, conservar):
                log.info("respaldo antiguo eliminado: %s", viejo.name)
        except OSError:
            # La copia nueva ya esta hecha: que no se pueda borrar una vieja no la
            # convierte en un fallo.
            log.exception("no se pudieron podar las copias antiguas")
        return nuevo
    finally:
        _candado.release()


def aceptar_perdida(database_url: str, carpeta: Path, ahora: datetime | None = None) -> int:
    """Da por buenos los movimientos que tiene ahora la base: lo que falta lo borraste
    tu a proposito (deshacer una importacion, limpiar datos de prueba).

    Sin esto, el aviso de movimientos desaparecidos seguia en pantalla hasta la
    siguiente copia, hasta 7 dias, y un aviso que no se puede apagar se aprende a
    ignorar. No borra ninguna copia: las que tienen esos movimientos se conservan.
    Devuelve cuantos movimientos se dieron por buenos.
    """
    origen = ruta_sqlite(database_url)
    movimientos = (
        contar_movimientos(origen, memorizar=False)
        if origen is not None and origen.is_file() else None
    )
    if movimientos is None:
        raise ValueError("No se pudo leer la base para saber cuantos movimientos tiene.")
    momento = (ahora or datetime.now(timezone.utc)).replace(microsecond=0)
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / ARCHIVO_PERDIDA_ACEPTADA).write_text(
        json.dumps({"fecha": momento.isoformat(), "movimientos": movimientos}), encoding="utf-8",
    )
    return movimientos


def _perdida_aceptada(carpeta: Path) -> tuple[datetime, int] | None:
    try:
        datos = json.loads((carpeta / ARCHIVO_PERDIDA_ACEPTADA).read_text(encoding="utf-8"))
        return datetime.fromisoformat(datos["fecha"]), int(datos["movimientos"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


_SI_FUE_A_PROPOSITO = (
    " Si lo borraste tu a proposito, pulsa \"Lo borre a proposito\"; si no, mira la "
    "Papelera de Movimientos y, si hace falta, restaura la copia."
)


def _alertas(
    existentes: list[Respaldo], activo: bool, cada_dias: int, en_uso: int | None,
    ahora: datetime, aceptada: tuple[datetime, int] | None,
) -> tuple[list[str], bool]:
    """Lo que va mal, y si alguna alerta es de movimientos desaparecidos."""
    alertas: list[str] = []
    perdida = False
    if _ultimo_intento and not _ultimo_intento["ok"]:
        alertas.append(f"El ultimo intento de copia fallo: {_ultimo_intento['error']}")
    if not existentes:
        if activo:
            alertas.append("Todavia no hay ninguna copia de seguridad.")
        return alertas, perdida

    ultimo = existentes[0]
    dias = (ahora - ultimo.fecha).days
    if activo and dias > cada_dias + 1:
        alertas.append(f"La ultima copia es de hace {dias} dias; tocaba cada {cada_dias}.")

    # La base en uso se compara con la ultima copia, o con lo que diste por bueno si
    # fue despues de ella.
    aceptada_despues = aceptada is not None and aceptada[0] >= ultimo.fecha
    if aceptada_despues:
        referencia = aceptada[1]
        cuando = f"cuando diste por bueno el ultimo borrado ({aceptada[0]:%d/%m/%Y})"
    else:
        referencia = ultimo.movimientos
        cuando = f"la ultima copia ({ultimo.fecha:%d/%m/%Y})"
    if hubo_perdida(referencia, en_uso):
        perdida = True
        alertas.append(
            f"La base tiene {en_uso} movimientos y {cuando} tenia {referencia}."
            + _SI_FUE_A_PROPOSITO
        )

    # La ultima copia contra la anterior, descontando lo que diste por bueno entre medias.
    if len(existentes) > 1 and not aceptada_despues:
        anterior = existentes[1]
        base = (
            aceptada[1] if aceptada is not None and aceptada[0] >= anterior.fecha
            else anterior.movimientos
        )
        if hubo_perdida(base, ultimo.movimientos):
            perdida = True
            alertas.append(
                f"La ultima copia ({ultimo.fecha:%d/%m/%Y}) tiene {ultimo.movimientos} "
                f"movimientos y antes habia {base}. La copia anterior no se borra sola."
                + _SI_FUE_A_PROPOSITO
            )
    return alertas, perdida


def estado(
    database_url: str, carpeta: Path, cada_dias: int, conservar: int,
    ahora: datetime | None = None,
) -> dict:
    ahora = ahora or datetime.now(timezone.utc)
    existentes = listar(carpeta)
    ultimo = existentes[0] if existentes else None
    origen = ruta_sqlite(database_url)
    activo = cada_dias > 0 and origen is not None
    proximo = None
    if cada_dias > 0:
        proximo = (
            (ultimo.fecha + timedelta(days=cada_dias)).isoformat()
            if ultimo else ahora.replace(microsecond=0).isoformat()
        )
    en_uso = (
        contar_movimientos(origen, memorizar=False)
        if origen is not None and origen.is_file() else None
    )
    alertas, perdida = _alertas(
        existentes, activo, cada_dias, en_uso, ahora, _perdida_aceptada(carpeta),
    )
    return {
        "activo": activo,
        "cada_dias": cada_dias,
        "conservar": conservar,
        "carpeta": str(carpeta),
        "ultimo": ultimo.a_dict() if ultimo else None,
        "proximo": proximo,
        "movimientos_en_uso": en_uso,
        "ultimo_intento": _ultimo_intento,
        "alertas": alertas,
        # Alguna alerta es de movimientos desaparecidos: se puede dar por buena.
        "perdida_sin_aceptar": perdida,
        "respaldos": [r.a_dict() for r in existentes],
    }


def copia_previa(motivo: str) -> Respaldo | None:
    """Copia inmediata antes de una operacion que cambia muchos datos de golpe.

    Lanza si no se puede hacer: quien la pide no debe seguir sin copia. Devuelve
    None si la base no es SQLite en archivo, porque entonces no hay nada que copiar.
    """
    from app.plataforma.config import settings

    if ruta_sqlite(settings.database_url) is None:
        return None
    nuevo = respaldar(
        settings.database_url, settings.carpeta_respaldos, settings.respaldo_conservar,
        forzar=True, esperar=True,
    )
    if nuevo is None:
        raise RuntimeError("habia otro respaldo en curso y no termino a tiempo")
    log.info("copia previa a %s: %s", motivo, nuevo.ruta.name)
    return nuevo


def tarea_programada() -> None:
    """Lo que ejecuta el planificador. Nunca lanza: un respaldo fallido queda en el
    log y en `estado()`, pero no puede tumbar la app ni el sincronizador de correo."""
    from app.plataforma.config import settings

    try:
        nuevo = respaldar(
            settings.database_url,
            settings.carpeta_respaldos,
            settings.respaldo_conservar,
            cada_dias=settings.respaldo_cada_dias,
        )
        if nuevo:
            log.info("respaldo creado: %s (%.1f MB)", nuevo.ruta.name, nuevo.bytes / 1e6)
    except Exception:  # noqa: BLE001
        log.exception("no se pudo crear el respaldo")
