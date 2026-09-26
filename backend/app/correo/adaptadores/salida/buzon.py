"""El puerto `FuenteDeCorreos`: IMAP o la API de Gmail, segun EMAIL_BACKEND."""
from __future__ import annotations

from app.correo.adaptadores.salida import gmail, imap
from app.correo.adaptadores.salida.patrones import get_bundle, gmail_query
from app.correo.aplicacion.puertos import FuenteNoConfigurada
from app.correo.dominio.correo import RawEmail
from app.plataforma.config import settings


class BuzonSegunConfiguracion:
    @property
    def canal(self) -> str:
        return "IMAP" if settings.usa_imap else "Gmail"

    def descargar(self, dias: int, max_correos: int) -> tuple[list[RawEmail], str]:
        """Trae los correos por el canal configurado. Devuelve (correos, descripcion)."""
        try:
            if settings.usa_imap:
                remitentes = get_bundle().senders
                return (
                    imap.fetch_messages(dias, remitentes, max_results=max_correos),
                    f"IMAP · {len(remitentes)} remitentes · ultimos {dias} dias",
                )
            query = gmail_query(dias)
            return gmail.fetch_messages(query, max_results=max_correos), query
        except (gmail.GmailNotConfigured, imap.ImapNoConfigurado) as exc:
            raise FuenteNoConfigurada(str(exc)) from exc
