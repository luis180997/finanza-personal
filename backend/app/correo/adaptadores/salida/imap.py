"""Lectura de correo por IMAP con contrasena de aplicacion.

POR QUE IMAP Y NO LA API DE GMAIL

La API de Gmail parece la opcion "correcta" —permiso de solo lectura, sin
contrasenas— pero para una app personal tiene un problema practico que la
descalifica: `gmail.readonly` es un *restricted scope*, y mientras la app este
en estado "Testing" en Google Cloud Console, **el refresh token caduca a los 7
dias**. Es decir, habria que volver a autorizar cada semana. Sacarla de
"Testing" exige pasar la verificacion de Google, que para un proyecto de una
sola persona no tiene sentido.

Una contrasena de aplicacion no caduca. Configurarla son dos minutos y no
requiere Google Cloud Console.

EL PRECIO, dicho claramente: una contrasena de aplicacion da acceso IMAP
completo al buzon (leer y borrar), no solo lectura. Mitigaciones:
  - vive en el .env, en tu maquina, fuera de git;
  - esta app solo hace SELECT y FETCH, nunca STORE ni EXPUNGE;
  - se revoca en un clic desde tu cuenta de Google.

CONFIGURACION (2 minutos):
  1. https://myaccount.google.com/security -> activa la verificacion en 2 pasos
     (sin ella Google no deja crear contrasenas de aplicacion)
  2. https://myaccount.google.com/apppasswords -> crea una y copia las 16 letras
  3. En el .env del proyecto:
         EMAIL_BACKEND=imap
         IMAP_USER=tucorreo@gmail.com
         IMAP_PASSWORD=las16letrassinespacios
  4. docker compose up -d
"""
from __future__ import annotations

import email
import imaplib
import logging
import ssl
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

from app.plataforma.config import settings
from app.correo.adaptadores.salida.html import decode_header_value, extract_body_mime
from app.correo.dominio.correo import RawEmail

log = logging.getLogger(__name__)
TZ = ZoneInfo(settings.timezone)


class ImapNoConfigurado(RuntimeError):
    pass


def esta_configurado() -> bool:
    return bool(settings.imap_user and settings.imap_password)


def _conectar() -> imaplib.IMAP4_SSL:
    if not esta_configurado():
        raise ImapNoConfigurado(
            "Faltan IMAP_USER e IMAP_PASSWORD en el .env. Crea una contrasena de "
            "aplicacion en https://myaccount.google.com/apppasswords"
        )

    if settings.imap_verificar_certificado:
        contexto = ssl.create_default_context()
    else:
        # Escotilla para antivirus o proxies corporativos que interceptan TLS.
        # Apagar la verificacion abre la puerta a un intermediario: usalo solo
        # si la conexion falla por certificado y sabes por que.
        log.warning("IMAP con verificacion de certificado DESACTIVADA")
        contexto = ssl.create_default_context()
        contexto.check_hostname = False
        contexto.verify_mode = ssl.CERT_NONE

    imap = imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port, ssl_context=contexto)
    # La contrasena de aplicacion se muestra en grupos de 4; Google la acepta
    # igual, pero quitar los espacios evita el fallo mas tonto posible.
    imap.login(settings.imap_user, settings.imap_password.replace(" ", ""))
    return imap


def probar_conexion() -> dict:
    """Comprueba credenciales sin descargar nada. Lo usa el boton de la interfaz."""
    imap = None
    try:
        imap = _conectar()
        estado, datos = imap.select("INBOX", readonly=True)
        if estado != "OK":
            return {"ok": False, "error": f"No se pudo abrir INBOX: {estado}"}
        return {"ok": True, "cuenta": settings.imap_user, "mensajes_en_inbox": int(datos[0])}
    except ImapNoConfigurado as exc:
        return {"ok": False, "error": str(exc)}
    except imaplib.IMAP4.error as exc:
        # Google devuelve "AUTHENTICATIONFAILED" tanto si la contrasena esta mal
        # como si es la del correo en vez de una de aplicacion.
        return {
            "ok": False,
            "error": (
                f"Gmail rechazo las credenciales ({exc}). Revisa que sea una "
                "contrasena de APLICACION de 16 letras, no la de tu cuenta, y que "
                "tengas la verificacion en 2 pasos activada."
            ),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"No se pudo conectar: {exc}"}
    finally:
        _cerrar(imap)


