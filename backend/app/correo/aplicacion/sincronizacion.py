"""Casos de uso de la ingesta: buzon -> correo archivado -> parser -> movimiento.

Es idempotente de punta a punta. Puedes re-sincronizar la misma ventana mil
veces: los correos ya vistos se saltan por gmail_id y los movimientos por su huella
(modulo movimientos, aplicacion/registro.py).
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.compartido import reloj
from app.compartido.corte import FECHA_INICIO_AUTOMATIZADO
from app.compartido.puertos import UnidadDeTrabajo
from app.compartido.tipos import Source, TxStatus
from app.correo.aplicacion.puertos import (
    ArchivoDeCorreos,
    CatalogoDePatrones,
    Clasificador,
    CuentasActivas,
    EstadoDeSincronizacion,
    FuenteDeCorreos,
    FuenteNoConfigurada,
    MemoriaDelTitular,
    RegistroDeMovimientos,
)
from app.correo.dominio import dinero_propio
from app.correo.dominio.correo import ParsedTx, RawEmail
from app.correo.dominio.entidades import EmailMessage, ParseStatus
from app.correo.dominio.lectura import (
    ANIO_PRIMER_CORREO,
    MAX_CUERPO,
    NOTAS_SIN_MOVIMIENTO,
    apartar_dinero_propio,
    como_correo,
    contexto_de_clasificacion,
    correo_archivado,
    recibido_antes_del_corte,
    resolver_cuenta,
    revisar_si_otra_moneda,
    transaccion_desde_correo,
    vaciar_cuerpo,
)
from app.movimientos.dominio.entidades import Transaction

log = logging.getLogger(__name__)


@dataclass
class ResultadoSync:
    correos_leidos: int = 0
    correos_nuevos: int = 0
    transacciones_creadas: int = 0
    por_revisar: int = 0
    duplicados: int = 0
    sin_parser: int = 0
    errores: list[str] = field(default_factory=list)
    ejecutado_en: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class AjustesDeCorreo:
    zona: ZoneInfo
    moneda_base: str
    dias_por_defecto: int            # ventana de la sincronizacion automatica
    retencion_dias: int              # 0 = no vaciar nunca el texto de los correos


class ServicioSincronizacion:
    def __init__(
        self,
        *,
        archivo: ArchivoDeCorreos,
        fuente: FuenteDeCorreos,
        patrones: CatalogoDePatrones,
        cuentas: CuentasActivas,
        titular: MemoriaDelTitular,
        estado: EstadoDeSincronizacion,
        clasificador: Clasificador,
        registro: RegistroDeMovimientos,
        uow: UnidadDeTrabajo,
        ajustes: AjustesDeCorreo,
    ):
        self.archivo = archivo
        self.fuente = fuente
        self.patrones = patrones
        self.cuentas = cuentas
        self.titular = titular
        self.estado = estado
        self.clasificador = clasificador
        self.registro = registro
        self.uow = uow
        self.ajustes = ajustes

    # ------------------------------------------------------------ construccion
    def construir_transaccion(
        self, parsed: ParsedTx, *, source: Source, email: EmailMessage | None = None,
    ) -> Transaction:
        cuenta = resolver_cuenta(self.cuentas.activas(), parsed)
        tx = transaccion_desde_correo(
            parsed, cuenta=cuenta, email=email, source=source,
            zona=self.ajustes.zona, ahora=reloj.ahora_en(self.ajustes.zona),
        )
        apartar_dinero_propio(tx, parsed, email, self.titular.leer)
        self.clasificador.aplicar(tx, contexto_de_clasificacion(email, cuenta, parsed))
        revisar_si_otra_moneda(tx, self.ajustes.moneda_base)
        return tx

    # ----------------------------------------------------------------- ingesta
    def ingerir(self, raw: RawEmail, resultado: ResultadoSync) -> None:
        if raw.received_at and raw.received_at.year < ANIO_PRIMER_CORREO:
            return

        existente = self.archivo.por_gmail_id(raw.gmail_id)
        if existente:
            # Ya se decidio que este correo no genera movimiento (NOTAS_SIN_MOVIMIENTO).
            if existente.parse_status == ParseStatus.parseado and existente.error:
                return
            tiene_tx = self.archivo.tiene_movimiento(existente.id)
            # Solo re-crear el movimiento si no lo tiene Y el correo es posterior a la
            # frontera (hasta entonces la fuente de verdad unica es el Excel).
            fecha_msg = existente.received_at.date() if existente.received_at else None
            if not tiene_tx and raw.body and fecha_msg and fecha_msg >= FECHA_INICIO_AUTOMATIZADO:
                if not existente.body_text:
                    existente.body_text = raw.body[:MAX_CUERPO]
                parsed, _motivo = self.patrones.leer(raw)
                if parsed:
                    existente.parse_status = ParseStatus.parseado
                    existente.parser = parsed.parser
                    existente.error = None
                    self.archivo.agregar(existente)
                    self.uow.confirmar()
                    tx = self.construir_transaccion(parsed, source=Source.gmail, email=existente)
                    self._anotar_desenlace(existente, self._guardar(tx, resultado))
            return

        resultado.correos_nuevos += 1
        parsed, motivo = self.patrones.leer(raw)

        email = correo_archivado(raw, parsed, motivo)
        self.archivo.agregar(email)
        self.uow.confirmar()
        self.uow.refrescar(email)

        if not parsed:
            resultado.sin_parser += 1
            return

        # Hasta la frontera el Excel es la fuente de verdad unica. Los correos
        # anteriores se quedan archivados, pero no generan movimiento.
        if recibido_antes_del_corte(raw.received_at):
            self._anotar_desenlace(email, "corte")
            return

        tx = self.construir_transaccion(parsed, source=Source.gmail, email=email)
        self._anotar_desenlace(email, self._guardar(tx, resultado))

    def _anotar_desenlace(self, email: EmailMessage, desenlace: str) -> None:
        nota = NOTAS_SIN_MOVIMIENTO.get(desenlace)
        if nota and email.error != nota:
            email.error = nota
            self.archivo.agregar(email)
            self.uow.confirmar()

    def _guardar(self, tx: Transaction, resultado: ResultadoSync) -> str:
        """Registra el movimiento con los filtros antiduplicado del modulo movimientos y
        anota el desenlace en el resultado de la sincronizacion."""
        desenlace = self.registro.registrar(tx)
        if desenlace in ("duplicado", "mellizo"):
            resultado.duplicados += 1
        elif desenlace in ("creado", "reaplicado"):
            resultado.transacciones_creadas += 1
            if desenlace == "creado" and tx.status == TxStatus.por_revisar:
                resultado.por_revisar += 1
        return desenlace

    def aprender_titular(self, cuerpos: Iterable[str]) -> list[str]:
        """El nombre completo del titular, una sola vez: si ya se aprendio, no se toca.

        Se hace ANTES de clasificar ninguno, sobre toda la tanda (ver
        dinero_propio.mejor_nombre_completo).
        """
        guardado = self.titular.leer()
        if guardado:
            return guardado
        mejor = dinero_propio.mejor_nombre_completo(cuerpos)
        if mejor:
            self.titular.guardar(mejor)
        return mejor

    # ---------------------------------------------------------- sincronizacion
    def sincronizar(self, dias: int | None = None, max_correos: int = 300) -> ResultadoSync:
        resultado = ResultadoSync()
        dias = dias or self.ajustes.dias_por_defecto
        query = ""

        try:
            correos, query = self.fuente.descargar(dias, max_correos)
        except FuenteNoConfigurada as exc:
            resultado.errores.append(str(exc))
            return resultado
        except Exception as exc:  # noqa: BLE001
            log.exception("fallo la sincronizacion por %s", self.fuente.canal)
            resultado.errores.append(f"Error de {self.fuente.canal}: {exc}")
            return resultado

        resultado.correos_leidos = len(correos)
        # Aprender el nombre del titular ANTES de clasificar nada: si se hiciera
        # sobre la marcha, los correos procesados antes del primero que lo dice se
        # quedarian sin el y el resultado dependeria del orden de la bandeja.
        self.aprender_titular(c.body for c in correos)
        for raw in correos:
            try:
                self.ingerir(raw, resultado)
            except Exception as exc:  # noqa: BLE001
                self.uow.deshacer()
                log.exception("error procesando %s", raw.gmail_id)
                resultado.errores.append(f"{raw.subject[:60]}: {exc}")

        self.purgar_cuerpos_antiguos()
        self.estado.anotar("ultima_sync", resultado.ejecutado_en.isoformat())
        self.estado.anotar("ultima_query", query)
        return resultado

    def reparsear_pendientes(self, limite: int = 5000) -> ResultadoSync:
        """Vuelve a intentar los correos guardados que ningun parser reconocio.

        Se usa despues de editar patterns.yaml: no hay que volver a bajar nada.

        El tope era de 500 y la ruta no lo decia: con 626 correos archivados, pulsar
        "Re-parsear pendientes" una vez dejaba 126 sin tocar y el resultado no daba
        ninguna pista de que faltaran. Ahora entra el archivo entero de una vez.
        """
        resultado = ResultadoSync()
        pendientes = self.archivo.sin_parser(limite)

        resultado.correos_leidos = len(pendientes)
        # Igual que en la sincronizacion: el nombre del titular se aprende de toda la
        # tanda antes de clasificar, no correo a correo.
        self.aprender_titular(e.body_text for e in pendientes)
        for email in pendientes:
            try:
                parsed, motivo = self.patrones.leer(como_correo(email))
                if not parsed:
                    email.error = motivo
                    resultado.sin_parser += 1
                else:
                    # El estado del correo se confirma junto con su movimiento. Antes se
                    # anotaba despues y quedaba sin confirmar: si fallaba el correo
                    # siguiente, el rollback dejaba este con el movimiento creado pero
                    # marcado todavia como sin parser.
                    email.parse_status = ParseStatus.parseado
                    email.parser = parsed.parser
                    email.error = None
                    if recibido_antes_del_corte(email.received_at):
                        desenlace = "corte"          # igual que en la sincronizacion
                    else:
                        tx = self.construir_transaccion(parsed, source=Source.gmail, email=email)
                        # La MISMA cadena que usa la sincronizacion. Antes habia aqui
                        # una copia simplificada, se quedo sin la deteccion de mellizos,
                        # y el re-parseo volvia a duplicar los retiros del BBVA.
                        desenlace = self._guardar(tx, resultado)
                    email.error = NOTAS_SIN_MOVIMIENTO.get(desenlace)
                self.archivo.agregar(email)
                self.uow.confirmar()
            except Exception as exc:  # noqa: BLE001
                # Igual que en la sincronizacion: un correo raro no puede tumbar el
                # lote entero. Sin esto, el fallo del correo 400 dejaba los otros 600
                # a medio procesar y devolvia un 500 sin decir cual fue.
                self.uow.deshacer()
                log.exception("error re-parseando %s", email.gmail_id)
                resultado.errores.append(f"{(email.subject or '')[:60]}: {exc}")
        self.uow.confirmar()
        return resultado

    def purgar_cuerpos_antiguos(self, dias: int | None = None) -> int:
        """Vacia el texto de los correos mas viejos de N dias.

        Se conserva la ficha (gmail_id, remitente, asunto, fecha) porque es lo que
        impide reprocesar el mismo correo dos veces; lo que se borra es el contenido,
        que es lo sensible. Sin esto, la base acumula para siempre un archivo
        completo de tus notificaciones bancarias.
        """
        dias = self.ajustes.retencion_dias if dias is None else dias
        if dias <= 0:
            return 0

        # `received_at` se guarda SIN zona y en hora local (asi lo dejan tanto el
        # cliente IMAP como el de la API de Gmail). Restar los dias sobre UTC hacia
        # que la purga se comparara contra un limite cinco horas adelantado.
        limite = reloj.ahora_en(self.ajustes.zona).replace(tzinfo=None) - timedelta(days=dias)
        antiguos = self.archivo.con_cuerpo_antes_de(limite)
        for correo in antiguos:
            vaciar_cuerpo(correo)
            self.archivo.agregar(correo)
        if antiguos:
            self.uow.confirmar()
            log.info("purga de correos: %s cuerpos vaciados (>%s dias)", len(antiguos), dias)
        return len(antiguos)

    # ---------------------------------------------------------------- consultas
    def listar_correos(self, estado: ParseStatus | None, limite: int) -> list[EmailMessage]:
        return self.archivo.listar(estado, limite)

    def ver_correo(self, correo_id: int) -> EmailMessage | None:
        return self.archivo.obtener(correo_id)
