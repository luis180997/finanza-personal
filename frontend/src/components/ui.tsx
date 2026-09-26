/** Piezas de interfaz reutilizables. Todo en HTML plano + Tailwind. */
import type { ReactNode } from "react";
import { AlertTriangle, Info, Loader2, TrendingDown, TrendingUp } from "lucide-react";
import { pct } from "../lib/format";

export function Tarjeta({
  titulo,
  subtitulo,
  acciones,
  children,
  className = "",
}: {
  titulo?: string;
  subtitulo?: string;
  acciones?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`rounded-xl border bg-[var(--superficie)] ${className}`}
      style={{ borderColor: "var(--borde)" }}
    >
      {(titulo || acciones) && (
        <header className="flex items-start justify-between gap-3 px-4 pt-4 pb-2">
          <div className="min-w-0">
            {titulo && <h2 className="text-sm font-semibold text-[var(--tinta)]">{titulo}</h2>}
            {subtitulo && (
              <p className="mt-0.5 text-xs text-[var(--tinta-3)]">{subtitulo}</p>
            )}
          </div>
          {acciones && <div className="shrink-0">{acciones}</div>}
        </header>
      )}
      <div className="p-4 pt-2">{children}</div>
    </section>
  );
}

/**
 * Cifra destacada. Sin grafico: cuando el dato es un solo numero, un numero
 * es mejor que un grafico.
 */
export function Indicador({
  etiqueta,
  valor,
  detalle,
  variacion,
  variacionBuenaSiBaja = false,
  acento,
}: {
  etiqueta: string;
  valor: string;
  detalle?: string;
  variacion?: number | null;
  variacionBuenaSiBaja?: boolean;
  acento?: string;
}) {
  const sube = (variacion ?? 0) > 0;
  const esBuena = variacionBuenaSiBaja ? !sube : sube;
  const hayVariacion = variacion !== null && variacion !== undefined;

  return (
    <div
      className="rounded-xl border bg-[var(--superficie)] p-4"
      style={{ borderColor: "var(--borde)" }}
    >
      <div className="flex items-center gap-2">
        {acento && (
          <span
            aria-hidden
            className="h-2.5 w-2.5 shrink-0 rounded-full"
            style={{ background: acento }}
          />
        )}
        <span className="text-xs font-medium text-[var(--tinta-2)]">{etiqueta}</span>
      </div>
      <div className="mt-2 text-2xl font-semibold tracking-tight text-[var(--tinta)]">
        {valor}
      </div>
      <div className="mt-1 flex items-center gap-2 text-xs">
        {hayVariacion && (
          <span
            className="inline-flex items-center gap-1 font-medium"
            style={{ color: esBuena ? "var(--texto-bien)" : "var(--texto-malo)" }}
          >
            {sube ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
            {pct(variacion)}
          </span>
        )}
        {detalle && <span className="text-[var(--tinta-3)]">{detalle}</span>}
      </div>
    </div>
  );
}

export function Boton({
  children,
  variante = "secundario",
  className = "",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variante?: "primario" | "secundario" | "fantasma" | "peligro";
}) {
  const base =
    "inline-flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50";
  const estilos: Record<string, string> = {
    primario: "text-white hover:brightness-110",
    secundario: "border hover:bg-[var(--superficie-2)]",
    fantasma: "hover:bg-[var(--superficie-2)] text-[var(--tinta-2)]",
    peligro: "border hover:bg-[var(--superficie-2)]",
  };
  const inline: React.CSSProperties =
    variante === "primario"
      ? { background: "var(--serie-1)" }
      : variante === "peligro"
        ? { borderColor: "var(--borde)", color: "var(--critico)" }
        : { borderColor: "var(--borde)" };

  return (
    <button className={`${base} ${estilos[variante]} ${className}`} style={inline} {...props}>
      {children}
    </button>
  );
}

export function Campo({
  etiqueta,
  hint,
  children,
}: {
  etiqueta: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-[var(--tinta-2)]">{etiqueta}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-[var(--tinta-3)]">{hint}</span>}
    </label>
  );
}

const claseControl =
  "w-full rounded-lg border bg-[var(--superficie)] px-3 py-2 text-sm outline-none placeholder:text-[var(--tinta-3)]";

export function Entrada(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={`${claseControl} ${props.className ?? ""}`}
      style={{ borderColor: "var(--borde)", ...props.style }}
    />
  );
}

export function AreaTexto(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      {...props}
      className={`${claseControl} ${props.className ?? ""}`}
      style={{ borderColor: "var(--borde)", ...props.style }}
    />
  );
}

export function Selector(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...props}
      className={`${claseControl} ${props.className ?? ""}`}
      style={{ borderColor: "var(--borde)", ...props.style }}
    />
  );
}

export function Etiqueta({
  children,
  color,
  titulo,
}: {
  children: ReactNode;
  color?: string;
  titulo?: string;
}) {
  return (
    <span
      title={titulo}
      className="inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium whitespace-nowrap"
      style={{ borderColor: "var(--borde)", color: "var(--tinta-2)" }}
    >
      {color && (
        <span
          aria-hidden
          className="h-2 w-2 shrink-0 rounded-full"
          style={{ background: color }}
        />
      )}
      {children}
    </span>
  );
}

/** Necesidad: color de estado + texto. El color nunca va solo. */
export function SelloNecesidad({ valor }: { valor: string | null }) {
  if (!valor) return <span className="text-xs text-[var(--tinta-3)]">—</span>;
  const mapa: Record<string, { texto: string; color: string }> = {
    esencial: { texto: "Esencial", color: "var(--bien)" },
    discrecional: { texto: "Discrecional", color: "var(--aviso)" },
    evitable: { texto: "Evitable", color: "var(--critico)" },
  };
  const item = mapa[valor];
  if (!item) return <span className="text-xs text-[var(--tinta-3)]">—</span>;
  return <Etiqueta color={item.color}>{item.texto}</Etiqueta>;
}

export function Cargando({ texto = "Cargando…" }: { texto?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-12 text-sm text-[var(--tinta-3)]">
      <Loader2 size={16} className="animate-spin" />
      {texto}
    </div>
  );
}

export function Vacio({ titulo, detalle }: { titulo: string; detalle?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-1 py-12 text-center">
      <Info size={20} className="text-[var(--tinta-3)]" />
      <p className="text-sm font-medium text-[var(--tinta-2)]">{titulo}</p>
      {detalle && <p className="max-w-sm text-xs text-[var(--tinta-3)]">{detalle}</p>}
    </div>
  );
}

export function Aviso({
  children,
  tono = "info",
}: {
  children: ReactNode;
  tono?: "info" | "aviso" | "critico";
}) {
  const colores = {
    info: "var(--serie-1)",
    aviso: "var(--aviso)",
    critico: "var(--critico)",
  } as const;
  return (
    <div
      className="flex items-start gap-2 rounded-lg border p-3 text-sm"
      style={{ borderColor: "var(--borde)", background: "var(--superficie-2)" }}
    >
      <AlertTriangle size={16} className="mt-0.5 shrink-0" style={{ color: colores[tono] }} />
      <div className="min-w-0 text-[var(--tinta-2)]">{children}</div>
    </div>
  );
}
