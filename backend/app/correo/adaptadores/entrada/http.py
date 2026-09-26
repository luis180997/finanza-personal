"""Rutas del correo: estado de la conexion, OAuth, sincronizacion, archivo y
laboratorio de parsers. Solo traducen HTTP <-> caso de uso."""
from __future__ import annotations

import secrets
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from app.correo.adaptadores import fabrica
from app.correo.adaptadores.entrada.esquemas import (
    EmailOut,
    PruebaParserIn,
    PruebaParserOut,
    SyncIn,
    SyncOut,
)
from app.correo.adaptadores.salida import gmail as gmail_client
from app.correo.adaptadores.salida import imap as imap_client
from app.correo.adaptadores.salida.patrones import get_bundle, gmail_query
from app.correo.aplicacion import laboratorio
from app.correo.aplicacion.sincronizacion import ServicioSincronizacion
from app.correo.dominio.entidades import EmailMessage, ParseStatus
from app.plataforma import kv
from app.plataforma.config import settings
from app.plataforma.db import get_session

router = APIRouter()


def _sincronizador(session: Session = Depends(get_session)) -> ServicioSincronizacion:
    return fabrica.sincronizador(session)


def _email_out(c: EmailMessage, con_cuerpo: bool) -> EmailOut:
    return EmailOut(
        id=c.id, gmail_id=c.gmail_id, sender=c.sender, subject=c.subject,
        received_at=c.received_at, snippet=c.snippet,
        parse_status=c.parse_status.value, parser=c.parser, error=c.error,
        body_text=c.body_text if con_cuerpo else None,
    )


@router.get("/gmail/estado", tags=["gmail"])
def estado(session: Session = Depends(get_session)):
    ultima = kv.leer(session, "ultima_sync")

    if settings.usa_imap:
        configurado = imap_client.esta_configurado()
        return {
            "backend": "imap",
            "credenciales_presentes": configurado,
            "autorizado": configurado,
            "cuenta": settings.imap_user or None,
            "servidor": f"{settings.imap_host}:{settings.imap_port}",
            "sync_automatica_min": settings.sync_interval_minutes,
            "ventana_automatica": settings.gmail_lookback_days,
            "retencion_dias": settings.email_retention_days,
            "ultima_sync": ultima,
            "query": f"IMAP · {len(get_bundle().senders)} remitentes",
            "remitentes": get_bundle().senders,
            "parsers": [
                {"id": p.id, "label": p.label, "banco": p.bank, "prioridad": p.priority}
                for p in get_bundle().parsers
            ],
        }

    correo = None
    if gmail_client.is_authorized():
        try:
            correo = gmail_client.profile().get("emailAddress")
        except Exception as exc:  # noqa: BLE001
            correo = f"(token invalido: {exc})"
    return {
        "backend": "gmail",
        "credenciales_presentes": gmail_client.has_credentials(),
        "tipo_cliente": gmail_client.tipo_cliente(),
        "redirect_uri": settings.oauth_redirect_uri,
        "autorizado": gmail_client.is_authorized(),
        "cuenta": correo,
        "sync_automatica_min": settings.sync_interval_minutes,
        "ventana_automatica": settings.gmail_lookback_days,
        "retencion_dias": settings.email_retention_days,
        "ultima_sync": ultima,
        "query": gmail_query(settings.gmail_lookback_days),
        "remitentes": get_bundle().senders,
        "parsers": [
            {"id": p.id, "label": p.label, "banco": p.bank, "prioridad": p.priority}
            for p in get_bundle().parsers
        ],
    }


@router.post("/correo/probar", tags=["gmail"])
def probar_conexion():
    """Comprueba las credenciales IMAP sin descargar nada."""
    if not settings.usa_imap:
        raise HTTPException(400, "Esta prueba es solo para el modo IMAP")
    return imap_client.probar_conexion()


