"""El puerto `BuzonHapi` con el lector IMAP de la app (solo lectura).

Reutiliza `imap.fetch_messages`, el mismo que lee los correos del banco: abre el
buzon en modo de solo lectura y no marca nada como leido. Aqui solo se le pide
otro remitente; la sincronizacion de los correos bancarios no cambia.
"""
from __future__ import annotations

from datetime import date

from app.compartido import reloj
from app.correo.adaptadores.salida import imap
from app.inversiones.dominio.correo_hapi import REMITENTE, CorreoHapi
from app.plataforma.config import settings

# Hapi envia del orden de un centenar de correos al anio.
_MAXIMO = 5000


class BuzonImap:
    @property
    def configurado(self) -> bool:
        return settings.usa_imap and imap.esta_configurado()

    def correos(self, desde: date) -> list[CorreoHapi]:
        dias = (reloj.hoy() - desde).days + 1
        return [
            CorreoHapi(message_id=c.gmail_id, recibido=c.received_at,
                       asunto=c.subject or "", cuerpo=c.body or "")
            for c in imap.fetch_messages(dias, [REMITENTE], max_results=_MAXIMO)
        ]
