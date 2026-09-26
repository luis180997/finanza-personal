"""Casos de uso sobre los movimientos: registrar, corregir, borrar y consultar."""
from __future__ import annotations

from zoneinfo import ZoneInfo

from app.compartido import reloj
from app.compartido.errores import NoEncontrado
from app.compartido.puertos import UnidadDeTrabajo
from app.compartido.tipos import Necessity, PaymentMethod, TxStatus
from app.movimientos.aplicacion.puertos import (
    CatalogoDeCategorias,
    Clasificador,
    FiltrosMovimientos,
    PaginaDeMovimientos,
    RepositorioCuentas,
    RepositorioMovimientos,
)
from app.movimientos.dominio.entidades import Transaction
from app.movimientos.dominio.movimiento import (
    MEDIO_POR_TIPO,
    a_hora_local,
    alta_manual,
    aplicar_lote,
    confirmar_correccion,
    corregir,
    descartar,
    desproteger_para_borrar,
    hereda_necesidad,
    proteger,
    quitar_categoria,
    se_borra_de_verdad,
    soltar_duplicado,
)


class ServicioMovimientos:
    def __init__(
        self,
        repo: RepositorioMovimientos,
        cuentas: RepositorioCuentas,
        categorias: CatalogoDeCategorias,
        clasificador: Clasificador,
        uow: UnidadDeTrabajo,
        zona: ZoneInfo,
    ):
        self.repo = repo
        self.cuentas = cuentas
        self.categorias = categorias
        self.clasificador = clasificador
        self.uow = uow
        self.zona = zona

    # ------------------------------------------------------------------ apoyo
    def _exigir_que_existan(self, category_id: int | None, *cuentas: int | None) -> None:
        """Una categoria o cuenta que no existe rompia la clave foranea al guardar y
        devolvia un 500 sin explicacion."""
        if category_id is not None and not self.categorias.obtener(category_id):
            raise NoEncontrado(f"La categoria {category_id} no existe")
        for cuenta_id in cuentas:
            if cuenta_id is not None and not self.cuentas.obtener(cuenta_id):
                raise NoEncontrado(f"La cuenta {cuenta_id} no existe")

    def _medio_por_defecto(self, cuenta_id: int | None) -> PaymentMethod | None:
        if cuenta_id is None:
            return None
        cuenta = self.cuentas.obtener(cuenta_id)
        return MEDIO_POR_TIPO.get(cuenta.type) if cuenta else None

    def mapas(self) -> tuple[dict, dict]:
        """Cuentas y categorias por id: lo que hace falta para mostrar un movimiento."""
        return self.cuentas.todas(), self.categorias.todas()

    # --------------------------------------------------------------- consultas
    def listar(
        self, filtros: FiltrosMovimientos, pagina: int, tamano: int, orden: str,
    ) -> PaginaDeMovimientos:
        return self.repo.pagina(filtros, pagina, tamano, orden)

    def por_revisar(self, limite: int) -> list[Transaction]:
        """Bandeja de entrada: lo que el sistema no supo clasificar con seguridad."""
        return self.repo.por_revisar(limite)

    # ----------------------------------------------------------------- altas
    def registrar_manual(self, alta: dict) -> Transaction:
        """Alta manual. Es la puerta de entrada de los gastos en efectivo."""
        local = a_hora_local(alta["occurred_at"] or reloj.ahora_en(self.zona), self.zona)

        cuenta_id = alta["account_id"]
        if cuenta_id is None:
            efectivo = self.cuentas.efectivo()
            cuenta_id = efectivo.id if efectivo else None
        self._exigir_que_existan(alta["category_id"], cuenta_id, alta["counter_account_id"])

        tx = alta_manual(
            alta, local=local, cuenta_id=cuenta_id,
            medio=alta["payment_method"] or self._medio_por_defecto(cuenta_id),
            ahora_utc=reloj.ahora_utc(),
        )

        # Si no eligio categoria, la cascada la propone; el alta manual sigue siendo confirmada.
        if tx.category_id is None:
            self.clasificador.aplicar(tx, {})
            tx.status = TxStatus.confirmada
            tx.confidence = 1.0

        # Despues de clasificar: lo que registras tu queda protegido desde el primer
        # momento. Ningun borrado masivo ni reproceso puede llevarselo.
        proteger(tx, reloj.ahora_utc())

        self.repo.agregar(tx)
        self.uow.confirmar()
        self.uow.refrescar(tx)
        return tx

    # ------------------------------------------------------------ correcciones
    def editar(self, tx_id: int, cambios: dict) -> Transaction:
        """`cambios` trae solo los campos que mandaste."""
        tx = self.repo.obtener(tx_id)
        if not tx:
            raise NoEncontrado("Movimiento no encontrado")
        self._exigir_que_existan(cambios.get("category_id"), cambios.get("account_id"))
        categoria_elegida = cambios.get("category_id")
        estado_elegido = cambios.get("status")

        corregir(tx, cambios, self.zona)
        confirmar_correccion(tx, categoria_elegida, estado_elegido)
        if hereda_necesidad(tx, categoria_elegida, "necessity" in cambios):
            cat = self.categorias.obtener(categoria_elegida)
            if cat:
                tx.necessity = cat.default_necessity

        # Lo que corriges tu ya no lo toca ningun reproceso, regla nueva ni limpieza.
        proteger(tx, reloj.ahora_utc())

        self.repo.agregar(tx)
        self.uow.confirmar()
        self.uow.refrescar(tx)
        return tx

    def editar_lote(
        self,
        ids: list[int],
        category_id: int | None,
        necessity: Necessity | None,
        status: TxStatus | None,
    ) -> int:
        self._exigir_que_existan(category_id)
        afectados = 0
        for tx_id in ids:
            tx = self.repo.obtener(tx_id)
            if not tx:
                continue
            aplicar_lote(tx, category_id, necessity, status)
            proteger(tx, reloj.ahora_utc())
            self.repo.agregar(tx)
            afectados += 1
        self.uow.confirmar()
        return afectados

    def borrar(self, tx_id: int) -> None:
        """Borrar significa dos cosas segun de donde viene el movimiento.

        - Un registro TUYO (manual): se borra de verdad. Es tu dato y tu decision; la
          copia queda en la papelera por si fue un error.
        - Uno del banco o del Excel: se DESCARTA (queda como ignorado). Si se borrara,
          el siguiente sincronizado lo traeria de vuelta desde su correo, clasificado
          otra vez desde cero, y tu decision de quitarlo se perderia.
        """
        tx = self.repo.obtener(tx_id)
        if not tx:
            raise NoEncontrado("Movimiento no encontrado")

        if not se_borra_de_verdad(tx):
            descartar(tx, reloj.ahora_utc())
            self.repo.agregar(tx)
            self.uow.confirmar()
            return

        # Otro movimiento puede estar marcado como duplicado de este. Como
        # duplicate_of_id es una clave foranea a la propia tabla y SQLite tiene las
        # foraneas activas, borrarlo sin soltar antes esa referencia devolvia un 500.
        for otro in self.repo.duplicados_de(tx_id):
            soltar_duplicado(otro, tx_id)
            self.repo.agregar(otro)
        self.uow.confirmar()

        desproteger_para_borrar(tx)
        self.repo.agregar(tx)
        self.uow.volcar()           # el trigger tiene que ver la proteccion ya quitada
        self.repo.borrar(tx)
        self.uow.confirmar()

    # ------------------------------------------- para el modulo de clasificacion
    def protegidos_en_categoria(self, cat_id: int) -> int:
        return sum(1 for tx in self.repo.de_categoria(cat_id) if tx.locked_by_user)

    def soltar_categoria(self, cat_id: int, destino_id: int | None) -> None:
        """La categoria se borra: sus movimientos pasan a `destino_id` o se quedan
        sin categoria. No confirma: lo hace quien borra la categoria."""
        for tx in self.repo.de_categoria(cat_id):
            quitar_categoria(tx, destino_id)
            self.repo.agregar(tx)
