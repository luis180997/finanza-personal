"""Casos de uso de los topes de presupuesto y de la meta de ahorro.

Ambos se configuran desde la interfaz, no desde el codigo: un tope es una
decision tuya que va a cambiar, y tocar un archivo y reiniciar para subir el
tope de delivery es friccion suficiente para que dejes de usarlo.
"""
from __future__ import annotations

from app.analitica.aplicacion.puertos import CatalogoDeCategorias, MetaDeAhorro, RepositorioTopes
from app.analitica.dominio.entidades import Budget
from app.clasificacion.dominio.entidades import Category
from app.compartido import reloj
from app.compartido.dinero import to_cents
from app.compartido.errores import DatoInvalido, NoEncontrado
from app.compartido.puertos import UnidadDeTrabajo
from app.compartido.tipos import Direction


class ServicioPresupuestos:
    def __init__(
        self,
        topes: RepositorioTopes,
        uow: UnidadDeTrabajo,
        categorias: CatalogoDeCategorias | None = None,
        meta: MetaDeAhorro | None = None,
    ):
        self.topes = topes
        self.uow = uow
        self.categorias = categorias
        self.meta = meta

    # --------------------------------------------------------------------- topes
    def listar(self) -> list[tuple[Budget, Category]]:
        """Cada tope con su categoria (los de categorias que ya no existen, fuera)."""
        categorias = self.categorias.todas()
        return [(b, categorias[b.category_id]) for b in self.topes.todos() if b.category_id in categorias]

    def guardar(self, category_id: int, amount: float, active: bool) -> tuple[Budget, Category]:
        """Crea o actualiza el tope de una categoria. Un solo caso de uso: desde la
        interfaz "poner tope" y "cambiar tope" son el mismo gesto."""
        cat = self.categorias.obtener(category_id)
        if not cat:
            raise NoEncontrado("Categoria no encontrada")
        if cat.kind != Direction.gasto:
            raise DatoInvalido("Solo se pueden poner topes a categorias de gasto")

        existentes = self.topes.de_categoria(category_id)
        if existentes:
            tope = existentes[0]
            tope.amount_cents = to_cents(amount)
            tope.active = active
            tope.updated_at = reloj.ahora_utc()
        else:
            tope = Budget(category_id=category_id, amount_cents=to_cents(amount), active=active)
        self.topes.agregar(tope)
        self.uow.confirmar()
        self.uow.refrescar(tope)
        return tope, cat

    def borrar(self, tope_id: int) -> None:
        tope = self.topes.obtener(tope_id)
        if not tope:
            raise NoEncontrado("Presupuesto no encontrado")
        self.topes.borrar(tope)
        self.uow.confirmar()

    # ------------------------------------------------------------ meta de ahorro
    def meta_cents(self) -> int:
        valor = self.meta.leer()
        return int(valor) if valor and valor.isdigit() else 0

    def guardar_meta(self, amount: float) -> int:
        cents = to_cents(amount)
        self.meta.guardar(cents)
        return cents

    # ------------------------------------------- para el modulo de clasificacion
    def reasignar_topes(self, cat_id: int, destino_id: int | None) -> None:
        """La categoria se borra: su tope pasa a `destino_id`, salvo que el destino ya
        tenga uno (una categoria tiene un solo tope). Si no pasa, se borra. No
        confirma: lo hace quien borra la categoria."""
        destino_tiene_tope = destino_id is not None and self.topes.existe_para(destino_id)
        for tope in self.topes.de_categoria(cat_id):
            if destino_id is not None and not destino_tiene_tope:
                tope.category_id = destino_id
                self.topes.agregar(tope)
            else:
                self.topes.borrar(tope)
