"""Caso de uso: clasificar un movimiento recorriendo la cascada de capas."""
from __future__ import annotations

from app.clasificacion.aplicacion.puertos import (
    CatalogoCategorias,
    MemoriaDeComercios,
    RepositorioReglas,
)
from app.clasificacion.dominio import diccionario, reglas
from app.clasificacion.dominio.clasificador import (
    Clasificacion,
    aplicar_resultado,
    categoria_por_defecto,
    de_un_protegido,
    por_memoria,
    por_regla,
    sin_clasificar,
    texto_para_diccionario,
)
from app.compartido.tipos import Direction
from app.movimientos.dominio.entidades import Transaction


class ServicioClasificacion:
    def __init__(
        self,
        categorias: CatalogoCategorias,
        reglas_: RepositorioReglas,
        memoria: MemoriaDeComercios,
    ):
        self.categorias = categorias
        self.reglas = reglas_
        self.memoria = memoria

    # ------------------------------------------------------------------ capas
    def _por_reglas(self, tx: Transaction, contexto: dict) -> Clasificacion | None:
        regla = reglas.primera_que_aplica(self.reglas.activas_por_prioridad(), tx, contexto)
        if regla is None:
            return None
        self.reglas.registrar_acierto(regla)
        reglas.aplicar_efectos(regla, tx)
        return por_regla(regla)

    def _por_memoria(self, tx: Transaction) -> Clasificacion | None:
        """La categoria que TU elegiste mas veces para este mismo comercio."""
        if not tx.merchant:
            return None
        fila = self.memoria.mas_usada(tx.merchant, excluir_id=tx.id)
        if not fila:
            return None
        category_id, necessity, veces = fila
        return por_memoria(category_id, necessity, veces)

    def _por_diccionario(self, tx: Transaction) -> Clasificacion | None:
        objetivo = texto_para_diccionario(tx)
        if not objetivo.strip():
            return None
        for nombre_cat, necesidad in diccionario.candidatos(objetivo):
            cat = self.categorias.por_nombre(nombre_cat)
            if cat:
                return Clasificacion(cat.id, necesidad, "diccionario", 0.85)
        return None

    # ------------------------------------------------------------------ api
    def clasificar(self, tx: Transaction, contexto: dict | None = None) -> Clasificacion:
        contexto = contexto or {}
        por_defecto = self.categorias.por_nombre(categoria_por_defecto(tx.direction))

        # Una regla puede no fijar categoria y aun asi tener algo que decir: marcar
        # el gasto como evitable, o como recurrente. Antes se descartaba entera si
        # no traia categoria, asi que esas reglas se quedaban sin efecto en silencio
        # (aunque su contador de aciertos subiera, que despistaba todavia mas).
        regla = self._por_reglas(tx, contexto)
        if regla and regla.necessity is not None and tx.necessity is None:
            tx.necessity = regla.necessity

        for capa in (
            lambda: regla,
            lambda: self._por_memoria(tx),
            lambda: self._por_diccionario(tx),
        ):
            resultado = capa()
            if resultado and resultado.category_id:
                if resultado.necessity is None:
                    cat = self.categorias.obtener(resultado.category_id)
                    resultado.necessity = cat.default_necessity if cat else None
                return resultado

        # La pista que trae el propio parser del correo. Va la ultima a proposito:
        # asi tus correcciones y tus reglas nunca quedan pisadas por el parser.
        #
        # Pero no es una conjetura. Cuando Yape dice "acabas de yapear a Fulano", que
        # el movimiento sea un pago a una persona es un hecho que afirma el correo.
        # Lo que el correo no dice nunca es *para que* fue, y eso no lo arregla
        # ninguna revision: con 0.7 estos pagos caian por debajo del umbral y
        # llenaban la bandeja con 45 movimientos que no se podian despachar. Si
        # alguno era el alquiler, se corrige una vez y la memoria de comercio lo
        # aprende, que es justo para lo que sirve la capa de memoria.
        pista = contexto.get("category_hint")
        if pista:
            cat = self.categorias.por_nombre(pista)
            if cat:
                return Clasificacion(cat.id, cat.default_necessity, "parser", 0.9)

        # "Entre cuentas propias" no es un cajon de sastre: si el correo dice que es
        # un traspaso entre tus cuentas, esa ES la categoria, y no hay nada que
        # revisar. Tratarla como fallback mandaba a la bandeja doce traspasos que el
        # propio banco ya habia identificado.
        if tx.direction == Direction.transferencia and por_defecto:
            return Clasificacion(por_defecto.id, None, "direccion", 0.95)

        return sin_clasificar(por_defecto.id if por_defecto else None)

    def aplicar(self, tx: Transaction, contexto: dict | None = None) -> Clasificacion:
        """Clasifica y decide si el movimiento necesita revision humana.

        Un movimiento protegido (lo registraste o corregiste tu) no se reclasifica
        nunca: ni una regla nueva, ni un reparseo, ni una migracion pisan tu decision.
        """
        if tx.locked_by_user:
            return de_un_protegido(tx)
        c = self.clasificar(tx, contexto)
        aplicar_resultado(tx, c)
        return c
