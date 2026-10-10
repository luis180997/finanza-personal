"""Revisa en seco los estados de cuenta de Hapi (Apex) de una carpeta.

Lee cada PDF, lo valida contra sus propios totales y comprueba que los meses
encadenen. No escribe nada: ni en la base ni en disco.

    python scripts/revisar_estados_hapi.py ../data/hapi
    python scripts/revisar_estados_hapi.py ../data/hapi --detalle   # tambien los movimientos

Sale con codigo 1 si algun documento no cuadra.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.inversiones.adaptadores import fabrica  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("carpeta", type=Path)
    parser.add_argument("--detalle", action="store_true", help="lista los movimientos de cada mes")
    args = parser.parse_args()

    archivos = sorted(args.carpeta.glob("*.pdf"))
    if not archivos:
        print(f"No hay PDFs en {args.carpeta}")
        return 1
    informe = fabrica.revision().revisar((f.name, f.read_bytes()) for f in archivos)

    orden = sorted(
        informe.documentos, key=lambda d: (d.estado is None, d.estado and d.estado.inicio),
    )
    for doc in orden:
        if doc.estado is None:
            print(f"--  {doc.nombre}: {'; '.join(map(str, doc.errores))}")
            continue
        e = doc.estado
        codigos = Counter(m.codigo for m in e.movimientos)
        marca = "OK " if doc.valido else "ERR"
        print(f"{marca} {e.inicio}..{e.fin}  posiciones={len(e.posiciones):2d}  "
              f"movimientos={dict(codigos)}")
        for error in doc.errores:
            print(f"      {error}")
        if args.detalle:
            for m in e.movimientos:
                print(f"        {m.seccion.value:11s} {m.codigo:8s} {m.fecha} "
                      f"{m.descripcion[:34]:34s} q={m.cantidad} p={m.precio} "
                      f"D={m.debito_cents / 100:.2f} C={m.credito_cents / 100:.2f} "
                      f"WH={m.retencion_cents / 100:.2f}")
            for linea in e.no_reconocidas:
                print(f"        ? {linea}")

    for error in informe.errores_de_serie:
        print(f"  SERIE {error}")
    estados = informe.estados
    validos = sum(d.valido for d in informe.documentos)
    print(f"\n{validos}/{len(informe.documentos)} documentos cuadran; "
          f"{len(informe.errores_de_serie)} errores entre meses.")
    if estados:
        print(f"Periodo cubierto: {estados[0].inicio} -> {estados[-1].fin}")
    return 0 if informe.todo_cuadra else 1


if __name__ == "__main__":
    sys.exit(main())
