"""Casos de uso de los movimientos que entran por lotes (el importador del Excel)."""
from __future__ import annotations

from app.compartido.puertos import UnidadDeTrabajo
from app.movimientos.aplicacion.puertos import RepositorioMovimientos
from app.movimientos.dominio.entidades import Transaction
from app.movimientos.dominio.movimiento import (
    preparar_para_deshacer_lote,
    soltar_duplicado_de_lote,
)


class ServicioLotes:
    def __init__(self, repo: RepositorioMovimientos, uow: UnidadDeTrabajo):
        self.repo = repo
        self.uow = uow

    def existe_huella(self, huella: str) -> bool:
        return self.repo.por_huella(huella) is not None

    def agregar_importado(self, tx: Transaction) -> None:
        """No confirma: el importador confirma por tandas."""
        self.repo.agregar(tx)

    def protegidos_del_lote(self, lote_id: int) -> int:
        return self.repo.protegidos_del_lote(lote_id)

    def deshacer_lote(self, lote_id: int) -> int:
        """Borra los movimientos del lote. Quedan en la papelera (la escribe el trigger)."""
        movs = self.repo.del_lote(lote_id)

        # duplicate_of_id puede apuntar a una fila del lote desde FUERA de el: un
        # movimiento del correo o manual marcado como posible duplicado de un dia del
        # Excel. Sin soltar esa referencia la clave foranea rechazaba el borrado y
        # deshacer devolvia un 500.
        for otro in self.repo.duplicados_de_fuera_del_lote(lote_id):
            soltar_duplicado_de_lote(otro, lote_id)
            self.repo.agregar(otro)
        for tx in movs:
            preparar_para_deshacer_lote(tx)
            self.repo.agregar(tx)
        self.uow.confirmar()
        for tx in movs:
            self.repo.borrar(tx)
        self.uow.confirmar()
        return len(movs)
