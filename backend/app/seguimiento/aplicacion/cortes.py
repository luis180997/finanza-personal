"""Casos de uso de Seguimiento: cortes de saldo real y su comparacion con lo registrado."""
from __future__ import annotations

from datetime import date

from app.compartido import reloj
from app.compartido.errores import Conflicto, NoEncontrado
from app.compartido.puertos import UnidadDeTrabajo
from app.seguimiento.aplicacion.puertos import LectorDeLibro, RepositorioCortes, TotalesRegistrados
from app.seguimiento.dominio.conciliacion import (
    LecturaExcel,
    Saldo,
    actualizar_corte,
    cuentas_sugeridas,
    leer_libro,
    proyeccion,
    resumen,
    saldos_de,
    serie,
)
from app.seguimiento.dominio.entidades import SaldoCorte


class ServicioSeguimiento:
    def __init__(
        self,
        cortes: RepositorioCortes,
        registrado: TotalesRegistrados,
        lector: LectorDeLibro,
        uow: UnidadDeTrabajo,
    ):
        self.cortes = cortes
        self.registrado = registrado
        self.lector = lector
        self.uow = uow

    def ver(self) -> dict:
        filas = serie(self.cortes.por_fecha(), self.cortes.saldos_por_corte(), self.registrado.entre)
        return {
            "cortes": filas,
            "resumen": resumen(filas),
            "cuentas_sugeridas": cuentas_sugeridas(filas),
            "proyeccion": proyeccion(filas),
        }

    def _guardar(
        self,
        corte: SaldoCorte,
        *,
        fecha: date,
        tipo_cambio_diezmil: int,
        notas: str | None,
        saldos: list[Saldo],
        origen: str | None = None,
    ) -> SaldoCorte:
        """Crea o reemplaza un corte con sus saldos, en una sola transaccion."""
        actualizar_corte(
            corte, fecha=fecha, tipo_cambio_diezmil=tipo_cambio_diezmil, notas=notas,
            origen=origen, ahora=reloj.ahora_utc(),
        )
        self.cortes.agregar(corte)
        self.uow.volcar()
        for viejo in self.cortes.saldos_de(corte.id):
            self.cortes.borrar(viejo)
        self.uow.volcar()
        for nuevo in saldos_de(corte.id, saldos):
            self.cortes.agregar(nuevo)
        self.uow.confirmar()
        self.uow.refrescar(corte)
        return corte

    def crear(
        self, *, fecha: date, tipo_cambio_diezmil: int, notas: str | None, saldos: list[Saldo],
    ) -> SaldoCorte:
        if self.cortes.en_fecha(fecha):
            raise Conflicto(f"Ya hay un corte del {fecha:%d/%m/%Y}. Editalo en vez de crear otro.")
        return self._guardar(
            SaldoCorte(), fecha=fecha, tipo_cambio_diezmil=tipo_cambio_diezmil,
            notas=notas, saldos=saldos, origen="manual",
        )

    def editar(
        self, corte_id: int, *, fecha: date, tipo_cambio_diezmil: int, notas: str | None,
        saldos: list[Saldo],
    ) -> SaldoCorte:
        corte = self.cortes.obtener(corte_id)
        if not corte:
            raise NoEncontrado("Corte no encontrado")
        if self.cortes.en_fecha(fecha, excluir_id=corte_id):
            raise Conflicto(f"Ya hay otro corte del {fecha:%d/%m/%Y}.")
        return self._guardar(
            corte, fecha=fecha, tipo_cambio_diezmil=tipo_cambio_diezmil, notas=notas, saldos=saldos,
        )

    def borrar(self, corte_id: int) -> None:
        corte = self.cortes.obtener(corte_id)
        if not corte:
            raise NoEncontrado("Corte no encontrado")
        for s in self.cortes.saldos_de(corte.id):
            self.cortes.borrar(s)
        self.uow.volcar()
        self.cortes.borrar(corte)
        self.uow.confirmar()

    def leer_excel(self, contenido: bytes, hoja: str | None = None) -> LecturaExcel:
        """Lee el historial de saldos de un Excel. No escribe nada."""
        return leer_libro(self.lector.abrir(contenido), hoja)

    def importar(self, lectura: LecturaExcel) -> dict:
        """Guarda los cortes leidos. Una fecha que ya existe no se toca ni se duplica."""
        existentes = self.cortes.fechas()
        creados = ya_existian = 0
        for c in lectura.cortes:
            if c.fecha in existentes:
                ya_existian += 1
                continue
            self._guardar(
                SaldoCorte(), fecha=c.fecha, tipo_cambio_diezmil=c.tipo_cambio_diezmil,
                notas=None, saldos=c.saldos, origen="excel",
            )
            existentes.add(c.fecha)
            creados += 1
        return {
            "hoja": lectura.hoja,
            "leidos": len(lectura.cortes),
            "creados": creados,
            "ya_existian": ya_existian,
            "avisos": lectura.avisos,
        }