@router.post("/gmail/autorizar", tags=["gmail"])
def autorizar(session: Session = Depends(get_session)):
    """Paso 1 del OAuth: devuelve la URL de consentimiento de Google.

    No abre nada por su cuenta. El frontend lleva TU navegador a esa URL, que es
    lo unico que funciona igual en local, en Docker y detras de una VPN.
    """
    if not gmail_client.has_credentials():
        raise HTTPException(
            400,
            f"Falta el archivo {settings.gmail_credentials_file}. "
            "Descargalo de Google Cloud Console (OAuth, tipo 'Aplicacion web').",
        )
    try:
        url, state = gmail_client.url_autorizacion()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"No se pudo iniciar el flujo OAuth: {exc}") from exc

    kv.guardar(session, "oauth_state", state)
    return {"url": url, "redirect_uri": settings.oauth_redirect_uri}


@router.get("/gmail/callback", tags=["gmail"], include_in_schema=False)
def callback(
    session: Session = Depends(get_session),
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    """Paso 2: Google redirige aqui. Canjea el codigo y devuelve al navegador a la app."""
    destino = f"{settings.app_base_url.rstrip('/')}/correo"

    if error:
        return RedirectResponse(f"{destino}?gmail=error&detalle={quote(error)}")
    if not code:
        return RedirectResponse(f"{destino}?gmail=error&detalle=falta_codigo")

    esperado = kv.leer(session, "oauth_state")
    if esperado is None or not state or not secrets.compare_digest(esperado, state):
        return RedirectResponse(f"{destino}?gmail=error&detalle=state_invalido")

    try:
        gmail_client.canjear_codigo(code, state=state)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(f"{destino}?gmail=error&detalle={quote(str(exc)[:200])}")

    kv.guardar(session, "oauth_state", "")
    return RedirectResponse(f"{destino}?gmail=ok")


@router.post("/gmail/desconectar", tags=["gmail"])
def desconectar():
    """Borra el token local. Para revocar el acceso del todo, hazlo tambien en
    https://myaccount.google.com/permissions"""
    gmail_client.revocar()
    return {"autorizado": False}


@router.post("/gmail/sincronizar", response_model=SyncOut, tags=["gmail"])
def sincronizar(
    datos: SyncIn | None = None, servicio: ServicioSincronizacion = Depends(_sincronizador),
):
    datos = datos or SyncIn()
    resultado = servicio.sincronizar(dias=datos.dias, max_correos=datos.max_correos)
    return SyncOut(**resultado.__dict__)


@router.post("/gmail/reparsear", response_model=SyncOut, tags=["gmail"])
def reparsear(servicio: ServicioSincronizacion = Depends(_sincronizador)):
    """Re-procesa los correos archivados que quedaron sin parser.
    Uselo despues de tocar patterns.yaml."""
    resultado = servicio.reparsear_pendientes()
    return SyncOut(**resultado.__dict__)


@router.get("/gmail/correos", response_model=list[EmailOut], tags=["gmail"])
def listar_correos(
    servicio: ServicioSincronizacion = Depends(_sincronizador),
    estado: ParseStatus | None = None,
    limite: int = Query(50, ge=1, le=300),
    incluir_cuerpo: bool = False,
):
    return [_email_out(c, incluir_cuerpo) for c in servicio.listar_correos(estado, limite)]


@router.get("/gmail/correos/{correo_id}", response_model=EmailOut, tags=["gmail"])
def ver_correo(correo_id: int, servicio: ServicioSincronizacion = Depends(_sincronizador)):
    c = servicio.ver_correo(correo_id)
    if not c:
        raise HTTPException(404, "Correo no encontrado")
    return _email_out(c, True)


# ------------------------------------------------------------------ laboratorio
@router.post("/parsers/probar", response_model=PruebaParserOut, tags=["parsers"])
def probar(datos: PruebaParserIn):
    """Pega el texto de un correo real y mira exactamente que extraen los
    patrones. Es la herramienta para calibrar patterns.yaml sin adivinar."""
    return PruebaParserOut(
        **laboratorio.probar(fabrica.patrones(), datos.sender, datos.subject, datos.body)
    )


@router.post("/parsers/recargar", tags=["parsers"])
def recargar():
    """Recarga patterns.yaml sin reiniciar el servidor."""
    bundle = fabrica.patrones().recargar()
    return {
        "parsers": len(bundle.parsers),
        "remitentes": len(bundle.senders),
        "ids": [p.id for p in bundle.parsers],
    }
