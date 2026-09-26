/**
 * Filtros compartidos por Panel y Tendencia.
 *
 * Dos problemas que resuelven:
 *
 *  1. El filtro vive en la URL (?periodo=...&desde=...). Sobrevive a recargar la
 *     pagina, y un enlace abre la vista exacta: el Panel puede mandar a Tendencia
 *     ya filtrada por una categoria.
 *
 *  2. Un <input type="date"> avisa en cada tecla. Al escribir el ano "2022",
 *     Chrome emite 0002, 0020, 0202 y 2022, y cada una es una fecha "valida": el
 *     panel pedia el resumen del ano 2 y mostraba "No se pudo cargar el resumen".
 *     Aqui el rango se aplica solo cuando las dos fechas estan completas, son
 *     razonables y estan en orden, y tras una pausa corta para no lanzar una
 *     consulta por tecla.
 */
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

// Los mismos limites que valida el servidor (routes/resumen.py).
export const ANIO_MIN = 2000;
export const ANIO_MAX = 2100;

export function fechaValida(iso: string | null | undefined): iso is string {
  if (!iso || !/^\d{4}-\d{2}-\d{2}$/.test(iso)) return false;
  const [a, m, d] = iso.split("-").map(Number);
  if (a < ANIO_MIN || a > ANIO_MAX) return false;
  const f = new Date(a, m - 1, d);
  return f.getFullYear() === a && f.getMonth() === m - 1 && f.getDate() === d;
}

/**
 * Parametros de la URL con su valor por defecto. Guardar el valor por defecto lo
 * quita de la URL, para que quede limpia. Reemplaza la entrada del historial en
 * vez de apilar una por cada cambio de filtro.
 */
export function useParametros<T extends Record<string, string>>(defecto: T) {
  const [params, setParams] = useSearchParams();
  const valores = Object.fromEntries(
    Object.entries(defecto).map(([k, v]) => [k, params.get(k) ?? v]),
  ) as T;

  function cambiar(cambios: Partial<T>) {
    setParams(
      (previos) => {
        const nuevos = new URLSearchParams(previos);
        for (const [k, v] of Object.entries(cambios)) {
          if (v === undefined || v === "" || v === defecto[k]) nuevos.delete(k);
          else nuevos.set(k, String(v));
        }
        return nuevos;
      },
      { replace: true },
    );
  }

  return [valores, cambiar] as const;
}

export function CamposRango({
  desde,
  hasta,
  onAplicar,
}: {
  desde: string;
  hasta: string;
  onAplicar: (rango: { desde: string; hasta: string }) => void;
}) {
  const [borrador, setBorrador] = useState({ desde, hasta });
  const aplicar = useRef(onAplicar);
  aplicar.current = onAplicar;

  // Si el rango cambia desde fuera (otro preset, un enlace), el borrador lo sigue.
  useEffect(() => setBorrador({ desde, hasta }), [desde, hasta]);

  const completo = fechaValida(borrador.desde) && fechaValida(borrador.hasta);
  const invertido = completo && borrador.desde > borrador.hasta;
  const pendiente = borrador.desde !== desde || borrador.hasta !== hasta;

  useEffect(() => {
    if (!completo || invertido || !pendiente) return;
    const t = setTimeout(() => aplicar.current(borrador), 400);
    return () => clearTimeout(t);
  }, [borrador, completo, invertido, pendiente]);

  return (
    <div className="mb-5 flex flex-wrap items-end gap-3">
      {(["desde", "hasta"] as const).map((cual) => (
        <label key={cual} className="text-xs capitalize text-[var(--tinta-3)]">
          {cual}
          <input
            type="date"
            value={borrador[cual]}
            min={`${ANIO_MIN}-01-01`}
            max={`${ANIO_MAX}-12-31`}
            onChange={(e) => setBorrador((b) => ({ ...b, [cual]: e.target.value }))}
            className="mt-1 block w-40 rounded-md border bg-transparent px-2 py-1.5 text-sm text-[var(--tinta)] outline-none"
            style={{ borderColor: "var(--borde)" }}
          />
        </label>
      ))}
      {invertido ? (
        <p className="text-xs" style={{ color: "var(--critico)" }}>
          La fecha inicial es posterior a la final.
        </p>
      ) : !completo ? (
        <p className="text-xs text-[var(--tinta-3)]">
          Completa las dos fechas (años {ANIO_MIN} a {ANIO_MAX}).
        </p>
      ) : null}
    </div>
  );
}
