import { useEffect } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { TrendingDown, TrendingUp } from "lucide-react";
import { api, ErrorApi } from "../lib/api";
import type { PuntoPeriodo, SeriePeriodos } from "../lib/api";
import {
  hoyISO,
  primerDiaDelAnio,
  primerDiaDelMes,
  soles,
  ultimoDiaDelMes,
} from "../lib/format";
import { Encabezado } from "../App";
import { GraficoCategoriasPorPeriodo, GraficoMensual } from "../components/charts";
import { CamposRango, fechaValida, useParametros } from "../components/filtros";
import { Cargando, Selector, Tarjeta, Vacio } from "../components/ui";

type Agrupar = "mes" | "anio";
type Periodo = "12m" | "este_anio" | "anio_pasado" | "todo" | "rango";
type Rango = { desde?: string; hasta?: string };

const PERIODOS: Periodo[] = ["12m", "este_anio", "anio_pasado", "todo", "rango"];
const FILTROS = { agrupar: "mes", periodo: "12m", desde: "", hasta: "", categoria: "" };

/**
 * Tendencia responde "¿voy a mas o a menos?": como evolucionan tus ingresos y
 * gastos mes a mes o año a año, y en que categorias.
 *
 * El Panel responde otra pregunta, "¿como voy en este periodo?", con una foto de
 * un rango concreto. Por eso aqui cada periodo trae su variacion contra el
 * anterior de la misma serie: comparar agosto con julio dice mucho mas que
 * compararlo con un promedio que nadie ha vivido.
 *
 * Los filtros viven en la URL: el Panel enlaza aqui con ?categoria=<id>.
 */
