"""Los puertos de correo sobre SQLite: el archivo de correos y el almacen clave-valor."""
from __future__ import annotations

from datetime import datetime

from sqlmodel import Session, col, select

from app.correo.dominio.entidades import EmailMessage, ParseStatus
from app.movimientos.dominio.entidades import Transaction
from app.plataforma import kv


class ArchivoSqlite:
    def __init__(self, session: Session):
        self.session = session

    def por_gmail_id(self, gmail_id: str) -> EmailMessage | None:
        return self.session.exec(
            select(EmailMessage).where(EmailMessage.gmail_id == gmail_id)
        ).first()

    def obtener(self, correo_id: int) -> EmailMessage | None:
        return self.session.get(EmailMessage, correo_id)

    def listar(self, estado: ParseStatus | None, limite: int) -> list[EmailMessage]:
        consulta = select(EmailMessage)
        if estado:
            consulta = consulta.where(EmailMessage.parse_status == estado)
        return list(self.session.exec(
            consulta.order_by(col(EmailMessage.received_at).desc()).limit(limite)
        ).all())

    def sin_parser(self, limite: int) -> list[EmailMessage]:
        return list(self.session.exec(
            select(EmailMessage)
            .where(EmailMessage.parse_status == ParseStatus.sin_parser)
            .limit(limite)
        ).all())

    def con_cuerpo_antes_de(self, limite: datetime) -> list[EmailMessage]:
        return list(self.session.exec(
            select(EmailMessage).where(
                EmailMessage.received_at < limite,
                EmailMessage.body_text != "",
            )
        ).all())

    def tiene_movimiento(self, correo_id: int) -> bool:
        return self.session.exec(
            select(Transaction.id).where(Transaction.email_id == correo_id)
        ).first() is not None

    def agregar(self, correo: EmailMessage) -> None:
        self.session.add(correo)


CLAVE_TITULAR = "titular_nombre"


class TitularKv:
    """El nombre del titular, en la tabla clave-valor."""

    def __init__(self, session: Session):
        self.session = session

    def leer(self) -> list[str]:
        valor = kv.leer(self.session, CLAVE_TITULAR)
        return valor.split() if valor else []

    def guardar(self, nombre: list[str]) -> None:
        kv.guardar(self.session, CLAVE_TITULAR, " ".join(nombre))


class EstadoKv:
    """Ultima sincronizacion y ultima consulta al buzon."""

    def __init__(self, session: Session):
        self.session = session

    def anotar(self, clave: str, valor: str) -> None:
        kv.guardar(self.session, clave, valor)
