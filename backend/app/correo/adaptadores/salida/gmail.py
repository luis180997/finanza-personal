"""Cliente de Gmail (solo lectura).

FLUJO OAUTH: web con redireccion, no de escritorio.

El flujo de "aplicacion de escritorio" (`run_local_server`) abre un navegador en
la maquina que ejecuta el backend. Dentro de un contenedor eso no existe: no hay
navegador y el puerto efimero que abre no esta publicado. Por eso se usa el flujo
web, que funciona igual en Docker, en local y manana detras de la VPN:

    1. El backend genera la URL de consentimiento de Google.
    2. TU navegador la abre y aceptas.
    3. Google redirige a  <OAUTH_REDIRECT_URI>  con un codigo.
    4. El backend canjea el codigo por el token y lo guarda.

Configuracion en Google Cloud Console:
    - APIs y servicios -> Biblioteca -> Gmail API -> Habilitar
    - Pantalla de consentimiento OAuth -> Externo -> agregate como usuario de prueba
    - Credenciales -> ID de cliente OAuth -> tipo "Aplicacion web"
    - URI de redireccion autorizados (registra los que vayas a usar):
          http://localhost:8080/api/gmail/callback     (Docker)
          http://localhost:5173/api/gmail/callback     (desarrollo con Vite)
    - Descarga el JSON y guardalo donde apunte GMAIL_CREDENTIALS_FILE

Alcance usado: gmail.readonly. La app NUNCA puede enviar ni borrar correo.
"""
from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from app.plataforma.config import settings
from app.correo.adaptadores.salida.html import extract_body
from app.correo.dominio.correo import RawEmail

log = logging.getLogger(__name__)
TZ = ZoneInfo(settings.timezone)

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


class GmailNotConfigured(RuntimeError):
    """Falta credentials.json, o el token todavia no existe."""


class GmailEstadoInvalido(RuntimeError):
    """El parametro `state` del callback no coincide: posible CSRF."""


# --------------------------------------------------------------------------- rutas
def _ruta_credenciales() -> Path:
    return Path(settings.gmail_credentials_file)


def _ruta_token() -> Path:
    return Path(settings.gmail_token_file)


def has_credentials() -> bool:
    return _ruta_credenciales().exists()


def is_authorized() -> bool:
    return _ruta_token().exists()


def tipo_cliente() -> str | None:
    """'web' o 'installed'. Sirve para avisar si el JSON es del tipo equivocado."""
    if not has_credentials():
        return None
    try:
        datos = json.loads(_ruta_credenciales().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    for clave in ("web", "installed"):
        if clave in datos:
            return clave
    return None


# --------------------------------------------------------------------------- flujo
def _flow(state: str | None = None):
    from google_auth_oauthlib.flow import Flow

    if not has_credentials():
        raise GmailNotConfigured(
            f"Falta {_ruta_credenciales()}. Descarga el JSON de OAuth (tipo "
            "'Aplicacion web') desde Google Cloud Console y guardalo ahi."
        )
    return Flow.from_client_secrets_file(
        str(_ruta_credenciales()),
        scopes=SCOPES,
        redirect_uri=settings.oauth_redirect_uri,
        state=state,
    )


def url_autorizacion() -> tuple[str, str]:
    """Devuelve (url_de_consentimiento, state). El state se valida en el callback."""
    flow = _flow()
    url, state = flow.authorization_url(
        access_type="offline",       # imprescindible para obtener refresh_token
        prompt="consent",            # fuerza el refresh_token aunque ya hubieras aceptado
        include_granted_scopes="true",
    )
    return url, state


def canjear_codigo(code: str, state: str | None = None):
    """Cambia el codigo de Google por credenciales y las persiste."""
    flow = _flow(state=state)
    flow.fetch_token(code=code)
    creds = flow.credentials
    _guardar_token(creds)
    return creds


def _guardar_token(creds) -> None:
    ruta = _ruta_token()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(creds.to_json(), encoding="utf-8")
    try:
        ruta.chmod(0o600)            # el token es la llave de tu correo
    except OSError:
        pass                          # sistemas de archivos sin permisos POSIX


def revocar() -> None:
    """Borra el token local. No revoca en Google: eso se hace desde tu cuenta."""
    _ruta_token().unlink(missing_ok=True)


def _credentials():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    ruta = _ruta_token()
    if not ruta.exists():
        raise GmailNotConfigured(
            "Gmail todavia no esta autorizado. Ve a la pantalla Correo y pulsa "
            "'Conectar Gmail'."
        )

    creds = Credentials.from_authorized_user_file(str(ruta), SCOPES)
    if creds.valid:
        return creds
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _guardar_token(creds)
        return creds
    raise GmailNotConfigured(
        "El token de Gmail caduco y no se pudo renovar. Vuelve a conectar la cuenta."
    )


def get_service():
    from googleapiclient.discovery import build

    return build("gmail", "v1", credentials=_credentials(), cache_discovery=False)


def profile() -> dict:
    return get_service().users().getProfile(userId="me").execute()


# --------------------------------------------------------------------------- lectura
def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def nuevo_state() -> str:
    return secrets.token_urlsafe(24)


def fetch_messages(query: str, max_results: int = 200) -> list[RawEmail]:
    """Busca por query de Gmail y devuelve los correos aplanados."""
    svc = get_service()
    ids: list[str] = []
    page_token = None

    while len(ids) < max_results:
        resp = (
            svc.users()
            .messages()
            .list(userId="me", q=query, maxResults=min(100, max_results - len(ids)),
                  pageToken=page_token)
            .execute()
        )
        ids.extend(m["id"] for m in resp.get("messages", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    emails: list[RawEmail] = []
    for msg_id in ids:
        try:
            msg = svc.users().messages().get(userId="me", id=msg_id, format="full").execute()
        except Exception as exc:  # noqa: BLE001 - un correo roto no debe tumbar la sync
            log.warning("no se pudo leer el mensaje %s: %s", msg_id, exc)
            continue
        payload = msg.get("payload", {}) or {}
        headers = payload.get("headers", []) or []
        received = datetime.fromtimestamp(int(msg.get("internalDate", 0)) / 1000, tz=TZ)
        emails.append(
            RawEmail(
                gmail_id=msg["id"],
                thread_id=msg.get("threadId"),
                sender=_header(headers, "From"),
                subject=_header(headers, "Subject"),
                body=extract_body(payload),
                received_at=received,
                snippet=msg.get("snippet", ""),
            )
        )
    return emails
