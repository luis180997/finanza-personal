"""Los lotes de importacion sobre SQLite."""
from __future__ import annotations

from sqlmodel import Session, col, select

from app.excel.dominio.entidades import ImportBatch


class LotesSqlite:
    def __init__(self, session: Session):
        self.session = session

    def agregar(self, lote: ImportBatch) -> None:
        self.session.add(lote)

    def obtener(self, lote_id: int) -> ImportBatch | None:
        return self.session.get(ImportBatch, lote_id)

    def recientes(self) -> list[ImportBatch]:
        return list(self.session.exec(
            select(ImportBatch).order_by(col(ImportBatch.created_at).desc())
        ).all())

    def borrar(self, lote: ImportBatch) -> None:
        self.session.delete(lote)
