"""Casos de uso de las cuentas."""
from __future__ import annotations

from app.compartido.errores import Conflicto, NoEncontrado
from app.compartido.puertos import UnidadDeTrabajo
from app.movimientos.aplicacion.puertos import RepositorioCuentas
from app.movimientos.dominio.entidades import Account


class ServicioCuentas:
    def __init__(self, cuentas: RepositorioCuentas, uow: UnidadDeTrabajo):
        self.cuentas = cuentas
        self.uow = uow

    def listar(self) -> list[Account]:
        return self.cuentas.ordenadas()

    def crear(self, campos: dict) -> Account:
        if self.cuentas.por_nombre(campos["name"]):
            raise Conflicto("Ya existe una cuenta con ese nombre")
        cuenta = Account(**campos)
        self.cuentas.agregar(cuenta)
        self.uow.confirmar()
        self.uow.refrescar(cuenta)
        return cuenta

    def editar(self, cuenta_id: int, cambios: dict) -> Account:
        """Edicion parcial: solo cambia lo que mandas. Antes exigia reenviar la cuenta
        entera, y renombrarla con el nombre de otra devolvia un 500."""
        cuenta = self.cuentas.obtener(cuenta_id)
        if not cuenta:
            raise NoEncontrado("Cuenta no encontrada")
        nombre = cambios.get("name")
        if nombre and nombre != cuenta.name and self.cuentas.por_nombre(nombre):
            raise Conflicto("Ya existe una cuenta con ese nombre")
        for k, v in cambios.items():
            setattr(cuenta, k, v)
        self.cuentas.agregar(cuenta)
        self.uow.confirmar()
        self.uow.refrescar(cuenta)
        return cuenta

    def borrar(self, cuenta_id: int) -> None:
        cuenta = self.cuentas.obtener(cuenta_id)
        if not cuenta:
            raise NoEncontrado("Cuenta no encontrada")
        if self.cuentas.tiene_movimientos(cuenta_id):
            raise Conflicto("La cuenta tiene movimientos. Desactivala en lugar de borrarla.")
        self.cuentas.borrar(cuenta)
        self.uow.confirmar()
