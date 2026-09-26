/**
 * Graficos del panel.
 *
 * Reglas que se respetan aqui (y que conviene no romper al editar):
 *   - Un solo eje de valor por grafico. Nunca dos escalas Y.
 *   - El color identifica a la entidad (la categoria trae su hex del backend),
 *     nunca al puesto en el ranking: filtrar no debe repintar las que quedan.
 *   - Toda serie tiene etiqueta de texto ademas de color: el color nunca carga
 *     el significado solo (daltonismo, impresion en blanco y negro).
 *   - Marcas finas, rejilla discreta, extremo de la barra redondeado 4px.
 */
import { useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  Legend,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Table2 } from "lucide-react";
import type { Corte, PuntoDiario, PuntoMensual, PuntoPeriodo } from "../lib/api";
import { ejeSoles, fechaCorta, soles } from "../lib/format";
import { Vacio } from "./ui";

const EJE = { fontSize: 11, fill: "var(--tinta-3)" };

function CajaTooltip({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="rounded-lg border px-3 py-2 text-xs shadow-lg"
      style={{
        background: "var(--superficie)",
        borderColor: "var(--borde-fuerte)",
        color: "var(--tinta)",
      }}
    >
      {children}
    </div>
  );
}

/**
 * Recharts tipa el payload del tooltip de forma muy laxa (ValueType/NameType),
 * asi que lo estrechamos aqui una sola vez en lugar de esparcir casts.
 */
interface PropsTooltip {
  active?: boolean;
  payload?: ReadonlyArray<{ name?: unknown; value?: unknown; color?: string }>;
  label?: unknown;
}

function tooltip(formatearEtiqueta?: (v: string) => string) {
  return (props: unknown) => {
    const { active, payload, label } = props as PropsTooltip;
    if (!active || !payload?.length) return null;
    const titulo = label === undefined || label === null ? "" : String(label);
    return (
      <CajaTooltip>
        <div className="mb-1 font-medium">
          {formatearEtiqueta && titulo ? formatearEtiqueta(titulo) : titulo}
        </div>
        {payload.map((p, i) => (
          <div key={i} className="flex items-center gap-2">
            <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: p.color }} />
            <span className="text-[var(--tinta-2)]">{String(p.name ?? "")}</span>
            <span className="tabular ml-auto font-medium">{soles(Number(p.value ?? 0))}</span>
          </div>
        ))}
      </CajaTooltip>
    );
  };
}

/* ------------------------------------------------------------------ ritmo del mes */
export function GraficoRitmo({
  serie,
  referencia,
}: {
  serie: PuntoDiario[];
  referencia: number;
}) {
  if (!serie.length) return <Vacio titulo="Sin datos en el periodo" />;

  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={serie} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
          <defs>
            <linearGradient id="degradadoGasto" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--serie-2)" stopOpacity={0.28} />
              <stop offset="100%" stopColor="var(--serie-2)" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="var(--rejilla)" strokeDasharray="0" vertical={false} />
          <XAxis
            dataKey="fecha"
            tick={EJE}
            tickLine={false}
            axisLine={{ stroke: "var(--eje)" }}
            tickFormatter={fechaCorta}
            minTickGap={24}
          />
          <YAxis
            tick={EJE}
            tickLine={false}
            axisLine={false}
            tickFormatter={ejeSoles}
            width={56}
            /* el dominio incluye la referencia: si no, la linea del periodo
               anterior queda fuera del grafico y no se ve nada */
            domain={[0, (max: number) => Math.ceil(Math.max(max, referencia) * 1.08)]}
          />
          {referencia > 0 && (
            <ReferenceLine
              y={referencia}
              stroke="var(--tinta-3)"
              strokeDasharray="4 4"
              label={{
                value: `Periodo anterior ${ejeSoles(referencia)}`,
                position: "insideTopRight",
                fill: "var(--tinta-3)",
                fontSize: 11,
              }}
            />
          )}
          <Tooltip
            cursor={{ stroke: "var(--eje)", strokeWidth: 1 }}
            content={tooltip(fechaCorta)}
          />
          <Area
            type="monotone"
            dataKey="acumulado"
            name="Gasto acumulado"
            stroke="var(--serie-2)"
            strokeWidth={2}
            fill="url(#degradadoGasto)"
            activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--superficie)" }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