export default function Tendencia() {
  const [f, cambiar] = useParametros(FILTROS);
  const agrupar: Agrupar = f.agrupar === "anio" ? "anio" : "mes";
  const periodo: Periodo = (PERIODOS as string[]).includes(f.periodo)
    ? (f.periodo as Periodo)
    : "12m";
  const rango = rangoDe(periodo, f.desde, f.hasta);

  const { data, isLoading, isPlaceholderData, error } = useQuery({
    queryKey: ["periodos", agrupar, rango.desde, rango.hasta],
    queryFn: () => api.resumenPeriodos(agrupar, rango.desde, rango.hasta),
    // Cambiar un filtro no desmonta la pantalla: se ve lo anterior, atenuado,
    // hasta que llega lo nuevo. Antes todo pasaba por "Cargando" y la tarjeta de
    // categorias perdia la categoria elegida.
    placeholderData: keepPreviousData,
  });

  function elegirPeriodo(valor: Periodo) {
    if (valor === "rango") {
      cambiar({
        periodo: valor,
        desde: rango.desde ?? primerDiaDelAnio(),
        hasta: rango.hasta ?? hoyISO(),
      });
    } else {
      cambiar({ periodo: valor, desde: "", hasta: "" });
    }
  }

  const conDatos = data?.periodos.filter((p) => p.movimientos > 0) ?? [];
  const t = data?.totales;
  const unidad = agrupar === "mes" ? "mes" : "año";

  return (
    <div className="p-4 md:p-6">
      <Encabezado
        titulo="Tendencia"
        descripcion="¿Vas a más o a menos? Cómo evolucionan tus ingresos y gastos. Para la foto de un periodo concreto, usa el Panel."
        acciones={
          <>
            <Selector
              value={agrupar}
              onChange={(e) => cambiar({ agrupar: e.target.value })}
              className="w-32"
              aria-label="Agrupar por"
            >
              <option value="mes">Por mes</option>
              <option value="anio">Por año</option>
            </Selector>
            <Selector
              value={periodo}
              onChange={(e) => elegirPeriodo(e.target.value as Periodo)}
              className="w-48"
              aria-label="Periodo"
            >
              <option value="12m">Últimos 12 meses</option>
              <option value="este_anio">Este año</option>
              <option value="anio_pasado">Año pasado</option>
              <option value="todo">Todo mi historial</option>
              <option value="rango">Rango a medida…</option>
            </Selector>
          </>
        }
      />

      {periodo === "rango" && (
        <CamposRango
          desde={rango.desde ?? primerDiaDelAnio()}
          hasta={rango.hasta ?? hoyISO()}
          onAplicar={(r) => cambiar(r)}
        />
      )}

      {isLoading ? (
        <Cargando />
      ) : error ? (
        // Sin esto, un rango invalido (400) se pintaba como "no hay movimientos en
        // ese rango", que es una respuesta falsa a una pregunta que no se hizo.
        <Tarjeta>
          <Vacio
            titulo="No se pudo cargar la tendencia"
            detalle={
              error instanceof ErrorApi
                ? error.message
                : "Verifica que el contenedor este corriendo."
            }
          />
        </Tarjeta>
      ) : !data || !conDatos.length ? (
        <Tarjeta>
          <Vacio
            titulo="No hay movimientos en ese rango"
            detalle="Prueba con otro periodo, o sincroniza el correo para traer mas historial."
          />
        </Tarjeta>
      ) : (
        <div
          className={`transition-opacity ${isPlaceholderData ? "opacity-60" : ""}`}
          aria-busy={isPlaceholderData}
        >
          {t && (
            <div className="mb-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Dato titulo="Gasto total" valor={soles(t.gasto)} />
              <Dato
                titulo={`Gasto promedio por ${unidad}`}
                valor={soles(t.promedio)}
                pie={`sobre ${t.periodos_con_datos} ${
                  agrupar === "mes" ? "meses" : "años"
                } con movimientos`}
              />
              <Dato
                titulo={agrupar === "mes" ? "Mes mas caro" : "Año mas caro"}
                valor={t.mayor ? soles(t.mayor.gasto) : "—"}
                pie={t.mayor?.etiqueta}
              />
              <Dato titulo="Movimientos" valor={String(t.movimientos)} />
            </div>
          )}

          <Tarjeta
            titulo={`Ingresos y gastos por ${unidad}`}
            subtitulo="Los periodos sin movimientos salen en cero, no desaparecen"
          >
            <GraficoMensual datos={data.periodos} />
          </Tarjeta>

          <div className="mt-5">
            <TarjetaCategorias
              agrupar={agrupar}
              rango={rango}
              base={data}
              basePendiente={isPlaceholderData}
              categoria={f.categoria}
              onCategoria={(categoria) => cambiar({ categoria })}
            />
          </div>

          <div className="mt-5">
            <Tarjeta titulo="Detalle" subtitulo="El mismo dato en numeros, por si quieres cotejarlo">
              <TablaPeriodos periodos={conDatos} />
            </Tarjeta>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Gasto por categoria a lo largo del tiempo, con su propio filtro.
 *
 * El filtro vive en la tarjeta y no en el encabezado: el resto de la pantalla
 * responde "cuanto gasto en total" y no debe moverse al mirar una categoria.
 * Las opciones salen de lo que tiene gasto en el rango, categorias y sus
 * subcategorias: ofrecer una sin datos llevaria a una grafica vacia.
 */
function TarjetaCategorias({
  agrupar,
  rango,
  base,
  basePendiente,
  categoria,
  onCategoria,
}: {
  agrupar: Agrupar;
  rango: Rango;
  base: SeriePeriodos;
  /** La serie base todavia es la del filtro anterior (esta llegando la nueva). */
  basePendiente: boolean;
  categoria: string;
  onCategoria: (categoria: string) => void;
}) {
  const opciones = base.arbol_categorias;
  const valida =
    opciones.some((c) => String(c.id) === categoria) ||
    opciones.some((c) => c.subcategorias.some((s) => String(s.id) === categoria));
  const filtro = valida ? categoria : "";

  // Una categoria sin gastos en el rango nuevo (o un enlace viejo) se quita de la
  // URL. Si solo se escondiera, volveria a activarse sola al regresar a un rango
  // donde si tiene, sin que el selector lo mostrara. Solo se decide con los datos
  // definitivos, nunca con los del rango anterior.
  useEffect(() => {
    if (categoria && !valida && !basePendiente) onCategoria("");
  }, [categoria, valida, basePendiente, onCategoria]);

  const { data, isLoading, isPlaceholderData, error } = useQuery({
    queryKey: ["periodos", agrupar, rango.desde, rango.hasta, filtro],
    queryFn: () => api.resumenPeriodos(agrupar, rango.desde, rango.hasta, filtro),
    enabled: filtro !== "",
    // Al pasar de una categoria a otra se sigue viendo la anterior hasta que
    // llega la nueva, en vez de parpadear con el "Cargando".
    placeholderData: keepPreviousData,
  });
  const serie = filtro ? data : base;
  const actualizando = filtro !== "" && isPlaceholderData;

  // El titulo describe lo que se VE, no lo que se acaba de elegir: mientras
  // llegan los datos nuevos no puede decir "Delivery" encima de Alimentacion.
  const mostrada = serie?.categoria_id ?? null;
  const raiz = opciones.find((c) => c.id === mostrada);
  const padre = opciones.find((c) => c.subcategorias.some((s) => s.id === mostrada));
  const sub = padre?.subcategorias.find((s) => s.id === mostrada);

  const periodo = agrupar === "mes" ? "mes a mes" : "año a año";
  const titulo = raiz
    ? `${raiz.nombre} por subcategoria, ${periodo}`
    : sub
      ? `${sub.nombre}, ${periodo}`
      : `Gasto por categoria, ${periodo}`;
  const subtitulo = sub
    ? `Subcategoria de ${padre?.nombre}`
    : `Las ${raiz ? "subcategorias" : "categorias"} con mas gasto en el rango; el resto se agrupa en Otras`;

  return (
    <Tarjeta
      titulo={titulo}
      subtitulo={subtitulo}
      acciones={
        <div className="flex items-center gap-2">
          {actualizando && <span className="text-xs text-[var(--tinta-3)]">Actualizando…</span>}
          <Selector
            value={filtro}
            onChange={(e) => onCategoria(e.target.value)}
            className="w-56"
            aria-label="Filtrar por categoria"
          >
            <option value="">Todas las categorias</option>
            {opciones.flatMap((c) => [
              <option key={c.id} value={c.id}>
                {c.nombre}
              </option>,
              // Un <optgroup> no se puede elegir: la categoria tiene que ser una
              // opcion mas, y sus subcategorias van sangradas debajo.
              ...c.subcategorias.map((s) => (
                <option key={s.id} value={s.id}>
                  {"    "}
                  {s.nombre}
                </option>
              )),
            ])}
          </Selector>
        </div>
      }
    >
      {filtro && error ? (
        <Vacio
          titulo="No se pudo cargar la categoria"
          detalle={
            error instanceof ErrorApi ? error.message : "Verifica que el contenedor este corriendo."
          }
        />
      ) : filtro && isLoading ? (
        <Cargando />
      ) : (
        <div className={`transition-opacity ${actualizando ? "opacity-60" : ""}`}>
          <GraficoCategoriasPorPeriodo
            periodos={serie?.periodos ?? []}
            categorias={serie?.categorias ?? []}
          />
        </div>
      )}
    </Tarjeta>
  );
}

function rangoDe(periodo: Periodo, desde: string, hasta: string): Rango {
  const hoy = new Date();
  const anio = hoy.getFullYear();
  switch (periodo) {
    case "12m":
      // El mes en curso y los 11 anteriores, completos.
      return {
        desde: primerDiaDelMes(new Date(anio, hoy.getMonth() - 11, 1)),
        hasta: ultimoDiaDelMes(hoy),
      };
    case "este_anio":
      return { desde: `${anio}-01-01`, hasta: `${anio}-12-31` };
    case "anio_pasado":
      return { desde: `${anio - 1}-01-01`, hasta: `${anio - 1}-12-31` };
    case "rango":
      return {
        desde: fechaValida(desde) ? desde : primerDiaDelAnio(),
        hasta: fechaValida(hasta) ? hasta : hoyISO(),
      };
    default:
      // Sin fechas, el backend cubre desde tu primer movimiento hasta hoy.
      return { desde: undefined, hasta: undefined };
  }
}

function Dato({ titulo, valor, pie }: { titulo: string; valor: string; pie?: string }) {
  return (
    <div
      className="rounded-xl border p-4"
      style={{ borderColor: "var(--borde)", background: "var(--superficie)" }}
    >
      <div className="text-xs text-[var(--tinta-3)]">{titulo}</div>
      <div className="tabular mt-1 text-xl font-semibold">{valor}</div>
      {pie && <div className="mt-0.5 text-xs text-[var(--tinta-3)]">{pie}</div>}
    </div>
  );
}

function TablaPeriodos({ periodos }: { periodos: PuntoPeriodo[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-[var(--tinta-3)]">
            <th className="pb-2 pr-4 font-medium">Periodo</th>
            <th className="pb-2 pr-4 text-right font-medium">Gasto</th>
            <th className="pb-2 pr-4 text-right font-medium">Ingreso</th>
            <th className="pb-2 pr-4 text-right font-medium">Neto</th>
            <th className="pb-2 pr-4 text-right font-medium">Movs.</th>
            <th className="pb-2 text-right font-medium">vs. anterior</th>
          </tr>
        </thead>
        <tbody>
          {periodos.map((p) => (
            <tr key={p.periodo} className="border-t" style={{ borderColor: "var(--borde)" }}>
              <td className="py-2 pr-4">{p.etiqueta}</td>
              <td className="tabular py-2 pr-4 text-right">{soles(p.gasto)}</td>
              <td className="tabular py-2 pr-4 text-right text-[var(--tinta-3)]">
                {p.ingreso ? soles(p.ingreso) : "—"}
              </td>
              <td
                className="tabular py-2 pr-4 text-right"
                style={{ color: p.neto < 0 ? "var(--tinta-2)" : "var(--bien)" }}
              >
                {soles(p.neto)}
              </td>
              <td className="tabular py-2 pr-4 text-right text-[var(--tinta-3)]">
                {p.movimientos}
              </td>
              <td className="py-2 text-right">
                <Variacion pct={p.variacion} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Gastar menos es bueno: la flecha hacia abajo va en verde, no en rojo. */
function Variacion({ pct }: { pct: number | null }) {
  if (pct === null) return <span className="text-xs text-[var(--tinta-3)]">—</span>;
  const sube = pct > 0;
  const Icono = sube ? TrendingUp : TrendingDown;
  return (
    <span
      className="tabular inline-flex items-center gap-1 text-xs"
      style={{ color: sube ? "var(--critico)" : "var(--bien)" }}
    >
      <Icono size={12} />
      {sube ? "+" : ""}
      {pct}%
    </span>
  );
}
