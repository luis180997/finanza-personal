/** Formateo consistente en toda la app: soles, fechas y porcentajes. */

const SOLES = new Intl.NumberFormat("es-PE", {
  style: "currency",
  currency: "PEN",
  minimumFractionDigits: 2,
});

const SOLES_CORTO = new Intl.NumberFormat("es-PE", {
  style: "currency",
  currency: "PEN",
  maximumFractionDigits: 0,
});

export const soles = (v: number) => SOLES.format(v ?? 0);
export const solesCorto = (v: number) => SOLES_CORTO.format(v ?? 0);

/**
 * Importe con su moneda: "S/ 31.20" o "US$ 8.85". Un cobro en dolares escrito como
 * "S/ 8.85" se lee como soles, que es justo el error que hay que ver.
 */
export function importe(v: number, moneda?: string | null): string {
  if (!moneda || moneda === "PEN") return soles(v);
  try {
    return new Intl.NumberFormat("es-PE", {
      style: "currency",
      currency: moneda,
      minimumFractionDigits: 2,
    }).format(v ?? 0);
  } catch {
    return `${moneda} ${(v ?? 0).toFixed(2)}`;
  }
}

/**
 * "12.50", "12,50", "1,234.50", "1.234,50" o "S/ 1234". NaN si no es un numero.
 *
 * Antes solo se cambiaba la primera coma por un punto: "1,234.50" quedaba en
 * "1.234.50", que no es un numero, y el formulario no guardaba ni decia por que.
 */
export function leerMonto(texto: string): number {
  let s = texto.replace(/[^\d,.-]/g, "");
  if (s.includes(",") && s.includes(".")) {
    // El separador decimal es el que aparece al final
    s = s.lastIndexOf(".") > s.lastIndexOf(",")
      ? s.replace(/,/g, "")
      : s.replace(/\./g, "").replace(",", ".");
  } else if (s.includes(",")) {
    // Coma sola: decimal si deja una o dos cifras detras ("12,5"); si no, de miles
    const partes = s.split(",");
    s = partes.length === 2 && partes[1].length <= 2 ? s.replace(",", ".") : s.replace(/,/g, "");
  }
  return s ? Number(s) : NaN;
}

/** Para ejes: "1.2 k" en vez de "S/ 1,234.00". */
export function ejeSoles(v: number): string {
  if (Math.abs(v) >= 1000) return `${(v / 1000).toFixed(1).replace(".0", "")} k`;
  return String(Math.round(v));
}

export const pct = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(1)}%`;

/**
 * Convierte una cadena del backend en Date sin que se desplace un dia.
 *
 * `new Date("2024-03-01")` se interpreta como medianoche UTC. Al mostrarlo en
 * Lima (UTC-5) queda el 29 de febrero a las 19:00, y la fecha aparece un dia
 * antes. Anclando al mediodia local, ninguna zona horaria del mundo cruza el
 * cambio de dia. Las cadenas que ya traen hora se dejan tal cual.
 */
function aFecha(iso: string): Date {
  return /^\d{4}-\d{2}-\d{2}$/.test(iso.trim())
    ? new Date(`${iso.trim()}T12:00:00`)
    : new Date(iso);
}

export function fecha(iso: string): string {
  return aFecha(iso).toLocaleDateString("es-PE", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

export function fechaCorta(iso: string): string {
  return aFecha(iso.slice(0, 10)).toLocaleDateString("es-PE", {
    day: "2-digit",
    month: "short",
  });
}

export function fechaHora(iso: string): string {
  return new Date(iso).toLocaleString("es-PE", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * Fecha en formato ISO, siempre en TU dia, nunca en el de Greenwich.
 *
 * `toISOString()` convierte a UTC. En Peru (UTC-5) eso significa que a partir
 * de las 7 de la tarde la fecha "de hoy" ya era la de mañana, y un filtro de
 * "ultimos 7 dias" pedia un rango que terminaba en el futuro.
 */
function aISOLocal(d: Date): string {
  const anio = d.getFullYear();
  const mes = String(d.getMonth() + 1).padStart(2, "0");
  const dia = String(d.getDate()).padStart(2, "0");
  return `${anio}-${mes}-${dia}`;
}

export function hoyISO(): string {
  return aISOLocal(new Date());
}

export function primerDiaDelMes(d = new Date()): string {
  return aISOLocal(new Date(d.getFullYear(), d.getMonth(), 1));
}

export function ultimoDiaDelMes(d = new Date()): string {
  return aISOLocal(new Date(d.getFullYear(), d.getMonth() + 1, 0));
}

export function primerDiaDelAnio(d = new Date()): string {
  return aISOLocal(new Date(d.getFullYear(), 0, 1));
}

export function ultimoDiaDelAnio(d = new Date()): string {
  return aISOLocal(new Date(d.getFullYear(), 11, 31));
}

export function haceDias(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return aISOLocal(d);
}

export const ETIQUETA_NECESIDAD: Record<string, string> = {
  esencial: "Esencial",
  discrecional: "Discrecional",
  evitable: "Evitable",
};

export const ETIQUETA_ORIGEN: Record<string, string> = {
  gmail: "Correo",
  manual: "Manual",
  excel: "Excel",
};

export const ETIQUETA_ESTADO: Record<string, string> = {
  confirmada: "Confirmada",
  por_revisar: "Por revisar",
  duplicada: "Duplicada",
  ignorada: "Ignorada",
};