/* --------------------------------------------------------- gasto por categoria */
export function GraficoCategorias({
  datos,
  onElegir,
}: {
  datos: Corte[];
  /** Al pulsar la barra de una categoria real (no la de "Otros"). */
  onElegir?: (c: Corte) => void;
}) {
  const [verTabla, setVerTabla] = useState(false);
  if (!datos.length) return <Vacio titulo="Aun no hay gastos clasificados" />;

  // Mas de 8 categorias no se distinguen por color: el resto se pliega en "Otros".
  const visibles = datos.slice(0, 7);
  const resto = datos.slice(7);
  const filas =
    resto.length > 0
      ? [
          ...visibles,
          {
            clave: "otros",
            nombre: "Otros",
            monto: Number(resto.reduce((a, b) => a + b.monto, 0).toFixed(2)),
            pct: Number(resto.reduce((a, b) => a + b.pct, 0).toFixed(1)),
            color: "var(--serie-otros)",
            movimientos: resto.reduce((a, b) => a + (b.movimientos ?? 0), 0),
          },
        ]
      : visibles;

  if (verTabla) {
    return (
      <>
        <BotonTabla activo onClick={() => setVerTabla(false)} />
        <table className="mt-2 w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-[var(--tinta-3)]">
              <th className="py-1 font-medium">Categoria</th>
              <th className="py-1 text-right font-medium">Monto</th>
              <th className="py-1 text-right font-medium">%</th>
            </tr>
          </thead>
          <tbody>
            {filas.map((f) => (
              <tr key={f.clave ?? f.nombre} className="border-t" style={{ borderColor: "var(--borde)" }}>
                <td className="flex items-center gap-2 py-1.5">
                  <span
                    aria-hidden
                    className="h-2.5 w-2.5 rounded-full"
                    style={{ background: f.color }}
                  />
                  {f.nombre}
                </td>
                <td className="tabular py-1.5 text-right">{soles(f.monto)}</td>
                <td className="tabular py-1.5 text-right text-[var(--tinta-3)]">{f.pct}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </>
    );
  }

  return (
    <>
      <BotonTabla activo={false} onClick={() => setVerTabla(true)} />
      <div style={{ height: Math.max(180, filas.length * 38) }} className="w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={filas}
            layout="vertical"
            margin={{ top: 4, right: 72, bottom: 4, left: 4 }}
            barCategoryGap={8}
          >
            <CartesianGrid stroke="var(--rejilla)" horizontal={false} />
            <XAxis type="number" hide />
            <YAxis
              type="category"
              dataKey="nombre"
              tick={{ ...EJE, fill: "var(--tinta-2)" }}
              tickLine={false}
              axisLine={false}
              width={140}
            />
            <Tooltip
              cursor={{ fill: "var(--superficie-2)" }}
              content={tooltip()}
            />
            <Bar
              dataKey="monto"
              name="Gasto"
              radius={[0, 4, 4, 0]}
              barSize={18}
              onClick={(d: { payload?: Corte }) => {
                if (d.payload?.id != null) onElegir?.(d.payload);
              }}
              style={onElegir ? { cursor: "pointer" } : undefined}
            >
              {filas.map((f) => (
                <Cell key={f.clave ?? f.nombre} fill={f.color} />
              ))}
              {/* Etiqueta directa: obligatoria. Tres hues de la paleta quedan
                  bajo 3:1 sobre fondo claro, y el texto los compensa. */}
              <LabelList
                dataKey="monto"
                position="right"
                fill="var(--tinta-2)"
                fontSize={11}
                formatter={(v: number) => soles(v)}
              />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </>
  );
}

function BotonTabla({ activo, onClick }: { activo: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="mb-1 inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-[var(--tinta-3)] hover:bg-[var(--superficie-2)]"
      aria-pressed={activo}
    >
      <Table2 size={13} />
      {activo ? "Ver grafico" : "Ver tabla"}
    </button>
  );
}

/* ------------------------------------------------------------- esencial vs fuga */
export function BarraNecesidad({ datos }: { datos: Corte[] }) {
  const total = datos.reduce((a, b) => a + b.monto, 0);
  if (!total) return <Vacio titulo="Marca tus gastos como esencial o evitable" />;

  return (
    <div>
      <div
        className="flex h-9 w-full overflow-hidden rounded-lg"
        role="img"
        aria-label={datos
          .map((d) => `${d.nombre}: ${soles(d.monto)} (${d.pct}%)`)
          .join(", ")}
      >
        {datos.map((d, i) => (
          <div
            key={d.clave ?? d.nombre}
            title={`${d.nombre}: ${soles(d.monto)}`}
            style={{
              width: `${(d.monto / total) * 100}%`,
              background: d.color,
              /* separador de 2px del color de la superficie entre segmentos */
              marginLeft: i === 0 ? 0 : 2,
            }}
          />
        ))}
      </div>
      <ul className="mt-3 space-y-2">
        {datos.map((d) => (
          <li key={d.clave ?? d.nombre} className="flex items-center gap-2 text-sm">
            <span
              aria-hidden
              className="h-2.5 w-2.5 shrink-0 rounded-full"
              style={{ background: d.color }}
            />
            <span className="text-[var(--tinta-2)]">{d.nombre}</span>
            <span className="tabular ml-auto font-medium">{soles(d.monto)}</span>
            <span className="tabular w-12 text-right text-xs text-[var(--tinta-3)]">
              {d.pct}%
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/* ----------------------------------------------------------- tendencia mensual */
export function GraficoMensual({ datos }: { datos: PuntoMensual[] }) {
  if (!datos.length) return <Vacio titulo="Sin historico todavia" />;
  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={datos} margin={{ top: 8, right: 8, bottom: 0, left: -12 }} barGap={2}>
          <CartesianGrid stroke="var(--rejilla)" vertical={false} />
          <XAxis
            dataKey="etiqueta"
            tick={EJE}
            tickLine={false}
            axisLine={{ stroke: "var(--eje)" }}
          />
          <YAxis tick={EJE} tickLine={false} axisLine={false} tickFormatter={ejeSoles} width={56} />
          <Tooltip cursor={{ fill: "var(--superficie-2)" }} content={tooltip()} />
          <Legend
            verticalAlign="top"
            align="right"
            height={28}
            iconType="circle"
            iconSize={8}
            wrapperStyle={{ fontSize: 12, color: "var(--tinta-2)" }}
          />
          <Bar dataKey="ingreso" name="Ingresos" fill="var(--serie-1)" radius={[4, 4, 0, 0]} />
          <Bar dataKey="gasto" name="Gastos" fill="var(--serie-2)" radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/* ------------------------------------------- categorias a lo largo del tiempo */

// Paleta categorica del modo claro, en el mismo orden que --serie-N de index.css.
// Si cambias alli un hex, cambialo tambien aqui: con esta lista se reconoce que
// color del catalogo es cual para devolver su variable CSS.
const PALETA = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"];
const GRIS = "#898781";
/** Clave con la que el backend agrupa lo que no entra en la pila. */
export const CLAVE_OTRAS = "otras";

const claveDe = (s: Corte) => s.clave ?? s.nombre;

/**
 * Color de cada serie en una pila: sin repetir y estable.
 *
 * El catalogo repite hues entre raices (Vivienda y Mascotas comparten aqua,
 * Financiero y Personas el gris) y las subcategorias heredan el de su padre. En
 * barras sueltas no importa porque cada una lleva su nombre, pero en una pila solo
 * la leyenda identifica el segmento: dos iguales serian indistinguibles.
 *
 * Estable: cuando dos series comparten color se lo queda la de id menor, no la que
 * mas gasto. Asi, cambiar de periodo y alterar el ranking no repinta a Vivienda.
 * Las que ceden su color toman el primer hue libre empezando por uno derivado de su
 * id, que tambien es fijo. El gris queda para "Otras".
 *
 * Los hex de la paleta se devuelven como su variable CSS para que el modo oscuro
 * use su propio escalon.
 */
function coloresSinChoques(series: Corte[]): Map<string, string> {
  const usados = new Set<string>();
  const asignado = new Map<string, string>();
  const otras = series.find((s) => s.clave === CLAVE_OTRAS);
  if (otras) {
    asignado.set(claveDe(otras), GRIS);
    usados.add(GRIS);
  }
  const porId = series
    .filter((s) => !asignado.has(claveDe(s)))
    .sort((a, b) => (a.id ?? Number.MAX_SAFE_INTEGER) - (b.id ?? Number.MAX_SAFE_INTEGER));

  for (const s of porId) {
    const hex = (s.color ?? "").toLowerCase();
    if (!hex || usados.has(hex)) continue;
    asignado.set(claveDe(s), hex);
    usados.add(hex);
  }
  for (const s of porId) {
    if (asignado.has(claveDe(s))) continue;
    const inicio = Math.abs(s.id ?? 0) % PALETA.length;
    const hex =
      PALETA.map((_, i) => PALETA[(inicio + i) % PALETA.length]).find((p) => !usados.has(p)) ??
      GRIS;
    asignado.set(claveDe(s), hex);
    usados.add(hex);
  }

  const salida = new Map<string, string>();
  for (const [clave, hex] of asignado) {
    const i = PALETA.indexOf(hex);
    salida.set(clave, i >= 0 ? `var(--serie-${i + 1})` : hex === GRIS ? "var(--serie-otros)" : hex);
  }
  return salida;
}

function tooltipPila(props: unknown) {
  const { active, payload, label } = props as PropsTooltip;
  if (!active || !payload?.length) return null;
  // De arriba abajo, como se ven los segmentos, y sin las categorias en cero.
  const filas = payload.filter((p) => Number(p.value) > 0).reverse();
  const total = filas.reduce((a, p) => a + Number(p.value), 0);
  return (
    <CajaTooltip>
      <div className="mb-1 flex gap-4 font-medium">
        <span>{String(label ?? "")}</span>
        <span className="tabular ml-auto">{soles(total)}</span>
      </div>
      {filas.length === 0 && <div className="text-[var(--tinta-3)]">Sin gastos</div>}
      {filas.map((p, i) => (
        <div key={i} className="flex items-center gap-2">
          <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: p.color }} />
          <span className="text-[var(--tinta-2)]">{String(p.name ?? "")}</span>
          <span className="tabular ml-auto pl-3 font-medium">{soles(Number(p.value))}</span>
        </div>
      ))}
    </CajaTooltip>
  );
}

/**
 * Segmento de una pila con 2px de separacion (1px arriba, 1px abajo) del color de
 * la superficie. Solo si el segmento la aguanta: con un trazo fijo, los segmentos
 * de 1-2px desaparecian enteros y su categoria no se veia en la barra.
 */
function SegmentoPila(props: unknown) {
  const { x, y, width, height, fill } = props as {
    x: number;
    y: number;
    width: number;
    height: number;
    fill: string;
  };
  if (!(height > 0) || !(width > 0)) return <g />;
  const hueco = height > 4 ? 1 : 0;
  return <rect x={x} y={y + hueco} width={width} height={height - 2 * hueco} fill={fill} />;
}

export function GraficoCategoriasPorPeriodo({
  periodos,
  categorias,
}: {
  periodos: PuntoPeriodo[];
  categorias: Corte[];
}) {
  const [verTabla, setVerTabla] = useState(false);
  if (!categorias.length) return <Vacio titulo="Sin gastos en el rango" />;
  const colores = coloresSinChoques(categorias);
  // Las series van por clave (el id de la categoria), no por nombre: dos
  // categorias con el mismo nombre ya no se funden en una.
  const monto = (p: PuntoPeriodo, c: Corte) => p.por_categoria[claveDe(c)] ?? 0;

  if (verTabla) {
    const conDatos = periodos.filter((p) => p.gasto > 0);
    return (
      <>
        <BotonTabla activo onClick={() => setVerTabla(false)} />
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-[var(--tinta-3)]">
                <th className="py-1 pr-3 font-medium">Periodo</th>
                {categorias.map((c) => (
                  <th key={claveDe(c)} className="whitespace-nowrap py-1 pr-3 text-right font-medium">
                    {c.nombre}
                  </th>
                ))}
                <th className="py-1 text-right font-medium">Total</th>
              </tr>
            </thead>
            <tbody>
              {conDatos.map((p) => (
                <tr key={p.periodo} className="border-t" style={{ borderColor: "var(--borde)" }}>
                  <td className="whitespace-nowrap py-1.5 pr-3">{p.etiqueta}</td>
                  {categorias.map((c) => (
                    <td key={claveDe(c)} className="tabular py-1.5 pr-3 text-right text-[var(--tinta-2)]">
                      {monto(p, c) ? soles(monto(p, c)) : "—"}
                    </td>
                  ))}
                  <td className="tabular py-1.5 text-right font-medium">{soles(p.gasto)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </>
    );
  }

  return (
    <>
      <BotonTabla activo={false} onClick={() => setVerTabla(true)} />
      <div className="h-80 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={periodos} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
            <CartesianGrid stroke="var(--rejilla)" vertical={false} />
            <XAxis
              dataKey="etiqueta"
              tick={EJE}
              tickLine={false}
              axisLine={{ stroke: "var(--eje)" }}
              minTickGap={8}
            />
            <YAxis tick={EJE} tickLine={false} axisLine={false} tickFormatter={ejeSoles} width={56} />
            <Tooltip cursor={{ fill: "var(--superficie-2)" }} content={tooltipPila} />
            {/* Con una sola serie la leyenda sobra: el titulo ya la nombra. */}
            {categorias.length > 1 && (
              <Legend
                verticalAlign="bottom"
                iconType="circle"
                iconSize={8}
                wrapperStyle={{ fontSize: 12, color: "var(--tinta-2)", paddingTop: 8 }}
              />
            )}
            {/* La mayor abajo, pegada a la base: es la que mejor se compara
                entre barras. Sin radio: el segmento de arriba cambia de
                categoria de una barra a otra. */}
            {categorias.map((c) => (
              <Bar
                key={claveDe(c)}
                dataKey={(p: PuntoPeriodo) => monto(p, c)}
                name={c.nombre}
                stackId="categorias"
                fill={colores.get(claveDe(c))}
                shape={SegmentoPila}
                maxBarSize={48}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
    </>
  );
}

/* ------------------------------------------------------------- listas simples */
export function ListaRanking({
  datos,
  vacio,
}: {
  datos: Corte[];
  vacio: string;
}) {
  if (!datos.length) return <Vacio titulo={vacio} />;
  const max = Math.max(...datos.map((d) => d.monto), 1);
  return (
    <ul className="space-y-2.5">
      {datos.map((d) => (
        <li key={d.clave ?? d.nombre}>
          <div className="flex items-baseline gap-2 text-sm">
            <span className="truncate text-[var(--tinta)]">{d.nombre}</span>
            {d.movimientos !== undefined && (
              <span
                className="text-xs text-[var(--tinta-3)]"
                title={
                  d.agrupado
                    ? `${d.movimientos} pagos a personas distintas, juntos en una fila`
                    : `${d.movimientos} movimientos`
                }
              >
                ×{d.movimientos}
                {d.agrupado && " ·  agrupado"}
              </span>
            )}
            <span className="tabular ml-auto font-medium">{soles(d.monto)}</span>
          </div>
          <div
            className="mt-1 h-1.5 w-full overflow-hidden rounded-full"
            style={{ background: "var(--superficie-2)" }}
          >
            <div
              className="h-full rounded-full"
              style={{ width: `${(d.monto / max) * 100}%`, background: "var(--serie-1)" }}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}
