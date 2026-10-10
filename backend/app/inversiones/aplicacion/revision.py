"""Revision en seco de un lote de estados de cuenta: los lee y los valida.

No escribe nada. Es el paso previo a importar: dice que documentos se pueden
usar y, de los que no, que comprobacion fallo.
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, field

from app.inversiones.aplicacion.puertos import LectorDePdf
from app.inversiones.dominio import estado_cuenta, validacion
from app.inversiones.dominio.estado_cuenta import EstadoDeCuenta, NoEsEstadoDeCuenta
from app.inversiones.dominio.validacion import Error


@dataclass
class Documento:
    nombre: str
    huella: str
    estado: EstadoDeCuenta | None = None
    errores: list[Error] = field(default_factory=list)

    @property
    def valido(self) -> bool:
        return self.estado is not None and not self.errores


@dataclass
class Informe:
    documentos: list[Documento]
    errores_de_serie: list[Error]

    @property
    def estados(self) -> list[EstadoDeCuenta]:
        """Los estados validos, en orden cronologico."""
        return sorted((d.estado for d in self.documentos if d.valido), key=lambda e: e.inicio)

    @property
    def todo_cuadra(self) -> bool:
        return all(d.valido for d in self.documentos) and not self.errores_de_serie


class ServicioRevision:
    def __init__(self, lector: LectorDePdf):
        self.lector = lector

    def revisar(self, documentos: Iterable[tuple[str, bytes]]) -> Informe:
        revisados: list[Documento] = []
        vistos: dict[str, Documento] = {}
        for nombre, contenido in documentos:
            doc = Documento(nombre=nombre, huella=hashlib.sha256(contenido).hexdigest())
            revisados.append(doc)
            if doc.huella in vistos:
                original = vistos[doc.huella].nombre
                doc.errores.append(Error("DUPLICADO", f"mismo archivo que {original}"))
                continue
            vistos[doc.huella] = doc
            try:
                doc.estado = estado_cuenta.leer(self.lector.paginas(contenido))
            except NoEsEstadoDeCuenta as exc:
                doc.errores.append(Error("FORMATO", str(exc)))
                continue
            doc.errores += validacion.validar(doc.estado)

        validos = [d for d in revisados if d.valido]
        errores_de_serie = _periodos_repetidos(validos)
        if not errores_de_serie:
            estados = sorted((d.estado for d in validos), key=lambda e: e.inicio)
            errores_de_serie = validacion.validar_serie(estados)
        return Informe(documentos=revisados, errores_de_serie=errores_de_serie)


def _periodos_repetidos(documentos: list[Documento]) -> list[Error]:
    por_periodo: dict[tuple, list[str]] = {}
    for d in documentos:
        por_periodo.setdefault((d.estado.inicio, d.estado.fin), []).append(d.nombre)
    return [
        Error("SERIE", f"el periodo {inicio}..{fin} esta en varios archivos: {', '.join(nombres)}")
        for (inicio, fin), nombres in por_periodo.items() if len(nombres) > 1
    ]
