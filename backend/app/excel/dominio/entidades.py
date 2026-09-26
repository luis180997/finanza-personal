"""Lotes de importacion del Excel historico."""
from __future__ import annotations

from datetime import date, datetime

from sqlmodel import Field, SQLModel

from app.compartido.entidad import utcnow


class ImportBatch(SQLModel, table=True):
    """Una ejecucion del importador de Excel.

    Existe para poder DESHACER. Importar un Excel de 1353 filas sin forma de
    revertirlo es una operacion que da miedo ejecutar, y una que da miedo no se
    ejecuta. Cada movimiento importado apunta a su lote, asi que deshacer es
    borrar exactamente lo que entro y nada mas.
    """

    __tablename__ = "import_batch"

    id: int | None = Field(default=None, primary_key=True)
    filename: str
    sheet: str
    rows_read: int = 0
    created_count: int = 0
    duplicated_count: int = 0
    date_from: date | None = None
    date_to: date | None = None
    created_at: datetime = Field(default_factory=utcnow)
