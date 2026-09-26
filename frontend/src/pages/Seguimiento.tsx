/**
 * Seguimiento: cuanto dinero tienes de verdad en cada fecha, y cuanto de ese cambio
 * explica lo que registraste.
 *
 * Entre dos cortes: diferencia real - efecto del dolar - registrado = descuadre.
 * Un descuadre cerca de cero es la señal de que no se te escapa nada. Positivo:
 * tu dinero crecio mas de lo registrado (un ingreso sin anotar). Negativo: crecio
 * menos (un gasto sin anotar).
 */
import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Trash2, Upload, X } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, ErrorApi } from "../lib/api";
import type {
  CorteNuevo,
  CorteSeguimiento,
  Moneda,
  ProyeccionSeguimiento,
  SaldoSeguimiento,
} from "../lib/api";
import { ejeSoles, fecha, hoyISO, importe, leerMonto, soles } from "../lib/format";
import { Encabezado } from "../App";
import {
  Aviso,
  Boton,
  Campo,
  Cargando,
  Entrada,
  Etiqueta,
  Indicador,
  Selector,
  Tarjeta,
  Vacio,
} from "../components/ui";

const CLAVE = ["seguimiento"];
const EJE = { fontSize: 11, fill: "var(--tinta-3)" };
const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "set", "oct", "nov", "dic"];
const MESES_LARGOS = [
  "enero", "febrero", "marzo", "abril", "mayo", "junio",
  "julio", "agosto", "setiembre", "octubre", "noviembre", "diciembre",
];
const mesCorto = (iso: string) => `${MESES[Number(iso.slice(5, 7)) - 1]} ${iso.slice(2, 4)}`;
const diaYMes = (iso: string) => `${Number(iso.slice(8, 10))} ${MESES[Number(iso.slice(5, 7)) - 1]}`;
const mesLargo = (iso: string) => `${MESES_LARGOS[Number(iso.slice(5, 7)) - 1]} ${iso.slice(0, 4)}`;

/** Hasta S/ 100 es ruido (redondeos, comisiones); mas de S/ 500 es algo que se escapo. */
function colorDescuadre(v: number): string {
  const a = Math.abs(v);
  return a <= 100 ? "var(--bien)" : a <= 500 ? "var(--aviso)" : "var(--critico)";
}

/** Para texto: el amarillo de aviso no se lee sobre fondo claro. */
function colorTextoDescuadre(v: number): string {
  const a = Math.abs(v);
  return a <= 100 ? "var(--texto-bien)" : a <= 500 ? "var(--tinta)" : "var(--texto-malo)";
}