def _cerrar(imap) -> None:
    if not imap:
        return
    try:
        imap.close()
    except Exception:  # noqa: BLE001
        pass
    try:
        imap.logout()
    except Exception:  # noqa: BLE001
        pass


def _uids_por_remitente(imap: imaplib.IMAP4_SSL, desde: str, remitentes: list[str]) -> list[bytes]:
    """Un SEARCH por remitente y se unen los resultados.

    IMAP soporta OR, pero encadenarlo para N remitentes produce una consulta
    anidada ilegible y cada servidor la interpreta a su manera. N consultas
    simples son mas lentas y mucho mas faciles de depurar.

    **Va por UID, no por numero de secuencia.** `imap.search()` a secas devuelve
    Message Sequence Numbers: la posicion del correo en el buzon, que cambia en
    cuanto borras o archivas algo. Como el identificador del correo archivado se
    construye con ese numero, al mover correos en Gmail los numeros se
    desplazaban y un correo nuevo podia heredar el de uno ya procesado: se
    descartaba en silencio y el gasto se perdia. El UID no se reutiliza.
    """
    encontrados: list[bytes] = []
    vistos: set[bytes] = set()
    for remitente in remitentes:
        estado, datos = imap.uid("search", None, "SINCE", desde, "FROM", f'"{remitente}"')
        if estado != "OK":
            log.warning("IMAP SEARCH fallo para %s: %s", remitente, estado)
            continue
        for uid in datos[0].split():
            if uid not in vistos:
                vistos.add(uid)
                encontrados.append(uid)
    # Ordenados por UID: como se buscó remitente a remitente, la lista venia por
    # bloques y quedarse con "los ultimos N" recortaba el primer remitente
    # entero en vez de los correos mas antiguos.
    return sorted(encontrados, key=int)


def fetch_messages(dias: int, remitentes: list[str], max_results: int = 300) -> list[RawEmail]:
    """Descarga los correos de esos remitentes en los ultimos N dias."""
    imap = _conectar()
    try:
        imap.select("INBOX", readonly=True)          # readonly: no marca como leidos
        desde = (datetime.now() - timedelta(days=dias)).strftime("%d-%b-%Y")
        uids = _uids_por_remitente(imap, desde, remitentes)
        log.info("IMAP: %s correos candidatos desde %s", len(uids), desde)

        correos: list[RawEmail] = []
        for uid in uids[-max_results:]:              # los mas recientes primero
            estado, datos = imap.uid("fetch", uid, "(RFC822)")
            if estado != "OK" or not datos or not isinstance(datos[0], tuple):
                log.warning("no se pudo leer el UID %s", uid)
                continue

            msg = email.message_from_bytes(datos[0][1])
            recibido = _fecha(msg)
            correos.append(RawEmail(
                # Identidad del correo, para no procesarlo dos veces. El
                # Message-ID lo pone quien envia y no cambia nunca: sobrevive a
                # que muevas el correo de carpeta, a que Gmail renumere el buzon
                # y a cambiar entre IMAP y la API. El UID solo vale mientras el
                # servidor no reinicie su UIDVALIDITY, asi que va de respaldo.
                gmail_id=_identidad(msg, uid),
                sender=decode_header_value(msg.get("From")),
                subject=decode_header_value(msg.get("Subject")),
                body=extract_body_mime(msg),
                received_at=recibido,
                thread_id=msg.get("Message-ID"),
                snippet="",
            ))
        return correos
    finally:
        _cerrar(imap)


def _identidad(msg, uid: bytes) -> str:
    mid = (msg.get("Message-ID") or "").strip()
    return mid[:250] if mid else f"imap-uid-{uid.decode()}"


def _fecha(msg) -> datetime:
    try:
        fecha = parsedate_to_datetime(msg.get("Date"))
        if not fecha.tzinfo:
            fecha = fecha.replace(tzinfo=timezone.utc)
        return fecha.astimezone(TZ)
    except (TypeError, ValueError):
        return datetime.now(TZ)
