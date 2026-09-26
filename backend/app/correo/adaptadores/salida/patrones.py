"""Catalogo de patrones: lee patterns.yaml, lo cachea en memoria y lo recarga en caliente.

Es el adaptador del puerto `CatalogoDePatrones`. El motor que interpreta las reglas
es dominio (correo/dominio/parsers.py); aqui solo se lee el archivo.
"""
from __future__ import annotations

import threading
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from app.correo.dominio.correo import ParsedTx, RawEmail
from app.correo.dominio.parsers import PatternBundle, construir_bundle, consulta_gmail, leer
from app.plataforma.config import settings

PATTERNS_FILE = Path(__file__).resolve().parents[2] / "patterns.yaml"

_lock = threading.Lock()
_bundle: PatternBundle | None = None


def load_patterns(path: Path | None = None) -> PatternBundle:
    data = yaml.safe_load((path or PATTERNS_FILE).read_text(encoding="utf-8")) or {}
    return construir_bundle(data, ZoneInfo(settings.timezone))


def get_bundle() -> PatternBundle:
    global _bundle
    with _lock:
        if _bundle is None:
            _bundle = load_patterns()
        return _bundle


def reload_bundle() -> PatternBundle:
    global _bundle
    with _lock:
        _bundle = load_patterns()
        return _bundle


def gmail_query(lookback_days: int) -> str:
    return consulta_gmail(get_bundle(), lookback_days)


def parse_email(
    email: RawEmail, ignorar_remitente: bool = False
) -> tuple[ParsedTx | None, str | None]:
    return leer(get_bundle(), email, ignorar_remitente)


def confianza_del_parser(parser_id: str) -> float | None:
    """Lo seguro que declara un parser al LEER el correo."""
    for p in get_bundle().parsers:
        if p.id == parser_id:
            return p.confidence
    return None


class PatronesYaml:
    """El puerto `CatalogoDePatrones` sobre las funciones de arriba."""

    def actual(self) -> PatternBundle:
        return get_bundle()

    def recargar(self) -> PatternBundle:
        return reload_bundle()

    def leer(
        self, email: RawEmail, ignorar_remitente: bool = False,
    ) -> tuple[ParsedTx | None, str | None]:
        return parse_email(email, ignorar_remitente)
