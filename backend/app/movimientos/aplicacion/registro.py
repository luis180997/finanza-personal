"""Caso de uso: registrar un movimiento que llega del banco.

Lo usan el correo (sincronizacion y re-parseo). Vive en un solo sitio a proposito:
cuando cada camino tenia su copia, el re-parseo se quedo sin la deteccion de
mellizos y volvio a duplicar los retiros del BBVA.
"""
from __future__ import annotations

from app.compartido.puertos import UnidadDeTrabajo
from app.movimientos.aplicacion.papelera import ServicioPapelera
from app.movimientos.aplicacion.puertos import RepositorioMovimientos
from app.movimientos.dominio.duplicados import (
    CROSS_WINDOW,
    elegir_mellizo,
    elegir_sospechoso,
    marcar_mellizo,
    marcar_sospecha,
)
from app.movimientos.dominio.entidades import Transaction
from app.movimientos.dominio.movimiento import antes_del_corte


class RegistroDeMovimientos:
    def __init__(
        self, repo: RepositorioMovimientos, papelera: ServicioPapelera, uow: UnidadDeTrabajo,
    ):
        self.repo = repo
        self.papelera = papelera
        self.uow = uow

    def mellizo_de(self, tx: Transaction) -> Transaction | None:
        return elegir_mellizo(tx, self.repo.candidatos_mellizo(tx))

    def sospecha_de_duplicado(self, tx: Transaction) -> Transaction | None:
        return elegir_sospechoso(tx, self.repo.candidatos_cruzados(tx, CROSS_WINDOW))

    def registrar(self, tx: Transaction) -> str:
        """Inserta el movimiento aplicando los tres filtros antiduplicado.

        Devuelve que paso: "creado", "reaplicado", "mellizo" (se guarda como
        duplicado), "duplicado" (no se guarda: ya existia) o "corte" (no se guarda:
        anterior a la frontera con el Excel, compartido/corte.py).
        """
        if antes_del_corte(tx):
            return "corte"

        # 1. Huella exacta: el mismo movimiento ya esta guardado.
        if self.repo.por_huella(tx.dedupe_hash):
            return "duplicado"

        # 1b. Este movimiento ya existio con decisiones tuyas y alguien lo borro (un
        #     script, una limpieza). Vuelve con TU clasificacion, no con una nueva, y
        #     sin pasar por las sospechas de duplicado: ya lo habias revisado tu.
        if self.papelera.reaplicar(tx):
            # Tus decisiones pueden traer la fecha que corregiste, y esa fecha tambien
            # tiene que respetar el corte.
            if antes_del_corte(tx):
                return "corte"
            self.repo.agregar(tx)
            self.uow.confirmar()
            return "reaplicado"

        # 2. Mellizo: el mismo movimiento notificado por dos correos distintos (el
        #    BBVA lo hace con cada retiro). Se guarda marcado como duplicado, asi no
        #    cuenta en ningun total y queda el rastro de por que.
        mellizo = self.mellizo_de(tx)
        if mellizo:
            marcar_mellizo(tx, mellizo)
            self.repo.agregar(tx)
            self.uow.confirmar()
            return "mellizo"

        self.repo.agregar(tx)
        self.uow.confirmar()
        self.uow.refrescar(tx)

        # 3. Sospecha cruzada: parecido pero no identico. Aqui NO se decide nada,
        #    solo se avisa; la ultima palabra es del usuario.
        gemelo = self.sospecha_de_duplicado(tx)
        if gemelo:
            marcar_sospecha(tx, gemelo)
            self.repo.agregar(tx)
            self.uow.confirmar()
        return "creado"
