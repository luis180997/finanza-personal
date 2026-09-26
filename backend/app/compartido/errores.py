"""Errores de negocio.

Los casos de uso no conocen HTTP: lanzan estos errores y el adaptador web los
traduce a una respuesta con su codigo (main.py). Asi el mismo caso de uso sirve
igual desde una ruta, desde el programador o desde un script.
"""
from __future__ import annotations


class ErrorDeNegocio(Exception):
    """Base. `estado_http` es el codigo con el que lo contesta la API."""

    estado_http = 400

    def __init__(self, mensaje: str):
        super().__init__(mensaje)
        self.mensaje = mensaje


class DatoInvalido(ErrorDeNegocio):
    estado_http = 400


class NoPermitido(ErrorDeNegocio):
    estado_http = 403


class NoEncontrado(ErrorDeNegocio):
    estado_http = 404


class Conflicto(ErrorDeNegocio):
    estado_http = 409


class DemasiadoGrande(ErrorDeNegocio):
    estado_http = 413


class NoDisponible(ErrorDeNegocio):
    estado_http = 503
