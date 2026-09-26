"""Caso de uso: el laboratorio de parsers.

Pega el texto de un correo real y mira exactamente que extraen los patrones. Es
la herramienta para calibrar patterns.yaml sin adivinar.
"""
from __future__ import annotations

from app.compartido import reloj
from app.compartido.comercio import clean_text, normalize_merchant
from app.correo.aplicacion.puertos import CatalogoDePatrones
from app.correo.dominio.correo import RawEmail


def probar(patrones: CatalogoDePatrones, sender: str, subject: str, body: str) -> dict:
    email = RawEmail(
        gmail_id="prueba",
        sender=sender,
        subject=subject,
        body=body,
        received_at=reloj.ahora_local(),
    )
    parsed, motivo = patrones.leer(email)

    # Si no pusiste remitente, reintentamos ignorando esa condicion: casi siempre
    # se pega solo el cuerpo del correo y el remitente exacto no se recuerda.
    nota = None
    if not parsed and not sender.strip():
        parsed, motivo_sin_remitente = patrones.leer(email, ignorar_remitente=True)
        if parsed:
            nota = (
                "Coincidio ignorando el remitente (lo dejaste vacio). En produccion "
                "el remitente tambien tiene que coincidir con los de patterns.yaml."
            )
        else:
            motivo = motivo_sin_remitente

    if not parsed:
        return {
            "reconocido": False,
            "motivo": motivo,
            "texto_normalizado": clean_text(email.haystack)[:4000],
        }
    return {
        "reconocido": True,
        "parser": parsed.parser,
        "motivo": nota,
        "resultado": {
            "monto": float(parsed.amount),
            "moneda": parsed.currency,
            "direccion": parsed.direction,
            "fecha": parsed.occurred_at.isoformat() if parsed.occurred_at else None,
            "comercio_crudo": parsed.merchant_raw,
            "comercio_normalizado": normalize_merchant(parsed.merchant_raw),
            "operacion": parsed.operation_number,
            "ultimos4": parsed.last4,
            "cuenta_sugerida": parsed.account_hint,
            "confianza": parsed.confidence,
        },
        "texto_normalizado": clean_text(email.haystack)[:4000],
    }