function conSigno(v: number): string {
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${soles(Math.abs(v))}`;
}

export default function Seguimiento() {
  const qc = useQueryClient();
  const formulario = useRef<HTMLDivElement>(null);
  const [editando, setEditando] = useState<CorteSeguimiento | null>(null);
  const { data, isLoading, error } = useQuery({ queryKey: CLAVE, queryFn: api.seguimiento });
  const [rango, setRango] = useState<Rango>("Todo");

  const borrar = useMutation({
    mutationFn: api.borrarCorte,
    onSuccess: () => {
      setEditando(null);
      qc.invalidateQueries({ queryKey: CLAVE });
    },
  });

  if (isLoading) return <div className="p-6"><Cargando /></div>;
  if (error || !data) {
    return (
      <div className="p-4 md:p-6">
        <Encabezado titulo="Seguimiento" />
        <Tarjeta>
          <Vacio
            titulo="No se pudo cargar el seguimiento"
            detalle={error instanceof ErrorApi ? error.message : "Verifica que la app este corriendo."}
          />
        </Tarjeta>
      </div>
    );
  }

  const { cortes, resumen } = data;
  const recientes = [...cortes].reverse();
  const ultimoTipoCambio = recientes.find((c) => c.tipo_cambio > 0)?.tipo_cambio ?? null;

  function editar(c: CorteSeguimiento) {
    setEditando(c);
    formulario.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  return (
    <div className="p-4 md:p-6">
      <Encabezado
        titulo="Seguimiento"
        descripcion="Cada cierto tiempo (por ejemplo, cada quincena) anotas cuánto tienes en cada cuenta: eso es un corte. La app lo compara con el corte anterior y con tus movimientos registrados. Un descuadre cerca de cero significa que no se te escapa nada."
      />

      {cortes.length > 0 && (
        <>
          <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Indicador
              etiqueta="Tu dinero en el último corte"
              valor={soles(resumen.total_actual ?? 0)}
              detalle={resumen.fecha_actual ? fecha(resumen.fecha_actual) : undefined}
              acento="var(--serie-1)"
            />
            <Indicador
              etiqueta="Descuadre del último periodo"
              valor={resumen.descuadre_ultimo === null ? "—" : conSigno(resumen.descuadre_ultimo)}
              detalle="cero = registraste todo"
              acento={resumen.descuadre_ultimo === null ? undefined : colorDescuadre(resumen.descuadre_ultimo)}
            />
            <Indicador
              etiqueta="Descuadre medio (últimos 6)"
              valor={resumen.descuadre_medio_6 === null ? "—" : soles(resumen.descuadre_medio_6)}
              detalle="sin importar el signo"
              acento={resumen.descuadre_medio_6 === null ? undefined : colorDescuadre(resumen.descuadre_medio_6)}
            />
            <Indicador etiqueta="Cortes" valor={String(resumen.cortes)} />
          </div>

          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold">Evolución</h2>
            <SelectorRango valor={rango} onCambio={setRango} />
          </div>
          <div className="mb-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
            <div className="lg:col-span-2">
              <Tarjeta
                titulo="Tu dinero en el tiempo"
                subtitulo="Total de cada corte, en soles. La línea punteada es la estimación."
                className="h-full"
              >
                <GraficoTotal cortes={cortes} rango={rango} proyeccion={data.proyeccion} />
              </Tarjeta>
            </div>
            <TarjetaEstimacion proyeccion={data.proyeccion} />
            <div className="lg:col-span-3">
              <Tarjeta
                titulo="Descuadre por periodo"
                subtitulo="Arriba: creció más de lo registrado. Abajo: creció menos (gastos sin anotar)"
              >
                <GraficoDescuadre cortes={cortes} rango={rango} />
              </Tarjeta>
            </div>
          </div>
        </>
      )}

      {/* grid-cols-1 (minmax(0, 1fr)): sin el, la tabla de 760px ensancha la unica
          columna en el movil y toda la pagina se desborda. */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Tarjeta titulo="Por fecha" subtitulo="Pulsa una fila para ver el saldo de cada cuenta">
            {!cortes.length ? (
              <Vacio
                titulo="Todavía no hay cortes"
                detalle="Importa tu historial desde el Excel o anota tus saldos de hoy con el formulario."
              />
            ) : (
              <TablaCortes
                cortes={recientes}
                onEditar={editar}
                onBorrar={(c) => {
                  if (window.confirm(`¿Borrar el corte del ${fecha(c.fecha)}?`)) borrar.mutate(c.id);
                }}
              />
            )}
            {borrar.isError && (
              <p className="mt-2 text-xs" style={{ color: "var(--texto-malo)" }}>
                {(borrar.error as Error).message}
              </p>
            )}
          </Tarjeta>
        </div>

        <div className="space-y-4" ref={formulario}>
          <FormularioCorte
            key={editando?.id ?? "nuevo"}
            editando={editando}
            sugeridas={data.cuentas_sugeridas}
            ultimoTipoCambio={ultimoTipoCambio}
            ultimaFecha={cortes.at(-1)?.fecha ?? null}
            onListo={() => setEditando(null)}
          />
          <ImportarHistorial />
          <Aviso>
            <b>Cómo leerlo.</b> Diferencia real = lo que cambió tu dinero entre dos cortes.
            Registrado = tus ingresos menos tus gastos de ese periodo. Efecto dólar = lo que
            ganaron o perdieron tus dólares solo por el tipo de cambio. Lo que queda es el
            descuadre: si es negativo, hubo gastos que no registraste; si es positivo,
            ingresos (tu sueldo, lo que ganó una inversión).
          </Aviso>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------- graficos */
type Rango = "YTD" | "1A" | "Todo";

const RANGOS: { valor: Rango; texto: string }[] = [
  { valor: "YTD", texto: "YTD" },
  { valor: "1A", texto: "Último año" },
  { valor: "Todo", texto: "Todo" },
];

function aISO(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function aTiempo(iso: string): number {
  const [a, m, d] = iso.split("-").map(Number);
  return new Date(a, m - 1, d).getTime();
}

/** Desde que fecha muestra cada rango; null = todo el historial. */
function inicioDelRango(rango: Rango, hoy: string): string | null {
  const [a, m, d] = hoy.split("-").map(Number);
  if (rango === "YTD") return `${a}-01-01`;
  if (rango === "1A") return aISO(new Date(a - 1, m - 1, d));
  return null;
}

/** Hasta donde se dibuja la estimacion: proporcional al rango, para no aplastar lo real. */
function finDeLaEstimacion(rango: Rango, hoy: string): string {
  const [a, m, d] = hoy.split("-").map(Number);
  if (rango === "YTD") return `${a}-12-31`;
  const meses = rango === "1A" ? 6 : 12;
  return aISO(new Date(a, m - 1 + meses, d));
}

/**
 * Los cortes del rango mas el ultimo anterior como punto de partida: asi el cambio
 * del periodo se mide desde lo que tenias al empezarlo.
 */
function cortesDelRango(cortes: CorteSeguimiento[], inicio: string | null): CorteSeguimiento[] {
  if (!inicio) return cortes;
  const dentro = cortes.filter((c) => c.fecha >= inicio);
  const previo = cortes.filter((c) => c.fecha < inicio).at(-1);
  return previo ? [previo, ...dentro] : dentro;
}

/** Un tick por mes, o cada 2, 3, 6 o 12 meses para que no se amontonen. */
function ticksMensuales(desde: number, hasta: number): number[] {
  const inicio = new Date(desde);
  const meses: Date[] = [];
  for (
    let d = new Date(inicio.getFullYear(), inicio.getMonth() + 1, 1);
    d.getTime() <= hasta;
    d = new Date(d.getFullYear(), d.getMonth() + 1, 1)
  ) {
    meses.push(d);
  }
  if (meses.length < 2) return [desde, hasta];
  const paso = [1, 2, 3, 6, 12].find((p) => meses.length / p <= 7) ?? 12;
  return meses.filter((d) => d.getMonth() % paso === 0).map((d) => d.getTime());
}

function etiquetaTick(t: number): string {
  const iso = aISO(new Date(t));
  return iso.endsWith("-01") ? mesCorto(iso) : diaYMes(iso);
}

function SelectorRango({ valor, onCambio }: { valor: Rango; onCambio: (r: Rango) => void }) {
  return (
    <div
      role="group"
      aria-label="Periodo de los gráficos"
      className="inline-flex rounded-lg border p-0.5"
      style={{ borderColor: "var(--borde)", background: "var(--superficie)" }}
    >
      {RANGOS.map((r) => {
        const activo = r.valor === valor;
        return (
          <button
            key={r.valor}
            type="button"
            aria-pressed={activo}
            onClick={() => onCambio(r.valor)}
            className={`rounded-md px-3 py-1 text-xs ${
              activo ? "font-medium text-[var(--tinta)]" : "text-[var(--tinta-3)] hover:text-[var(--tinta-2)]"
            }`}
            style={activo ? { background: "var(--superficie-2)" } : undefined}
          >
            {r.texto}
          </button>
        );
      })}
    </div>
  );
}

interface PuntoTotal {
  t: number;
  total: number | null;
  estimado: number | null;
}

function InfoPunto({ active, payload }: { active?: boolean; payload?: { payload: PuntoTotal }[] }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  const real = p.total !== null;
  return (
    <div
      className="rounded-md border px-2.5 py-1.5 text-xs"
      style={{ background: "var(--superficie)", borderColor: "var(--borde-fuerte)" }}
    >
      <div className="text-[var(--tinta-3)]">{fecha(aISO(new Date(p.t)))}</div>
      <div className="tabular font-medium">{real ? soles(p.total!) : `≈ ${soles(p.estimado!)}`}</div>
      {!real && <div className="text-[var(--tinta-3)]">estimación</div>}
    </div>
  );
}

function GraficoTotal({
  cortes,
  rango,
  proyeccion,
}: {
  cortes: CorteSeguimiento[];
  rango: Rango;
  proyeccion: ProyeccionSeguimiento | null;
}) {
  const hoy = hoyISO();
  const visibles = cortesDelRango(cortes, inicioDelRango(rango, hoy));
  if (!visibles.length) return <Vacio titulo="No hay cortes en estas fechas" />;

  const fin = finDeLaEstimacion(rango, hoy);
  const estimados = (proyeccion?.meses ?? []).filter((p) => p.fecha <= fin);
  const primero = visibles[0];
  const ultimo = visibles[visibles.length - 1];
  const datos: PuntoTotal[] = [
    ...visibles.map((c) => ({
      t: aTiempo(c.fecha),
      total: c.total,
      // El ultimo corte tambien abre la linea punteada, para que las dos se unan.
      estimado: c === ultimo && estimados.length ? c.total : null,
    })),
    ...estimados.map((p) => ({ t: aTiempo(p.fecha), total: null, estimado: p.total })),
  ];
  const desde = datos[0].t;
  const hasta = datos[datos.length - 1].t;
  const tHoy = aTiempo(hoy);
  const cambio = ultimo.total - primero.total;
  const finEstimado = estimados.at(-1);

  return (
    <>
      <div className="h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={datos} margin={{ top: 12, right: 12, bottom: 0, left: -8 }}>
            <CartesianGrid stroke="var(--rejilla)" vertical={false} />
            <XAxis
              dataKey="t"
              type="number"
              scale="time"
              domain={[desde, hasta]}
              ticks={ticksMensuales(desde, hasta)}
              tickFormatter={etiquetaTick}
              tick={EJE}
              tickLine={false}
            />
            <YAxis
              tick={EJE}
              tickLine={false}
              axisLine={false}
              tickFormatter={ejeSoles}
              width={52}
              domain={[(min: number) => Math.max(0, Math.floor((min * 0.9) / 1000) * 1000), "auto"]}
            />
            {tHoy > desde && tHoy < hasta && (
              <ReferenceLine
                x={tHoy}
                stroke="var(--eje)"
                strokeDasharray="2 3"
                label={{ value: "hoy", position: "insideTopLeft", fill: "var(--tinta-3)", fontSize: 10 }}
              />
            )}
            <Tooltip content={<InfoPunto />} />
            <Line
              name="Total"
              dataKey="total"
              type="monotone"
              stroke="var(--serie-1)"
              strokeWidth={2}
              dot={visibles.length <= 12 ? { r: 3 } : false}
            />
            <Line
              name="Estimación"
              dataKey="estimado"
              type="linear"
              stroke="var(--serie-1)"
              strokeWidth={2}
              strokeDasharray="5 4"
              strokeOpacity={0.7}
              dot={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div
        className="mt-3 flex flex-wrap gap-x-6 gap-y-1 border-t pt-3 text-xs text-[var(--tinta-3)]"
        style={{ borderColor: "var(--borde)" }}
      >
        {visibles.length > 1 && (
          <span>
            Cambio desde el {fecha(primero.fecha)}:{" "}
            <b className="tabular" style={{ color: cambio >= 0 ? "var(--texto-bien)" : "var(--texto-malo)" }}>
              {conSigno(cambio)}
            </b>
          </span>
        )}
        {finEstimado && (
          <span>
            Estimado al {fecha(finEstimado.fecha)}:{" "}
            <b className="tabular text-[var(--tinta)]">≈ {soles(finEstimado.total)}</b>
          </span>
        )}
      </div>
    </>
  );
}

function TarjetaEstimacion({ proyeccion }: { proyeccion: ProyeccionSeguimiento | null }) {
  if (!proyeccion) {
    return (
      <Tarjeta titulo="Estimación" className="h-full">
        <Vacio
          titulo="Aún no hay cortes suficientes"
          detalle="Hacen falta al menos 3 cortes en los últimos 12 meses, repartidos en más de dos meses."
        />
      </Tarjeta>
    );
  }
  const hoy = hoyISO();
  const proximos = proyeccion.meses.filter((p) => p.fecha >= hoy).slice(0, 6);
  const finDeAnio = proyeccion.meses.find((p) => p.fecha === `${hoy.slice(0, 4)}-12-31`);
  const lista = finDeAnio && !proximos.includes(finDeAnio) ? [...proximos, finDeAnio] : proximos;
  const sube = proyeccion.ritmo_mensual >= 0;

  return (
    <Tarjeta titulo="Estimación" subtitulo="Si tu dinero sigue al ritmo del último año" className="h-full">
      <div className="text-xs text-[var(--tinta-3)]">Ritmo</div>
      <div className="tabular text-2xl font-semibold" style={{ color: sube ? "var(--texto-bien)" : "var(--texto-malo)" }}>
        {conSigno(proyeccion.ritmo_mensual)}
        <span className="ml-1 text-sm font-normal text-[var(--tinta-3)]">al mes</span>
      </div>

      <div className="mt-4 text-xs text-[var(--tinta-3)]">Tendrías a fin de…</div>
      <ul className="mt-1 text-sm">
        {lista.map((p) => (
          <li key={p.fecha} className="flex items-baseline justify-between border-t py-1.5 first:border-t-0" style={{ borderColor: "var(--borde)" }}>
            <span className={p === finDeAnio ? "font-medium" : "text-[var(--tinta-2)]"}>{mesLargo(p.fecha)}</span>
            <span className={`tabular ${p === finDeAnio ? "font-medium" : ""}`}>≈ {soles(p.total)}</span>
          </li>
        ))}
      </ul>

      <p className="mt-3 text-xs text-[var(--tinta-3)]">
        Tendencia de tus {proyeccion.cortes_usados} cortes desde el {fecha(proyeccion.desde)}. Es una
        guía, no una promesa: un gasto grande o un ingreso extra la cambian.
      </p>
    </Tarjeta>
  );
}

function GraficoDescuadre({ cortes, rango }: { cortes: CorteSeguimiento[]; rango: Rango }) {
  const inicio = inicioDelRango(rango, hoyISO());
  const datos = cortes
    .filter((c) => c.periodo && (!inicio || c.fecha >= inicio))
    .map((c) => ({ fecha: c.fecha, descuadre: c.periodo!.descuadre }));
  if (!datos.length) {
    return (
      <Vacio
        titulo={cortes.length > 1 ? "Ningún periodo termina en estas fechas" : "Hace falta un segundo corte para comparar"}
      />
    );
  }
  return (
    <div className="h-48 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={datos} margin={{ top: 8, right: 12, bottom: 0, left: -8 }}>
          <CartesianGrid stroke="var(--rejilla)" vertical={false} />
          <XAxis
            dataKey="fecha"
            tick={EJE}
            tickLine={false}
            tickFormatter={datos.length <= 12 ? diaYMes : mesCorto}
            minTickGap={28}
          />
          <YAxis tick={EJE} tickLine={false} axisLine={false} tickFormatter={ejeSoles} width={52} />
          <ReferenceLine y={0} stroke="var(--eje)" />
          <Tooltip
            formatter={(v: number) => [conSigno(v), "Descuadre"]}
            labelFormatter={(l: string) => fecha(l)}
            contentStyle={{ background: "var(--superficie)", borderColor: "var(--borde-fuerte)", fontSize: 12 }}
          />
          <Bar dataKey="descuadre" maxBarSize={18}>
            {datos.map((d) => (
              <Cell key={d.fecha} fill={colorDescuadre(d.descuadre)} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/* ---------------------------------------------------------------------- tabla */
function TablaCortes({
  cortes,
  onEditar,
  onBorrar,
}: {
  cortes: CorteSeguimiento[];
  onEditar: (c: CorteSeguimiento) => void;
  onBorrar: (c: CorteSeguimiento) => void;
}) {
  const [abierto, setAbierto] = useState<number | null>(null);
  return (
    <div className="-mx-4 overflow-x-auto">
      <table className="w-full min-w-[760px] text-sm">
        <thead>
          <tr className="text-left text-xs text-[var(--tinta-3)]">
            <th className="px-4 py-2 font-medium">Fecha</th>
            <th className="px-2 py-2 text-right font-medium">Total</th>
            <th className="px-2 py-2 text-right font-medium">Dif. real</th>
            <th className="px-2 py-2 text-right font-medium">Registrado</th>
            <th className="px-2 py-2 text-right font-medium">Efecto dólar</th>
            <th className="px-2 py-2 text-right font-medium">Descuadre</th>
            <th className="px-4 py-2" />
          </tr>
        </thead>
        <tbody>
          {cortes.map((c) => {
            const p = c.periodo;
            return (
              <FilaCorte
                key={c.id}
                c={c}
                abierto={abierto === c.id}
                onAlternar={() => setAbierto(abierto === c.id ? null : c.id)}
                onEditar={() => onEditar(c)}
                onBorrar={() => onBorrar(c)}
              >
                <td className="tabular px-2 py-2 text-right">{p ? conSigno(p.dif_real) : "—"}</td>
                <td className="tabular px-2 py-2 text-right" title={p ? `Ingresos ${soles(p.ingresos)} · Gastos ${soles(p.gastos)}` : undefined}>
                  {p ? conSigno(p.registrado) : "—"}
                </td>
                <td className="tabular px-2 py-2 text-right text-[var(--tinta-3)]">
                  {p && p.efecto_dolar ? conSigno(p.efecto_dolar) : "—"}
                </td>
                <td className="tabular px-2 py-2 text-right font-medium whitespace-nowrap" style={{ color: p ? colorTextoDescuadre(p.descuadre) : undefined }}>
                  {p && (
                    <span
                      aria-hidden
                      className="mr-1.5 inline-block h-2 w-2 rounded-full"
                      style={{ background: colorDescuadre(p.descuadre) }}
                    />
                  )}
                  {p ? conSigno(p.descuadre) : "—"}
                  {p?.sin_ingresos && p.descuadre > 100 && (
                    <div className="text-[10px] font-normal text-[var(--tinta-3)]">sin ingresos registrados</div>
                  )}
                </td>
              </FilaCorte>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function FilaCorte({
  c,
  abierto,
  onAlternar,
  onEditar,
  onBorrar,
  children,
}: {
  c: CorteSeguimiento;
  abierto: boolean;
  onAlternar: () => void;
  onEditar: () => void;
  onBorrar: () => void;
  children: React.ReactNode;
}) {
  return (
    <>
      <tr
        className="cursor-pointer border-t align-top hover:bg-[var(--superficie-2)]"
        style={{ borderColor: "var(--borde)" }}
        onClick={onAlternar}
      >
        <td className="px-4 py-2 whitespace-nowrap">
          {fecha(c.fecha)}
          {c.periodo && (
            <div className="text-[10px] text-[var(--tinta-3)]">{c.periodo.dias} días</div>
          )}
        </td>
        <td className="tabular px-2 py-2 text-right font-medium">{soles(c.total)}</td>
        {children}
        <td className="px-4 py-2 text-right whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
          <button onClick={onEditar} title="Editar" className="rounded-md p-1.5 hover:bg-[var(--superficie-2)]" style={{ color: "var(--tinta-3)" }}>
            <Pencil size={13} />
          </button>
          <button onClick={onBorrar} title="Borrar" className="rounded-md p-1.5 hover:bg-[var(--superficie-2)]" style={{ color: "var(--tinta-3)" }}>
            <Trash2 size={13} />
          </button>
        </td>
      </tr>
      {abierto && (
        <tr style={{ background: "var(--superficie-2)" }}>
          <td colSpan={7} className="px-4 py-2">
            <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs">
              {c.saldos.map((s) => (
                <span key={`${s.cuenta}-${s.moneda}`} className="tabular">
                  <span className="text-[var(--tinta-3)]">{s.cuenta}: </span>
                  {s.es_deuda ? "−" : ""}
                  {importe(s.monto, s.moneda)}
                </span>
              ))}
              {c.tipo_cambio > 0 && (
                <span className="text-[var(--tinta-3)]">Tipo de cambio {c.tipo_cambio.toFixed(2)}</span>
              )}
              {c.origen === "excel" && <Etiqueta>Del Excel</Etiqueta>}
            </div>
            {c.notas && <p className="mt-1 text-xs text-[var(--tinta-2)]">{c.notas}</p>}
          </td>
        </tr>
      )}
    </>
  );
}

/* ----------------------------------------------------------------- formulario */
interface FilaForm {
  clave: string;
  cuenta: string;
  moneda: Moneda;
  es_deuda: boolean;
  monto: string;
}

const GRUPOS: { titulo: string; incluye: (f: FilaForm) => boolean }[] = [
  { titulo: "Cuentas en soles", incluye: (f) => !f.es_deuda && f.moneda === "PEN" },
  { titulo: "Cuentas en dólares", incluye: (f) => !f.es_deuda && f.moneda === "USD" },
  { titulo: "Deudas (restan del total)", incluye: (f) => f.es_deuda },
];

const leer = (texto: string) => (texto.trim() === "" ? 0 : leerMonto(texto));

function FormularioCorte({
  editando,
  sugeridas,
  ultimoTipoCambio,
  ultimaFecha,
  onListo,
}: {
  editando: CorteSeguimiento | null;
  sugeridas: { cuenta: string; moneda: Moneda; es_deuda: boolean }[];
  ultimoTipoCambio: number | null;
  ultimaFecha: string | null;
  onListo: () => void;
}) {
  const qc = useQueryClient();
  const [fechaCorte, setFechaCorte] = useState(editando?.fecha ?? hoyISO());
  const [tipoCambio, setTipoCambio] = useState(
    editando ? (editando.tipo_cambio ? String(editando.tipo_cambio) : "") : ultimoTipoCambio ? String(ultimoTipoCambio) : "",
  );
  const [notas, setNotas] = useState(editando?.notas ?? "");
  const [filas, setFilas] = useState<FilaForm[]>(() =>
    (editando ? editando.saldos : sugeridas).map((s, i) => ({
      clave: `${i}-${s.cuenta}-${s.moneda}`,
      cuenta: s.cuenta,
      moneda: s.moneda,
      es_deuda: s.es_deuda,
      monto: editando ? String((s as SaldoSeguimiento).monto) : "",
    })),
  );
  const [anadiendo, setAnadiendo] = useState(false);
  const [nueva, setNueva] = useState<{ cuenta: string; moneda: Moneda; es_deuda: boolean }>({
    cuenta: "",
    moneda: "PEN",
    es_deuda: false,
  });
  const [error, setError] = useState<string | null>(null);

  const guardar = useMutation({
    mutationFn: (datos: CorteNuevo) =>
      editando ? api.editarCorte(editando.id, datos) : api.crearCorte(datos),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: CLAVE });
      onListo();
      if (!editando) setFilas((fs) => fs.map((f) => ({ ...f, monto: "" })));
    },
  });

  const cambio = leerMonto(tipoCambio);
  const cambioValido = Number.isFinite(cambio) && cambio > 0 ? cambio : 0;

  // Solo una vista previa: el total que cuenta lo calcula el servidor en centimos.
  let enSoles = 0;
  let dolares = 0;
  let deudas = 0;
  for (const f of filas) {
    const m = leer(f.monto);
    if (!Number.isFinite(m)) continue;
    const valor = f.moneda === "USD" ? m * cambioValido : m;
    if (f.es_deuda) deudas += valor;
    else if (f.moneda === "USD") dolares += m;
    else enSoles += m;
  }
  const total = enSoles + dolares * cambioValido - deudas;

  function cambiarMonto(clave: string, monto: string) {
    setFilas((fs) => fs.map((f) => (f.clave === clave ? { ...f, monto } : f)));
  }

  function anadir() {
    const cuenta = nueva.cuenta.trim();
    if (!cuenta) return;
    if (filas.some((f) => f.cuenta.toLowerCase() === cuenta.toLowerCase() && f.moneda === nueva.moneda)) {
      setError(`Ya está la cuenta ${cuenta} en ${nueva.moneda === "USD" ? "dólares" : "soles"}`);
      return;
    }
    setError(null);
    setFilas((fs) => [...fs, { clave: `${Date.now()}`, cuenta, moneda: nueva.moneda, es_deuda: nueva.es_deuda, monto: "" }]);
    setNueva({ cuenta: "", moneda: "PEN", es_deuda: false });
    setAnadiendo(false);
  }

  function enviar() {
    const saldos: SaldoSeguimiento[] = [];
    for (const f of filas) {
      // Una cuenta en blanco se guarda en 0: asi sigue apareciendo en el siguiente corte.
      const m = leer(f.monto);
      if (!Number.isFinite(m) || m < 0) {
        setError(`El saldo de ${f.cuenta} no es un número válido`);
        return;
      }
      saldos.push({ cuenta: f.cuenta, moneda: f.moneda, es_deuda: f.es_deuda, monto: m });
    }
    if (!saldos.length) {
      setError("Añade al menos una cuenta");
      return;
    }
    if (saldos.some((s) => s.moneda === "USD" && s.monto > 0) && !cambioValido) {
      setError("Tienes saldos en dólares: falta el precio del dólar");
      return;
    }
    setError(null);
    guardar.mutate({
      fecha: fechaCorte,
      tipo_cambio: cambioValido || null,
      notas: notas.trim() || null,
      saldos,
    });
  }

  return (
    <Tarjeta
      titulo={editando ? `Editar el corte del ${fecha(editando.fecha)}` : "Anotar tus saldos de hoy"}
      subtitulo={
        editando
          ? "Corrige lo que haga falta y guarda."
          : `Abre la app de cada banco y escribe cuánto tienes en cada cuenta.${
              ultimaFecha ? ` Se comparará con lo que tenías el ${fecha(ultimaFecha)}.` : ""
            }`
      }
      acciones={
        editando && (
          <Boton variante="fantasma" className="px-2 py-1 text-xs" onClick={onListo}>
            <X size={13} /> Cancelar
          </Boton>
        )
      }
    >
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-2">
          <Campo etiqueta="Fecha">
            <Entrada type="date" value={fechaCorte} onChange={(e) => setFechaCorte(e.target.value)} />
          </Campo>
          <Campo
            etiqueta="Precio del dólar (S/)"
            hint={!editando && ultimoTipoCambio ? `El del último corte; pon el de hoy` : undefined}
          >
            <Entrada inputMode="decimal" placeholder="3.40" value={tipoCambio} onChange={(e) => setTipoCambio(e.target.value)} className="tabular" />
          </Campo>
        </div>

        {filas.length === 0 && (
          <p className="text-xs text-[var(--tinta-3)]">
            Añade tus cuentas: bancos, efectivo, Hapi y la tarjeta de crédito como deuda.
          </p>
        )}

        {GRUPOS.map((g) => {
          const delGrupo = filas.filter(g.incluye);
          if (!delGrupo.length) return null;
          return (
            <section key={g.titulo}>
              <h3 className="mb-1.5 text-xs font-medium text-[var(--tinta-2)]">{g.titulo}</h3>
              <ul className="space-y-1.5">
                {delGrupo.map((f) => (
                  <li key={f.clave} className="flex items-center gap-2">
                    <span className="min-w-0 flex-1 truncate text-sm" title={f.cuenta}>
                      {f.cuenta}
                    </span>
                    {/* El ancho lo fija este envoltorio: Entrada siempre ocupa el 100%. */}
                    <div className="relative w-36 shrink-0">
                      <span className="pointer-events-none absolute inset-y-0 left-2.5 flex items-center text-xs text-[var(--tinta-3)]">
                        {f.moneda === "USD" ? "$" : "S/"}
                      </span>
                      <Entrada
                        inputMode="decimal"
                        placeholder="0.00"
                        value={f.monto}
                        onChange={(e) => cambiarMonto(f.clave, e.target.value)}
                        className="tabular text-right"
                        style={{ paddingLeft: "2rem" }}
                        aria-label={`Saldo de ${f.cuenta} (${f.moneda})`}
                      />
                    </div>
                    <button
                      type="button"
                      onClick={() => setFilas((fs) => fs.filter((x) => x.clave !== f.clave))}
                      title="Quitar esta cuenta (ya no la tienes)"
                      className="shrink-0 rounded-md p-1 hover:bg-[var(--superficie-2)]"
                      style={{ color: "var(--tinta-3)" }}
                    >
                      <X size={13} />
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          );
        })}

        {anadiendo ? (
          <div className="space-y-2 rounded-lg border p-3" style={{ borderColor: "var(--borde)" }}>
            <Campo etiqueta="Nombre de la cuenta nueva">
              <Entrada
                autoFocus
                placeholder="Ej.: Interbank"
                value={nueva.cuenta}
                onChange={(e) => setNueva({ ...nueva, cuenta: e.target.value })}
                onKeyDown={(e) => {
                  if (e.key === "Enter") anadir();
                }}
              />
            </Campo>
            <div className="flex flex-wrap items-center gap-3">
              <div className="w-36">
                <Selector value={nueva.moneda} onChange={(e) => setNueva({ ...nueva, moneda: e.target.value as Moneda })}>
                  <option value="PEN">En soles</option>
                  <option value="USD">En dólares</option>
                </Selector>
              </div>
              <label className="flex items-center gap-1.5 text-xs text-[var(--tinta-2)]">
                <input type="checkbox" checked={nueva.es_deuda} onChange={(e) => setNueva({ ...nueva, es_deuda: e.target.checked })} />
                Es una deuda (resta)
              </label>
            </div>
            <div className="flex gap-2">
              <Boton className="px-2 py-1 text-xs" onClick={anadir} disabled={!nueva.cuenta.trim()}>
                Añadir
              </Boton>
              <Boton variante="fantasma" className="px-2 py-1 text-xs" onClick={() => setAnadiendo(false)}>
                Cancelar
              </Boton>
            </div>
          </div>
        ) : (
          <Boton variante="fantasma" className="px-2 py-1 text-xs" onClick={() => setAnadiendo(true)}>
            <Plus size={13} /> Añadir otra cuenta
          </Boton>
        )}

        <Campo etiqueta="Notas">
          <Entrada value={notas} onChange={(e) => setNotas(e.target.value)} placeholder="Opcional" />
        </Campo>

        <div className="space-y-1 border-t pt-3 text-sm" style={{ borderColor: "var(--borde)" }}>
          <LineaTotal texto="En soles" valor={soles(enSoles)} />
          {dolares > 0 && (
            <LineaTotal
              texto={`En dólares ($${dolares.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} × ${cambioValido || "?"})`}
              valor={soles(dolares * cambioValido)}
            />
          )}
          {deudas > 0 && <LineaTotal texto="Deudas" valor={`−${soles(deudas)}`} />}
          <div className="flex items-baseline justify-between pt-1">
            <span className="font-medium">Total</span>
            <span className="tabular text-xl font-semibold">{soles(total)}</span>
          </div>
        </div>

        <Boton variante="primario" className="w-full" onClick={enviar} disabled={guardar.isPending}>
          {guardar.isPending ? "Guardando…" : editando ? "Guardar cambios" : "Guardar corte"}
        </Boton>
        {(error || guardar.isError) && (
          <p className="text-xs" style={{ color: "var(--texto-malo)" }}>
            {error ?? (guardar.error as Error).message}
          </p>
        )}
      </div>
    </Tarjeta>
  );
}

function LineaTotal({ texto, valor }: { texto: string; valor: string }) {
  return (
    <div className="flex items-baseline justify-between text-[var(--tinta-2)]">
      <span>{texto}</span>
      <span className="tabular">{valor}</span>
    </div>
  );
}

/* ------------------------------------------------------------------- importar */
function ImportarHistorial() {
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const importar = useMutation({
    mutationFn: api.importarSeguimiento,
    onSuccess: () => qc.invalidateQueries({ queryKey: CLAVE }),
  });

  return (
    <Tarjeta
      titulo="Importar historial desde Excel"
      subtitulo="Una hoja con Fecha, el tipo de cambio (Dólar) y una columna por cuenta, como 'BCP (S/)' o 'Hapi ($)'. Las fechas que ya existen no se duplican."
    >
      <input
        ref={input}
        type="file"
        accept=".xlsx,.xlsm"
        hidden
        onChange={(e) => {
          const archivo = e.target.files?.[0];
          if (archivo) importar.mutate(archivo);
          e.target.value = "";
        }}
      />
      <Boton onClick={() => input.current?.click()} disabled={importar.isPending}>
        <Upload size={15} /> {importar.isPending ? "Importando…" : "Elegir archivo"}
      </Boton>
      {importar.data && (
        <div className="mt-3 space-y-2 text-sm">
          <p>
            <b>{importar.data.creados}</b> corte(s) nuevos · {importar.data.ya_existian} ya existían
            <span className="text-[var(--tinta-3)]"> (hoja {importar.data.hoja})</span>
          </p>
          {importar.data.avisos.map((a) => (
            <Aviso key={a} tono="aviso">{a}</Aviso>
          ))}
        </div>
      )}
      {importar.isError && (
        <p className="mt-2 text-xs" style={{ color: "var(--texto-malo)" }}>
          {(importar.error as Error).message}
        </p>
      )}
    </Tarjeta>
  );
}
