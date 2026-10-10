/**
 * Graficos de Inversiones. Todo en dolares.
 *
 * Mismas reglas que components/charts.tsx: un solo eje de valor, marcas finas,
 * rejilla discreta, leyenda siempre que hay dos series o mas y el color nunca
 * solo (las compras y ventas llevan ademas forma: triangulo arriba o abajo).
 */
import { useEffect, useMemo, useRef, useState } from "react";
import {
  Area,
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type {
  DividendosInversion,
  MarcaOperacion,
  PreciosAccion,
  PuntoValor,
  RangoInversion,
  RentabilidadInversion,
} from "../lib/api";
import { dolares, ejeSoles, fecha, fechaCorta, pctDe } from "../lib/format";
import { CajaTooltip, EJE } from "./charts";
import { Entrada, Vacio } from "./ui";

export const RANGOS: { valor: RangoInversion; texto: string; titulo?: string }[] = [
  { valor: "1D", texto: "1D" },
  { valor: "1S", texto: "1S" },
  { valor: "1M", texto: "1M" },
  { valor: "3M", texto: "3M" },
  { valor: "6M", texto: "6M" },
  { valor: "YTD", texto: "YTD", titulo: "Lo que va del año" },
  { valor: "1A", texto: "1A" },
  { valor: "TODO", texto: "Todo" },
];

/** El rango del grafico. */
export function SelectorRango({
  valor,
  onCambiar,
}: {
  valor: RangoInversion;
  onCambiar: (r: RangoInversion) => void;
}) {
  return <Segmentado etiqueta="Rango" opciones={RANGOS} valor={valor} onCambiar={onCambiar} />;
}

/** Botones de los que solo uno esta pulsado. En el movil ocupan todo el ancho (ocho
 *  no caben al lado de un titulo); si aun asi no caben, se desplazan de lado. */
function Segmentado<T extends string | number>({
  etiqueta,
  opciones,
  valor,
  onCambiar,
}: {
  etiqueta: string;
  opciones: { valor: T; texto: string; titulo?: string }[];
  valor: T;
  onCambiar: (v: T) => void;
}) {
  return (
    <div
      role="group"
      aria-label={etiqueta}
      className="flex w-full max-w-full overflow-x-auto rounded-lg border p-0.5 sm:ml-auto sm:inline-flex sm:w-auto"
      style={{ borderColor: "var(--borde)" }}
    >
      {opciones.map((r) => (
        <button
          key={r.valor}
          type="button"
          aria-pressed={valor === r.valor}
          title={r.titulo}
          onClick={() => onCambiar(r.valor)}
          className={`flex-1 rounded-md px-1 py-1 text-xs font-medium transition-colors sm:flex-none sm:px-2 ${
            valor === r.valor
              ? "text-[var(--tinta)]"
              : "text-[var(--tinta-3)] hover:text-[var(--tinta-2)]"
          }`}
          style={valor === r.valor ? { background: "var(--superficie-2)" } : undefined}
        >
          {r.texto}
        </button>
      ))}
    </div>
  );
}

/** "14:35" para intradia, "09 oct" para dias. */
function etiquetaTiempo(t: string, intradia: boolean): string {
  if (!intradia) return fechaCorta(t);
  return new Date(t).toLocaleTimeString("es-PE", { hour: "2-digit", minute: "2-digit" });
}

function etiquetaCompleta(t: string, intradia: boolean): string {
  if (!intradia) return fechaCorta(t);
  return new Date(t).toLocaleString("es-PE", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** "1.5 k" y, en la proyeccion a muchos anios, "1.5 M" en vez de "1500 k". */
const ejeDolares = (v: number) => (Math.abs(v) >= 1_000_000 ? `${+(v / 1_000_000).toFixed(2)} M` : ejeSoles(v));

type FormaLeyenda = "linea" | "discontinua" | "banda" | "punto" | "subir" | "bajar";

function Leyenda({ items }: { items: { color: string; texto: string; forma?: FormaLeyenda }[] }) {
  return (
    <div className="mb-2 flex flex-wrap items-center justify-end gap-x-4 gap-y-1 text-xs text-[var(--tinta-2)]">
      {items.map((i) => (
        <span key={i.texto} className="inline-flex items-center gap-1.5">
          {i.forma === "linea" ? (
            <span aria-hidden className="h-0.5 w-3.5 rounded" style={{ background: i.color }} />
          ) : i.forma === "discontinua" ? (
            <span aria-hidden className="w-3.5 border-t-2 border-dashed" style={{ borderColor: i.color }} />
          ) : i.forma === "banda" ? (
            <span aria-hidden className="h-2.5 w-3.5 rounded-sm" style={{ background: i.color, opacity: 0.3 }} />
          ) : i.forma === "subir" || i.forma === "bajar" ? (
            <svg aria-hidden width="10" height="10" viewBox="0 0 10 10">
              <path d={i.forma === "subir" ? "M5 1 L9 9 L1 9 Z" : "M1 1 L9 1 L5 9 Z"} fill={i.color} />
            </svg>
          ) : (
            <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: i.color }} />
          )}
          {i.texto}
        </span>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------- valor en el tiempo */

/**
 * El valor de la cuenta frente a lo que pusiste: la distancia entre las dos
 * lineas es la ganancia. El valor es la serie que importa (acento); los
 * aportes son contexto (gris, escalonados porque cambian de golpe).
 */
export function GraficoValor({ puntos, intradia }: { puntos: PuntoValor[]; intradia: boolean }) {
  if (!puntos.length) {
    return (
      <Vacio
        titulo="Sin historia todavía"
        detalle="Sube tus estados de cuenta o pulsa Actualizar para leer los correos de Hapi."
      />
    );
  }
  return (
    <div>
      <Leyenda
        items={[
          { color: "var(--serie-1)", texto: "Valor de la cuenta", forma: "linea" },
          { color: "var(--tinta-3)", texto: "Lo que aportaste", forma: "linea" },
        ]}
      />
      <div className="h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={puntos} syncId="cuenta" margin={{ top: 8, right: 12, bottom: 0, left: -8 }}>
            <defs>
              <linearGradient id="degradadoValor" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--serie-1)" stopOpacity={0.22} />
                <stop offset="100%" stopColor="var(--serie-1)" stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="var(--rejilla)" vertical={false} />
            <XAxis
              dataKey="t"
              tick={EJE}
              tickLine={false}
              axisLine={{ stroke: "var(--eje)" }}
              tickFormatter={(t: string) => etiquetaTiempo(t, intradia)}
              minTickGap={32}
            />
            <YAxis
              tick={EJE}
              tickLine={false}
              axisLine={false}
              tickFormatter={ejeDolares}
              width={56}
              domain={intradia ? ["dataMin", "dataMax"] : [0, "auto"]}
            />
            <Tooltip
              cursor={{ stroke: "var(--eje)", strokeWidth: 1 }}
              content={(props: unknown) => {
                const { active, payload, label } = props as {
                  active?: boolean;
                  payload?: { payload: PuntoValor }[];
                  label?: string;
                };
                if (!active || !payload?.length) return null;
                const p = payload[0].payload;
                return (
                  <CajaTooltip>
                    <div className="mb-1 font-medium">{etiquetaCompleta(String(label), intradia)}</div>
                    <Fila color="var(--serie-1)" texto="Valor" valor={dolares(p.valor)} />
                    <Fila color="var(--tinta-3)" texto="Aportado" valor={dolares(p.aportes)} />
                    <Fila texto="Ganancia" valor={dolares(p.valor - p.aportes)} />
                  </CajaTooltip>
                );
              }}
            />
            <Area
              type="monotone"
              dataKey="valor"
              name="Valor"
              stroke="var(--serie-1)"
              strokeWidth={2}
              fill="url(#degradadoValor)"
              baseValue={intradia ? "dataMin" : 0}
              activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--superficie)" }}
              isAnimationActive={false}
            />
            <Line
              type="stepAfter"
              dataKey="aportes"
              name="Aportado"
              stroke="var(--tinta-3)"
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 3 }}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

/**
 * Lo ganado en cada momento: valor menos lo aportado. Un deposito sube las dos
 * cosas a la vez, asi que no la mueve; solo el mercado, los dividendos y las
 * comisiones. Va debajo del valor, con el mismo rango y el cursor compartido.
 */
export function GraficoGanancia({ puntos, intradia }: { puntos: PuntoValor[]; intradia: boolean }) {
  if (!puntos.length) return null;
  const filas = puntos.map((p) => ({ t: p.t, ganancia: +(p.valor - p.aportes).toFixed(2) }));
  const valores = filas.map((f) => f.ganancia);
  // Sin forzar el cero: en un rango corto importa cuanto se movio, no la distancia al cero.
  const marcas = marcasRedondas(valores, false);
  // El relleno sale del cero si el cero esta a la vista; si no, del borde del grafico.
  const base = marcas[0] > 0 ? marcas[0] : marcas[marcas.length - 1] < 0 ? marcas[marcas.length - 1] : 0;
  return (
    <div className="mt-5">
      <div className="mb-1 flex flex-wrap items-baseline justify-between gap-x-3">
        <h3 className="text-xs font-medium text-[var(--tinta-2)]">Ganancia</h3>
        <span className="text-xs text-[var(--tinta-3)]">
          Valor menos lo que aportaste: tus depósitos y retiros no la mueven
        </span>
      </div>
      <div className="h-44 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={filas} syncId="cuenta" margin={{ top: 8, right: 12, bottom: 0, left: -8 }}>
            <defs>
              <linearGradient id="degradadoGanancia" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--serie-1)" stopOpacity={0.22} />
                <stop offset="100%" stopColor="var(--serie-1)" stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="var(--rejilla)" vertical={false} />
            <XAxis
              dataKey="t"
              tick={EJE}
              tickLine={false}
              axisLine={{ stroke: "var(--eje)" }}
              tickFormatter={(t: string) => etiquetaTiempo(t, intradia)}
              minTickGap={32}
            />
            <YAxis
              tick={EJE}
              tickLine={false}
              axisLine={false}
              tickFormatter={ejeDolares}
              width={56}
              ticks={marcas}
              domain={[marcas[0], marcas[marcas.length - 1]]}
            />
            <ReferenceLine y={0} stroke="var(--eje)" />
            <Tooltip
              cursor={{ stroke: "var(--eje)", strokeWidth: 1 }}
              content={(props: unknown) => {
                const { active, payload, label } = props as {
                  active?: boolean;
                  payload?: { payload: (typeof filas)[number] }[];
                  label?: string;
                };
                if (!active || !payload?.length) return null;
                return (
                  <CajaTooltip>
                    <div className="mb-1 font-medium">{etiquetaCompleta(String(label), intradia)}</div>
                    <Fila color="var(--serie-1)" texto="Ganancia" valor={dolares(payload[0].payload.ganancia)} />
                  </CajaTooltip>
                );
              }}
            />
            <Area
              type="monotone"
              dataKey="ganancia"
              name="Ganancia"
              stroke="var(--serie-1)"
              strokeWidth={2}
              fill="url(#degradadoGanancia)"
              baseValue={base}
              activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--superficie)" }}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function Fila({ color, texto, valor }: { color?: string; texto: string; valor: string }) {
  return (
    <div className="flex items-center gap-2">
      <span
        aria-hidden
        className="h-2 w-2 rounded-full"
        style={{ background: color ?? "transparent" }}
      />
      <span className="text-[var(--tinta-2)]">{texto}</span>
      <span className="tabular ml-auto pl-4 font-medium">{valor}</span>
    </div>
  );
}

/* ------------------------------------------------------------- dividendos */

/** Neto y retencion apilados: la columna entera es el bruto. */
export function GraficoDividendos({ datos }: { datos: DividendosInversion["por_mes"] }) {
  if (!datos.length) return <Vacio titulo="Aún no hay dividendos" />;
  const filas = datos.map((d) => ({ ...d, etiqueta: etiquetaMes(d.mes) }));
  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={filas} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
          <CartesianGrid stroke="var(--rejilla)" vertical={false} />
          <XAxis dataKey="etiqueta" tick={EJE} tickLine={false} axisLine={{ stroke: "var(--eje)" }} minTickGap={8} />
          <YAxis tick={EJE} tickLine={false} axisLine={false} width={48} />
          <Tooltip
            cursor={{ fill: "var(--superficie-2)" }}
            content={(props: unknown) => {
              const { active, payload, label } = props as {
                active?: boolean;
                payload?: { payload: (typeof filas)[number] }[];
                label?: string;
              };
              if (!active || !payload?.length) return null;
              const d = payload[0].payload;
              return (
                <CajaTooltip>
                  <div className="mb-1 font-medium">{String(label)}</div>
                  <Fila color="var(--serie-1)" texto="Neto" valor={dolares(d.neto)} />
                  <Fila color="var(--serie-otros)" texto="Retención" valor={dolares(d.retencion)} />
                  <Fila texto="Bruto" valor={dolares(d.bruto)} />
                </CajaTooltip>
              );
            }}
          />
          <Legend
            verticalAlign="top"
            align="right"
            height={28}
            iconType="circle"
            iconSize={8}
            wrapperStyle={{ fontSize: 12, color: "var(--tinta-2)" }}
          />
          <Bar dataKey="neto" name="Neto" stackId="d" fill="var(--serie-1)" stroke="var(--superficie)" strokeWidth={1} />
          <Bar
            dataKey="retencion"
            name="Retención"
            stackId="d"
            fill="var(--serie-otros)"
            stroke="var(--superficie)"
            strokeWidth={1}
            radius={[4, 4, 0, 0]}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function etiquetaMes(mes: string): string {
  const [anio, m] = mes.split("-").map(Number);
  return new Date(anio, m - 1, 15).toLocaleDateString("es-PE", { month: "short", year: "2-digit" });
}

/* ------------------------------------------------------------- rentabilidad */

/** Fraccion a eje: 0.05 -> "5%", 0.025 -> "2.5%". */
const ejePct = (v: number) => `${+(v * 100).toFixed(1)}%`;

/** Marcas del eje en pasos redondos (1, 2, 2.5 o 5 por potencia de diez) que cubren
 *  los valores. Las automaticas salian en 13 % y 26 %, o en 1.1 k y 2.2 k. */
function marcasRedondas(valores: (number | null)[], conCero: boolean): number[] {
  const v = valores.filter((x): x is number => x !== null);
  let min = Math.min(...v);
  let max = Math.max(...v);
  if (conCero) {
    min = Math.min(0, min);
    max = Math.max(0, max);
  }
  if (!(max > min)) max = min + 1;
  const bruto = (max - min) / 5;
  const potencia = 10 ** Math.floor(Math.log10(bruto));
  const paso = [1, 2, 2.5, 5, 10].map((m) => m * potencia).find((p) => p >= bruto) ?? 10 * potencia;
  const marcas: number[] = [];
  for (let i = Math.floor(min / paso); i <= Math.ceil(max / paso); i++) marcas.push(+(i * paso).toFixed(6));
  return marcas;
}

/** Las rentabilidades siempre muestran el cero: separa los meses buenos de los malos. */
const marcasPct = (valores: (number | null)[]) => marcasRedondas(valores, true);

/**
 * Tu rentabilidad de cada mes junto a la del S&P 500. Barras desde cero: hacia
 * arriba los meses buenos, hacia abajo los malos. Con muchos meses, en pantallas
 * estrechas el grafico se desplaza de lado en vez de apretar las barras.
 */
export function GraficoRentabilidadMensual({
  datos,
  simbolo,
}: {
  datos: RentabilidadInversion["por_mes"];
  simbolo: string;
}) {
  // En pantallas estrechas se abre en los meses recientes, no en los primeros.
  const desplazable = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = desplazable.current;
    if (el) el.scrollLeft = el.scrollWidth;
  }, [datos.length]);
  if (!datos.length) return <Vacio titulo="Sin historia todavía" />;
  const filas = datos.map((d) => ({ ...d, etiqueta: etiquetaMes(d.mes) }));
  const marcas = marcasPct(datos.flatMap((d) => [d.rentabilidad, d.referencia]));
  return (
    <div>
      <Leyenda
        items={[
          { color: "var(--serie-1)", texto: "Tú" },
          { color: "var(--serie-otros)", texto: `S&P 500 (${simbolo})` },
        ]}
      />
      <div ref={desplazable} className="-mx-4 overflow-x-auto px-4">
        <div className="h-64" style={{ minWidth: Math.max(filas.length * 16, 320) }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={filas} margin={{ top: 8, right: 8, bottom: 0, left: -8 }} barGap={2} barCategoryGap="20%">
              <CartesianGrid stroke="var(--rejilla)" vertical={false} />
              <XAxis dataKey="etiqueta" tick={EJE} tickLine={false} axisLine={false} minTickGap={12} />
              <YAxis
                tick={EJE}
                tickLine={false}
                axisLine={false}
                width={48}
                tickFormatter={ejePct}
                ticks={marcas}
                domain={[marcas[0], marcas[marcas.length - 1]]}
              />
              <ReferenceLine y={0} stroke="var(--eje)" />
              <Tooltip
                cursor={{ fill: "var(--superficie-2)" }}
                content={(props: unknown) => {
                  const { active, payload, label } = props as {
                    active?: boolean;
                    payload?: { payload: (typeof filas)[number] }[];
                    label?: string;
                  };
                  if (!active || !payload?.length) return null;
                  const d = payload[0].payload;
                  return (
                    <CajaTooltip>
                      <div className="mb-1 font-medium">{String(label)}</div>
                      <Fila color="var(--serie-1)" texto="Tú" valor={pctDe(d.rentabilidad)} />
                      <Fila color="var(--serie-otros)" texto="S&P 500" valor={pctDe(d.referencia)} />
                      <Fila texto="Ganancia" valor={dolares(d.ganancia)} />
                    </CajaTooltip>
                  );
                }}
              />
              <Bar dataKey="rentabilidad" name="Tú" fill="var(--serie-1)" radius={[4, 4, 0, 0]} isAnimationActive={false} />
              <Bar
                dataKey="referencia"
                name="S&P 500"
                fill="var(--serie-otros)"
                radius={[4, 4, 0, 0]}
                isAnimationActive={false}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}

/**
 * Cuanto ha crecido lo invertido desde el primer deposito, contigo y con el
 * S&P 500. El indice va discontinuo: se distingue sin depender del color.
 */
export function GraficoRentabilidadAcumulada({
  puntos,
  simbolo,
}: {
  puntos: RentabilidadInversion["acumulada"];
  simbolo: string;
}) {
  if (!puntos.length) return <Vacio titulo="Sin historia todavía" />;
  const marcas = marcasPct(puntos.flatMap((p) => [p.tuya, p.referencia]));
  return (
    <div>
      <Leyenda
        items={[
          { color: "var(--serie-1)", texto: "Tú", forma: "linea" },
          { color: "var(--serie-otros)", texto: `S&P 500 (${simbolo})`, forma: "discontinua" },
        ]}
      />
      <div className="h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={puntos} margin={{ top: 8, right: 12, bottom: 0, left: -8 }}>
            <CartesianGrid stroke="var(--rejilla)" vertical={false} />
            <XAxis
              dataKey="t"
              tick={EJE}
              tickLine={false}
              axisLine={false}
              tickFormatter={(t: string) => etiquetaMes(t.slice(0, 7))}
              minTickGap={40}
            />
            <YAxis
              tick={EJE}
              tickLine={false}
              axisLine={false}
              width={48}
              tickFormatter={ejePct}
              ticks={marcas}
              domain={[marcas[0], marcas[marcas.length - 1]]}
            />
            <ReferenceLine y={0} stroke="var(--eje)" />
            <Tooltip
              cursor={{ stroke: "var(--eje)", strokeWidth: 1 }}
              content={(props: unknown) => {
                const { active, payload, label } = props as {
                  active?: boolean;
                  payload?: { payload: (typeof puntos)[number] }[];
                  label?: string;
                };
                if (!active || !payload?.length) return null;
                const p = payload[0].payload;
                return (
                  <CajaTooltip>
                    <div className="mb-1 font-medium">{fecha(String(label))}</div>
                    <Fila color="var(--serie-1)" texto="Tú" valor={pctDe(p.tuya)} />
                    <Fila color="var(--serie-otros)" texto="S&P 500" valor={pctDe(p.referencia)} />
                  </CajaTooltip>
                );
              }}
            />
            <Line
              type="monotone"
              dataKey="tuya"
              name="Tú"
              stroke="var(--serie-1)"
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--superficie)" }}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="referencia"
              name="S&P 500"
              stroke="var(--serie-otros)"
              strokeWidth={2}
              strokeDasharray="5 4"
              dot={false}
              activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--superficie)" }}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------- proyeccion */

/** La referencia: el centro es lo que ha dado el S&P 500 a largo plazo (~10 % al
 *  anio con los dividendos reinvertidos); el abanico, un caso flojo y uno muy
 *  bueno sostenido. Ningun periodo de 20 o 30 anios del indice paso del 15 %, asi
 *  que una tasa mas alta va aparte, como la tuya. */
const TASAS = { baja: 0.05, media: 0.1, alta: 0.15 };
/** Lo que traen los campos al abrir la seccion. */
const APORTE_POR_DEFECTO = 200;
const TASA_PROPIA_POR_DEFECTO = 20;   // % al anio
/** Para pasar a dolares de hoy lo que la proyeccion da en dolares de ese anio. */
const INFLACION = 0.03;
const PLAZOS = [5, 10, 20, 30].map((a) => ({ valor: a, texto: `${a} años` }));
const tasa = (t: number) => `${+(t * 100).toFixed(1)} %`;

/** "20" o "7,5" -> 0.2 o 0.075. Vacio o absurdo (perderlo todo o mas) -> sin linea. */
function leerTasa(texto: string): number | null {
  const n = Number(texto.replace(",", "."));
  if (texto.trim() === "" || !Number.isFinite(n) || n <= -100 || n > 100) return null;
  return n / 100;
}

type PuntoProyeccion = {
  mes: number;
  sinRendimiento: number;
  baja: number;
  media: number;
  alta: number;
  abanico: [number, number];
  propia: number | null;
};

/**
 * La cuenta mes a mes si cada anio rinde lo mismo y a fin de cada mes entra
 * `aporte`: saldo = saldo anterior x (1 + r) + aporte. Cada tasa anual se pasa a
 * su equivalente mensual compuesto: 10 % al anio es 0.797 % al mes, no 10 / 12.
 */
function proyectar(inicial: number, aporte: number, anios: number, propia: number | null): PuntoProyeccion[] {
  const mensual = (t: number) => (1 + t) ** (1 / 12) - 1;
  const r = { baja: mensual(TASAS.baja), media: mensual(TASAS.media), alta: mensual(TASAS.alta) };
  const rPropia = propia === null ? null : mensual(propia);
  const v = { baja: inicial, media: inicial, alta: inicial, propia: inicial };
  const puntos: PuntoProyeccion[] = [];
  for (let mes = 0; mes <= anios * 12; mes++) {
    if (mes > 0) {
      v.baja = v.baja * (1 + r.baja) + aporte;
      v.media = v.media * (1 + r.media) + aporte;
      v.alta = v.alta * (1 + r.alta) + aporte;
      if (rPropia !== null) v.propia = v.propia * (1 + rPropia) + aporte;
    }
    puntos.push({
      mes,
      sinRendimiento: inicial + aporte * mes,
      baja: v.baja,
      media: v.media,
      alta: v.alta,
      abanico: [v.baja, v.alta],
      propia: rPropia === null ? null : v.propia,
    });
  }
  return puntos;
}

/** "oct. 2036": el mes que corresponde a `mes` meses desde hoy. */
function mesFuturo(mes: number): Date {
  const hoy = new Date();
  return new Date(hoy.getFullYear(), hoy.getMonth() + mes, 15);
}

/**
 * Cuanto podria valer la cuenta. Tu tasa va en su propio color; de referencia,
 * el S&P 500 (linea azul) con su abanico de la tasa baja a la alta, y en gris lo
 * que habria sin rendimiento ninguno.
 */
export function Proyeccion({ valorInicial, aporteMedio }: { valorInicial: number; aporteMedio: number }) {
  const [aporteTexto, setAporteTexto] = useState(String(APORTE_POR_DEFECTO));
  const [tasaTexto, setTasaTexto] = useState(String(TASA_PROPIA_POR_DEFECTO));
  const [anios, setAnios] = useState(10);
  const aporte = Math.max(0, Number(aporteTexto) || 0);
  const propia = leerTasa(tasaTexto);
  const puntos = useMemo(
    () => proyectar(valorInicial, aporte, anios, propia),
    [valorInicial, aporte, anios, propia],
  );
  const final = puntos[puntos.length - 1];
  const deHoy = (v: number) => v / (1 + INFLACION) ** anios;
  const marcas = Array.from({ length: 6 }, (_, i) => (i * anios * 12) / 5);
  const marcasY = marcasRedondas([valorInicial, final.alta, final.propia], true);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <label className="block w-36">
          <span className="mb-1 block text-xs text-[var(--tinta-3)]">Aporte al mes (US$)</span>
          <Entrada
            type="number"
            min={0}
            step={10}
            inputMode="decimal"
            value={aporteTexto}
            onChange={(e) => setAporteTexto(e.target.value)}
          />
        </label>
        <label className="block w-36">
          <span className="mb-1 block text-xs text-[var(--tinta-3)]">Tu rentabilidad (% al año)</span>
          <Entrada
            type="number"
            step={1}
            inputMode="decimal"
            value={tasaTexto}
            onChange={(e) => setTasaTexto(e.target.value)}
          />
        </label>
        <div className="min-w-0">
          <span className="mb-1 block text-xs text-[var(--tinta-3)]">Plazo</span>
          <Segmentado etiqueta="Plazo" opciones={PLAZOS} valor={anios} onCambiar={setAnios} />
        </div>
      </div>

      <div className="space-y-0.5 text-sm">
        {propia !== null && final.propia !== null && (
          <p>
            En {anios} años, con tu {tasa(propia)} al año: <b className="tabular">{dolares(final.propia)}</b>{" "}
            <span className="text-[var(--tinta-3)]">(≈ {dolares(deHoy(final.propia))} en dólares de hoy).</span>
          </p>
        )}
        <p>
          {propia === null ? `En ${anios} años, con` : "Con"} el S&amp;P 500 ({tasa(TASAS.media)}):{" "}
          <b className="tabular">{dolares(final.media)}</b>{" "}
          <span className="text-[var(--tinta-3)]">
            (≈ {dolares(deHoy(final.media))} de hoy), entre {dolares(final.baja)} con {tasa(TASAS.baja)} y{" "}
            {dolares(final.alta)} con {tasa(TASAS.alta)}. Sin rendimiento serían {dolares(final.sinRendimiento)}.
          </span>
        </p>
      </div>

      <div>
        <Leyenda
          items={[
            ...(propia !== null
              ? [{ color: "var(--serie-2)", texto: `Tu ${tasa(propia)} al año`, forma: "linea" as const }]
              : []),
            { color: "var(--serie-1)", texto: `${tasa(TASAS.media)} al año (S&P 500)`, forma: "linea" },
            { color: "var(--serie-1)", texto: `Entre ${tasa(TASAS.baja)} y ${tasa(TASAS.alta)}`, forma: "banda" },
            { color: "var(--tinta-3)", texto: "Sin rendimiento", forma: "discontinua" },
          ]}
        />
        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={puntos} margin={{ top: 8, right: 12, bottom: 0, left: -8 }}>
              <CartesianGrid stroke="var(--rejilla)" vertical={false} />
              <XAxis
                dataKey="mes"
                type="number"
                domain={[0, anios * 12]}
                ticks={marcas}
                tick={EJE}
                tickLine={false}
                axisLine={{ stroke: "var(--eje)" }}
                tickFormatter={(m: number) => String(mesFuturo(m).getFullYear())}
              />
              <YAxis
                tick={EJE}
                tickLine={false}
                axisLine={false}
                tickFormatter={ejeDolares}
                width={56}
                ticks={marcasY}
                domain={[marcasY[0], marcasY[marcasY.length - 1]]}
              />
              <Tooltip
                cursor={{ stroke: "var(--eje)", strokeWidth: 1 }}
                content={(props: unknown) => {
                  const { active, payload } = props as {
                    active?: boolean;
                    payload?: { payload: PuntoProyeccion }[];
                  };
                  if (!active || !payload?.length) return null;
                  const p = payload[0].payload;
                  return (
                    <CajaTooltip>
                      <div className="mb-1 font-medium">
                        {mesFuturo(p.mes).toLocaleDateString("es-PE", { month: "short", year: "numeric" })}
                      </div>
                      {propia !== null && (
                        <Fila color="var(--serie-2)" texto={`Tu ${tasa(propia)} al año`} valor={dolares(p.propia)} />
                      )}
                      <Fila color="var(--serie-1)" texto={`${tasa(TASAS.alta)} al año`} valor={dolares(p.alta)} />
                      <Fila color="var(--serie-1)" texto={`${tasa(TASAS.media)} al año`} valor={dolares(p.media)} />
                      <Fila color="var(--serie-1)" texto={`${tasa(TASAS.baja)} al año`} valor={dolares(p.baja)} />
                      <Fila color="var(--tinta-3)" texto="Sin rendimiento" valor={dolares(p.sinRendimiento)} />
                    </CajaTooltip>
                  );
                }}
              />
              <Area
                dataKey="abanico"
                name="Abanico"
                stroke="none"
                fill="var(--serie-1)"
                fillOpacity={0.15}
                isAnimationActive={false}
                activeDot={false}
              />
              <Line
                dataKey="sinRendimiento"
                name="Sin rendimiento"
                stroke="var(--tinta-3)"
                strokeWidth={2}
                strokeDasharray="5 4"
                dot={false}
                isAnimationActive={false}
              />
              <Line
                dataKey="media"
                name="Centro"
                stroke="var(--serie-1)"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--superficie)" }}
                isAnimationActive={false}
              />
              {propia !== null && (
                <Line
                  dataKey="propia"
                  name="Tu tasa"
                  stroke="var(--serie-2)"
                  strokeWidth={2}
                  dot={false}
                  activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--superficie)" }}
                  isAnimationActive={false}
                />
              )}
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </div>

      <p className="text-xs text-[var(--tinta-3)]">
        Es un cálculo, no una predicción ni una recomendación: supone la misma rentabilidad todos los años, y en la
        bolsa hay años de pérdidas. El {tasa(TASAS.media)} es aproximadamente lo que ha dado el S&amp;P 500 a largo
        plazo, con los dividendos reinvertidos. Las cifras son dólares de ese año; el equivalente de hoy descuenta un{" "}
        {tasa(INFLACION)} de inflación al año. Parte de lo que tienes ahora ({dolares(valorInicial)}). Como
        referencia, en los últimos 12 meses aportaste de media {dolares(aporteMedio)} al mes.
      </p>
    </div>
  );
}

/* ------------------------------------------------------------- precio de una accion */

type FilaPrecio = { t: string; precio: number; compra?: number; venta?: number; marcas: MarcaOperacion[] };

/** Cada operacion se pega al punto del grafico de su dia (o de su momento). */
function conMarcas(datos: PreciosAccion): FilaPrecio[] {
  const filas: FilaPrecio[] = datos.puntos.map((p) => ({ ...p, marcas: [] }));
  if (!filas.length) return filas;
  for (const m of datos.marcas) {
    let i = filas.findIndex((f) => f.t >= m.t);
    if (i === -1) i = filas.length - 1;
    const fila = filas[i];
    fila.marcas.push(m);
    if (m.precio !== null) {
      if (m.tipo === "compra") fila.compra = m.precio;
      else fila.venta = m.precio;
    }
  }
  return filas;
}

function Triangulo({ cx, cy, arriba, color }: { cx?: number; cy?: number; arriba: boolean; color: string }) {
  if (cx === undefined || cy === undefined) return null;
  const d = arriba
    ? `M${cx} ${cy - 7} L${cx + 6} ${cy + 4} L${cx - 6} ${cy + 4} Z`
    : `M${cx} ${cy + 7} L${cx + 6} ${cy - 4} L${cx - 6} ${cy - 4} Z`;
  // Anillo del color de la superficie: el triangulo se lee aunque caiga sobre la linea.
  return <path d={d} fill={color} stroke="var(--superficie)" strokeWidth={2} />;
}

export function GraficoPrecio({ datos }: { datos: PreciosAccion }) {
  const intradia = datos.detalle === "intradia";
  if (!datos.puntos.length) {
    return (
      <Vacio
        titulo="Sin precios de esta acción"
        detalle="Configura las claves de Alpaca para ver su precio día a día; mientras tanto se usa el del último estado de cuenta."
      />
    );
  }
  const filas = conMarcas(datos);
  return (
    <div>
      <Leyenda
        items={[
          { color: "var(--serie-1)", texto: "Precio", forma: "linea" },
          { color: "var(--serie-3)", texto: "Compra", forma: "subir" },
          { color: "var(--serie-2)", texto: "Venta", forma: "bajar" },
        ]}
      />
      <div className="h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={filas} margin={{ top: 12, right: 12, bottom: 0, left: -8 }}>
            <CartesianGrid stroke="var(--rejilla)" vertical={false} />
            <XAxis
              dataKey="t"
              tick={EJE}
              tickLine={false}
              axisLine={{ stroke: "var(--eje)" }}
              tickFormatter={(t: string) => etiquetaTiempo(t, intradia)}
              minTickGap={32}
            />
            <YAxis
              tick={EJE}
              tickLine={false}
              axisLine={false}
              width={56}
              domain={["auto", "auto"]}
              tickFormatter={ejeDolares}
            />
            <Tooltip
              cursor={{ stroke: "var(--eje)", strokeWidth: 1 }}
              content={(props: unknown) => {
                const { active, payload, label } = props as {
                  active?: boolean;
                  payload?: { payload: FilaPrecio }[];
                  label?: string;
                };
                if (!active || !payload?.length) return null;
                const f = payload[0].payload;
                return (
                  <CajaTooltip>
                    <div className="mb-1 font-medium">{etiquetaCompleta(String(label), intradia)}</div>
                    <Fila color="var(--serie-1)" texto="Precio" valor={dolares(f.precio)} />
                    {f.marcas.map((m, i) => (
                      <Fila
                        key={i}
                        color={m.tipo === "compra" ? "var(--serie-3)" : "var(--serie-2)"}
                        texto={`${m.tipo === "compra" ? "Compraste" : "Vendiste"} ${m.cantidad?.toLocaleString("es-PE", { maximumFractionDigits: 5 }) ?? ""}${m.estado === "provisional" ? " (provisional)" : ""}`}
                        valor={`a ${dolares(m.precio)}`}
                      />
                    ))}
                  </CajaTooltip>
                );
              }}
            />
            <Line
              type="monotone"
              dataKey="precio"
              name="Precio"
              stroke="var(--serie-1)"
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--superficie)" }}
              isAnimationActive={false}
            />
            <Scatter
              dataKey="compra"
              name="Compra"
              isAnimationActive={false}
              shape={(p: { cx?: number; cy?: number }) => (
                <Triangulo cx={p.cx} cy={p.cy} arriba color="var(--serie-3)" />
              )}
            />
            <Scatter
              dataKey="venta"
              name="Venta"
              isAnimationActive={false}
              shape={(p: { cx?: number; cy?: number }) => (
                <Triangulo cx={p.cx} cy={p.cy} arriba={false} color="var(--serie-2)" />
              )}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------- dividendos de una accion */

export function BarrasDividendosAccion({ datos }: { datos: { mes: string; neto: number }[] }) {
  if (!datos.length) return <Vacio titulo="Esta acción no te ha pagado dividendos" />;
  const filas = datos.map((d) => ({ ...d, etiqueta: etiquetaMes(d.mes) }));
  return (
    <div className="h-48 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={filas} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
          <CartesianGrid stroke="var(--rejilla)" vertical={false} />
          <XAxis dataKey="etiqueta" tick={EJE} tickLine={false} axisLine={{ stroke: "var(--eje)" }} />
          <YAxis tick={EJE} tickLine={false} axisLine={false} width={48} />
          <Tooltip
            cursor={{ fill: "var(--superficie-2)" }}
            content={(props: unknown) => {
              const { active, payload, label } = props as {
                active?: boolean;
                payload?: { payload: (typeof filas)[number] }[];
                label?: string;
              };
              if (!active || !payload?.length) return null;
              return (
                <CajaTooltip>
                  <div className="mb-1 font-medium">{String(label)}</div>
                  <Fila color="var(--serie-1)" texto="Neto" valor={dolares(payload[0].payload.neto)} />
                </CajaTooltip>
              );
            }}
          />
          <Bar dataKey="neto" name="Neto" fill="var(--serie-1)" radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
