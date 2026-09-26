"""Casos de uso de la papelera: ver lo borrado, restaurarlo y recuperar decisiones."""
from __future__ import annotations

from app.compartido import reloj
from app.compartido.errores import Conflicto, NoEncontrado
from app.compartido.puertos import UnidadDeTrabajo
from app.movimientos.aplicacion.puertos import RepositorioMovimientos, RepositorioPapelera
from app.movimientos.dominio.entidades import Transaction
from app.movimientos.dominio.movimiento import proteger
from app.movimientos.dominio.papelera import (
    huella_de,
    id_de,
    para_listado,
    reaplicar_decisiones,
    reconstruir,
)


class ServicioPapelera:
    def __init__(
        self, papelera: RepositorioPapelera, repo: RepositorioMovimientos, uow: UnidadDeTrabajo,
    ):
        self.papelera = papelera
        self.repo = repo
        self.uow = uow

    def _soltar_referencias_rotas(self, tx: Transaction) -> None:
        """Una categoria o cuenta borrada despues no puede impedir recuperar el resto."""
        for campo in self.papelera.referencias_rotas(tx):
            setattr(tx, campo, None)

    def listar(self, limite: int = 50) -> list[dict]:
        """Movimientos borrados, del mas reciente al mas antiguo."""
        filas = self.papelera.ultimas(limite)
        # Un movimiento borrado puede haber vuelto solo (se reproceso su correo).
        # Restaurarlo entonces lo contaria dos veces: la interfaz ofrece verlo.
        huellas = [f.dedupe_hash for f in filas if f.dedupe_hash]
        vivos = self.repo.ids_por_huella(huellas) if huellas else {}
        return [para_listado(f, vivos.get(f.dedupe_hash)) for f in filas]

    def restaurar(self, papelera_id: int) -> Transaction:
        """Devuelve a la tabla un movimiento de la papelera, tal cual estaba."""
        fila = self.papelera.obtener(papelera_id)
        if fila is None:
            raise NoEncontrado("Ese movimiento no esta en la papelera.")
        ya_existe = self.repo.por_huella(huella_de(fila))
        if ya_existe:
            raise Conflicto(
                f"Ese movimiento ya existe (#{ya_existe.id}); quiza volvio al reprocesar su "
                "correo. No se restaura para no contarlo dos veces."
            )

        id_original = id_de(fila)
        tx = reconstruir(
            fila, id_libre=id_original is None or self.repo.obtener(id_original) is None,
        )
        self._soltar_referencias_rotas(tx)
        proteger(tx, reloj.ahora_utc())            # restaurarlo es una decision tuya
        self.repo.agregar(tx)
        self.papelera.borrar(fila)
        self.uow.confirmar()
        self.uow.refrescar(tx)
        return tx

    def reaplicar(self, tx: Transaction) -> bool:
        """Si este movimiento ya existio con decisiones tuyas y se borro, se las devuelve.

        Se busca por el correo del que sale y, si ese correo se reimporto con otro id,
        por la huella del movimiento (fecha, importe, comercio, operacion). Devuelve True
        si encontro y aplico tus decisiones. No confirma.
        """
        fila = self.papelera.decisiones_para(tx.dedupe_hash, tx.email_id)
        if fila is None:
            return False
        reaplicar_decisiones(tx, fila, reloj.ahora_utc())
        self._soltar_referencias_rotas(tx)
        return True
