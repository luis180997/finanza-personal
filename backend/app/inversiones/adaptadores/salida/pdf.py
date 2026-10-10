"""El puerto `LectorDePdf` con pdfplumber.

pdfplumber da cada palabra con su caja. Se agrupan en lineas por altura y se
descarta el texto girado: el titulo vertical "ACCOUNT STATEMENT" del margen, que
si no se colaria letra a letra en las filas ("T BOUGHT", "O DIVIDEND").
"""
from __future__ import annotations

import io

from app.inversiones.dominio.estado_cuenta import Linea, Pagina, Palabra

# Palabras a menos de esta distancia vertical (puntos) son de la misma linea.
_MISMA_LINEA = 2.5


def lineas_desde_palabras(palabras: list[dict]) -> list[Linea]:
    """Agrupa las palabras de pdfplumber (dicts con text, x0, x1, top, upright)."""
    derechas = sorted(
        (w for w in palabras if w.get("upright", True)), key=lambda w: (round(w["top"]), w["x0"]),
    )
    lineas: list[tuple[float, list[Palabra]]] = []
    for w in derechas:
        palabra = Palabra(w["text"], w["x0"], w["x1"])
        if lineas and abs(lineas[-1][0] - w["top"]) <= _MISMA_LINEA:
            lineas[-1][1].append(palabra)
        else:
            lineas.append((w["top"], [palabra]))
    return [Linea(sorted(ps, key=lambda p: p.x0)) for _, ps in lineas]


class LectorPdfplumber:
    def paginas(self, contenido: bytes) -> list[Pagina]:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(contenido)) as pdf:
            return [
                Pagina(
                    numero=page.page_number,
                    lineas=lineas_desde_palabras(
                        page.extract_words(x_tolerance=1.5, y_tolerance=2, extra_attrs=["upright"])
                    ),
                )
                for page in pdf.pages
            ]
