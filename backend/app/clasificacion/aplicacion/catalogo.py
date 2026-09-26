"""Casos de uso del catalogo: categorias y reglas."""
from __future__ import annotations

from app.clasificacion.aplicacion.puertos import (
    CatalogoCategorias,
    MovimientosDeCategoria,
    RepositorioReglas,
    TopesDeCategoria,
)
from app.clasificacion.dominio.arbol import crearia_ciclo
from app.clasificacion.dominio.entidades import Category, Rule
from app.compartido.dinero import to_cents
from app.compartido.errores import Conflicto, DatoInvalido, NoEncontrado
from app.compartido.puertos import UnidadDeTrabajo


class ServicioCatalogo:
    def __init__(
        self,
        categorias: CatalogoCategorias,
        reglas: RepositorioReglas,
        movimientos: MovimientosDeCategoria,
        topes: TopesDeCategoria,
        uow: UnidadDeTrabajo,
    ):
        self.categorias = categorias
        self.reglas = reglas
        self.movimientos = movimientos
        self.topes = topes
        self.uow = uow

    # ------------------------------------------------------------ categorias
    def listar_categorias(self) -> list[Category]:
        return self.categorias.ordenadas()

    def _exigir_categoria_valida(
        self, nombre: str, parent_id: int | None, propia: int | None = None,
    ) -> None:
        """Padre que exista y nombre libre en ese nivel. Sin esto la base rechazaba la
        fila (clave foranea o nombre repetido) y la API devolvia un 500."""
        if parent_id is not None and not self.categorias.obtener(parent_id):
            raise NoEncontrado("La categoria padre no existe")
        otra = self.categorias.en_nivel(nombre, parent_id)
        if otra and otra.id != propia:
            raise Conflicto(f"Ya existe una categoria '{nombre}' en ese mismo nivel")

    def crear_categoria(self, campos: dict) -> Category:
        self._exigir_categoria_valida(campos["name"], campos.get("parent_id"))
        cat = Category(**campos)
        self.categorias.agregar(cat)
        self.uow.confirmar()
        self.uow.refrescar(cat)
        return cat

    def editar_categoria(self, cat_id: int, cambios: dict) -> Category:
        cat = self.categorias.obtener(cat_id)
        if not cat:
            raise NoEncontrado("Categoria no encontrada")

        nuevo_padre = cambios.get("parent_id", cat.parent_id)
        if nuevo_padre is not None:
            todas = self.categorias.todas()
            if nuevo_padre not in todas:
                raise NoEncontrado("La categoria padre no existe")
            if crearia_ciclo(cat_id, nuevo_padre, todas):
                raise DatoInvalido(
                    "Una categoria no puede colgar de si misma ni de una de sus subcategorias."
                )
        self._exigir_categoria_valida(cambios.get("name", cat.name), nuevo_padre, propia=cat_id)

        for k, v in cambios.items():
            setattr(cat, k, v)
        self.categorias.agregar(cat)
        self.uow.confirmar()
        self.uow.refrescar(cat)
        return cat

    def borrar_categoria(self, cat_id: int, mover_a: int | None = None) -> None:
        cat = self.categorias.obtener(cat_id)
        if not cat:
            raise NoEncontrado("Categoria no encontrada")
        if cat.is_system:
            raise Conflicto("Las categorias del sistema no se borran. Renombrala si quieres.")

        # Una categoria no cuelga sola: pueden apuntarla subcategorias, topes de
        # presupuesto y reglas, todas por clave foranea. Sin soltar esas referencias,
        # el borrado devolvia un 500 en vez de decir que pasaba.
        hijas = self.categorias.hijas(cat_id)
        if hijas:
            nombres = ", ".join(c.name for c in hijas[:5])
            raise Conflicto(
                f"'{cat.name}' tiene {len(hijas)} subcategoria(s) dentro ({nombres}). "
                "Muevelas o borralas antes."
            )

        destino = None
        if mover_a is not None:
            destino = self.categorias.obtener(mover_a)
            if destino is None:
                raise NoEncontrado("La categoria destino no existe")
            if destino.id == cat_id:
                raise DatoInvalido("La categoria destino no puede ser la misma que borras.")

        # Regla 1 de CLAUDE.md: lo que registraste o corregiste no se reclasifica solo.
        # Borrar la categoria los dejaba sin categoria y como confirmados, asi que ni
        # siquiera volvian a la bandeja. Sin un destino explicito, no se borra.
        protegidos = self.movimientos.protegidos_en_categoria(cat_id)
        if protegidos and destino is None:
            raise Conflicto(
                f"'{cat.name}' tiene {protegidos} movimiento(s) que registraste o corregiste tu. "
                "Borrarla los dejaria sin categoria: indica a cual pasan (mover_a) o cambialos antes."
            )

        destino_id = destino.id if destino else None
        self.movimientos.soltar_categoria(cat_id, destino_id)
        for regla in self.reglas.que_apuntan_a(cat_id):
            regla.set_category_id = destino_id
            if destino is None:
                regla.active = False        # una regla sin categoria destino no hace nada
            self.reglas.agregar(regla)
        self.topes.reasignar_topes(cat_id, destino_id)
        self.uow.confirmar()

        self.categorias.borrar(cat)
        self.uow.confirmar()

    # ---------------------------------------------------------------- reglas
    def listar_reglas(self) -> list[Rule]:
        return self.reglas.por_prioridad()

    def crear_regla(self, payload: dict) -> Rule:
        payload["min_amount_cents"] = (
            to_cents(payload.pop("min_amount")) if payload.get("min_amount") else None
        )
        payload["max_amount_cents"] = (
            to_cents(payload.pop("max_amount")) if payload.get("max_amount") else None
        )
        payload.pop("min_amount", None)
        payload.pop("max_amount", None)
        regla = Rule(**payload)
        self.reglas.agregar(regla)
        self.uow.confirmar()
        self.uow.refrescar(regla)
        return regla

    def editar_regla(self, regla_id: int, payload: dict) -> Rule:
        regla = self.reglas.obtener(regla_id)
        if not regla:
            raise NoEncontrado("Regla no encontrada")
        if "min_amount" in payload:
            regla.min_amount_cents = (
                to_cents(payload.pop("min_amount")) if payload["min_amount"] else None
            )
        if "max_amount" in payload:
            regla.max_amount_cents = (
                to_cents(payload.pop("max_amount")) if payload["max_amount"] else None
            )
        payload.pop("min_amount", None)
        payload.pop("max_amount", None)
        for k, v in payload.items():
            setattr(regla, k, v)
        self.reglas.agregar(regla)
        self.uow.confirmar()
        self.uow.refrescar(regla)
        return regla

    def borrar_regla(self, regla_id: int) -> None:
        regla = self.reglas.obtener(regla_id)
        if not regla:
            raise NoEncontrado("Regla no encontrada")
        self.reglas.borrar(regla)
        self.uow.confirmar()
