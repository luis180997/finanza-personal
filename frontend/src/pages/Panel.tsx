import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { AlertTriangle, ArrowRight } from "lucide-react";
import { api, ErrorApi } from "../lib/api";
import type { Resumen } from "../lib/api";
import {
  fecha,
  haceDias,
  hoyISO,
  primerDiaDelAnio,
  primerDiaDelMes,
  soles,
  ultimoDiaDelAnio,
  ultimoDiaDelMes,
} from "../lib/format";
import { Encabezado } from "../App";
import {
  BarraNecesidad,
  GraficoCategorias,
  GraficoRitmo,
  ListaRanking,
} from "../components/charts";
import { CamposRango, fechaValida, useParametros } from "../components/filtros";
import { Cargando, Indicador, Selector, Tarjeta, Vacio } from "../components/ui";

type Preset = "mes" | "mes_pasado" | "7d" | "30d" | "90d" | "anio" | "personalizado";
const PRESETS: Preset[] = ["mes", "mes_pasado", "7d", "30d", "90d", "anio", "personalizado"];

const COLOR_ESTADO: Record<string, string> = {
  en_curso: "var(--bien)",
  en_riesgo: "var(--aviso)",
  excedido: "var(--critico)",
};

function rangoDe(
  preset: Preset,
  aMedida: { desde: string; hasta: string },
): { desde: string; hasta: string; etiqueta: string } {
  const hoy = new Date();
  switch (preset) {
    case "anio":
      return {
        desde: primerDiaDelAnio(),
        hasta: ultimoDiaDelAnio(),
        etiqueta: "Este año",
      };
    case "personalizado":
      return { ...aMedida, etiqueta: "Rango a medida" };
    case "mes_pasado": {
      const d = new Date(hoy.getFullYear(), hoy.getMonth() - 1, 1);
      return {
        desde: primerDiaDelMes(d),
        hasta: ultimoDiaDelMes(d),
        etiqueta: "Mes pasado",
      };
    }
    case "7d":
      return { desde: haceDias(6), hasta: hoyISO(), etiqueta: "Ultimos 7 dias" };
    case "30d":
      return { desde: haceDias(29), hasta: hoyISO(), etiqueta: "Ultimos 30 dias" };
    case "90d":
      return { desde: haceDias(89), hasta: hoyISO(), etiqueta: "Ultimos 90 dias" };
    default:
      return {
        desde: primerDiaDelMes(),
        hasta: ultimoDiaDelMes(),
        etiqueta: "Este mes",
      };
  }
}

/**
 * El Panel responde "¿como voy en este periodo?": la foto de un rango concreto.
 *
 * La evolucion ("¿voy a mas o a menos?") esta en Tendencia. Por eso aqui ya no
 * hay grafico de los ultimos 12 meses, que ademas no obedecia al filtro de
 * periodo, y cada categoria enlaza a su evolucion alli.
 */
export default function Panel() {
  const navigate = useNavigate();
  const [filtros, cambiar] = useParametros({ periodo: "mes", desde: "", hasta: "" });
  const preset: Preset = (PRESETS as string[]).includes(filtros.periodo)
    ? (filtros.periodo as Preset)
    : "mes";
  const aMedida = {
    desde: fechaValida(filtros.desde) ? filtros.desde : primerDiaDelMes(),
    hasta: fechaValida(filtros.hasta) ? filtros.hasta : hoyISO(),
  };
  const rango = rangoDe(preset, aMedida);

  const { data, isLoading, isPlaceholderData, error } = useQuery({
    queryKey: ["resumen", rango.desde, rango.hasta],
    queryFn: () => api.resumen(rango.desde, rango.hasta),
    // Cambiar el periodo no desmonta la pantalla: se ve el anterior, atenuado,
    // hasta que llega el nuevo. Antes todo pasaba por "Cargando" y los campos de
    // fecha se desmontaban mientras escribias en ellos.
    placeholderData: keepPreviousData,
  });

  function elegirPreset(valor: Preset) {
    // Al pasar a rango a medida, los campos arrancan con el periodo que se ve.
    if (valor === "personalizado") {
      cambiar({ periodo: valor, desde: rango.desde, hasta: rango.hasta });
    } else {
      cambiar({ periodo: valor, desde: "", hasta: "" });
    }
  }

  return (
    <div className="p-4 md:p-6">
      <Encabezado
        titulo="Panel"
        descripcion={`${rango.etiqueta} · ${fecha(rango.desde)} a ${fecha(rango.hasta)}`}
        acciones={
          <Selector
            value={preset}
            onChange={(e) => elegirPreset(e.target.value as Preset)}
            className="w-44"
            aria-label="Periodo"
          >
            <option value="mes">Este mes</option>
            <option value="mes_pasado">Mes pasado</option>
            <option value="7d">Ultimos 7 dias</option>
            <option value="30d">Ultimos 30 dias</option>
            <option value="90d">Ultimos 90 dias</option>
            <option value="anio">Este año</option>
            <option value="personalizado">Rango a medida…</option>
          </Selector>
        }
      />

      {/* Los campos de fecha solo salen con el rango a medida: siempre visibles
          ocupan sitio y casi nunca se tocan. */}
      {preset === "personalizado" && (
        <CamposRango
          desde={aMedida.desde}
          hasta={aMedida.hasta}
          onAplicar={(r) => cambiar({ desde: r.desde, hasta: r.hasta })}
        />
      )}

      {isLoading ? (
        <Cargando />
      ) : error ? (
        // No todo error es que el backend este caido: un rango invalido devuelve
        // un 400 con el motivo escrito. Decir "arranca el contenedor" mandaba a
        // buscar un problema que no existe.
        <Vacio
          titulo={
            error instanceof ErrorApi
              ? "No se pudo cargar el resumen"
              : "No se pudo conectar con el backend"
          }
          detalle={
            error instanceof ErrorApi
              ? error.message
              : "Verifica que el contenedor este corriendo."
          }
        />
      ) : data ? (
        <div
          className={`transition-opacity ${isPlaceholderData ? "opacity-60" : ""}`}
          aria-busy={isPlaceholderData}
        >
          <ContenidoPanel
            data={data}
            onElegirCategoria={(id) => navigate(`/tendencia?categoria=${id}`)}
          />
        </div>
      ) : null}
    </div>
  );
}

function ContenidoPanel({
  data,
  onElegirCategoria,
}: {
  data: Resumen;
  onElegirCategoria: (id: number) => void;
}) {
  const k = data.kpis;

  return (
    <>
      {data.alertas.length > 0 && (
        <div className="mb-5 grid gap-2">
          {data.alertas.map((a, i) => (
            <div
              key={i}
              className="flex items-start gap-2 rounded-lg border px-3 py-2 text-sm"
              style={{ borderColor: "var(--borde)", background: "var(--superficie)" }}
            >
              <AlertTriangle
                size={15}
                className="mt-0.5 shrink-0"
                style={{ color: a.tipo === "fuga" ? "var(--critico)" : "var(--aviso)" }}
              />
              <span className="text-[var(--tinta-2)]">{a.texto}</span>
              {a.tipo === "revision" && (
                <Link
                  to="/revision"
                  className="ml-auto inline-flex shrink-0 items-center gap-1 text-xs font-medium"
                  style={{ color: "var(--serie-1)" }}
                >
                  Revisar <ArrowRight size={12} />
                </Link>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Cifras: un numero es mejor que un grafico cuando el dato es un numero */}
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Indicador
          etiqueta="Gastos del periodo"
          valor={soles(k.gastos)}
          variacion={k.variacion_gastos}
          variacionBuenaSiBaja
          detalle={
            // A mitad de periodo se compara con los mismos dias del anterior: contra
            // el anterior entero, el dia 13 siempre parecia que gastabas mucho menos.
            k.comparacion_parcial
              ? `vs ${soles(k.gastos_anterior_comparable)} a estas alturas del periodo anterior`
              : `vs ${soles(k.gastos_periodo_anterior)} el periodo anterior`
          }
          acento="var(--serie-2)"
        />
        <Indicador
          etiqueta="Ingresos"
          valor={soles(k.ingresos)}
          variacion={k.variacion_ingresos}
          acento="var(--serie-1)"
        />
        <Indicador
          etiqueta="Neto"
          valor={soles(k.neto)}
          detalle={k.ingresos ? `${k.tasa_ahorro}% de ahorro` : "sin ingresos registrados"}
          acento={k.neto >= 0 ? "var(--bien)" : "var(--critico)"}
        />
        <Indicador
          etiqueta="Gasto evitable"
          valor={soles(k.gasto_evitable)}
          detalle={`${k.pct_evitable}% del total`}
          acento="var(--critico)"
        />
      </div>

      <div className="mb-4 grid gap-4 lg:grid-cols-3">
        <Tarjeta
          className="lg:col-span-2"
          titulo="Ritmo de gasto"
          subtitulo={
            k.proyeccion_periodo !== null
              ? `Acumulado del periodo. Promedio S/ ${k.promedio_diario.toFixed(2)} por dia · proyeccion al cierre ${soles(k.proyeccion_periodo)}`
              : `Acumulado del periodo. Promedio S/ ${k.promedio_diario.toFixed(2)} por dia`
          }
        >
          <GraficoRitmo serie={data.serie_diaria} referencia={k.gastos_periodo_anterior} />
        </Tarjeta>

        <Tarjeta
          titulo="Esencial contra fuga"
          subtitulo="Lo que antes anotabas como 'gasto innecesario', ahora medido"
        >
          <BarraNecesidad datos={data.por_necesidad} />
        </Tarjeta>
      </div>

      <div className="mb-4 grid gap-4 lg:grid-cols-3">
        <Tarjeta
          className="lg:col-span-2"
          titulo="Gasto por categoria"
          subtitulo="Las 7 mayores; el resto se agrupa. Pulsa una barra para ver su evolución"
          acciones={
            <Link
              to="/tendencia"
              className="inline-flex items-center gap-1 text-xs font-medium"
              style={{ color: "var(--serie-1)" }}
            >
              Ver evolución <ArrowRight size={12} />
            </Link>
          }
        >
          <GraficoCategorias
            datos={data.por_categoria}
            onElegir={(c) => {
              if (c.id != null) onElegirCategoria(c.id);
            }}
          />
        </Tarjeta>

        <Tarjeta titulo="Detalle por subcategoria">
          <ListaRanking datos={data.por_subcategoria.slice(0, 8)} vacio="Sin datos" />
        </Tarjeta>
      </div>

      {(data.presupuestos.length > 0 || data.meta_ahorro) && (
        <div className="mb-4 grid gap-4 lg:grid-cols-3">
          {data.presupuestos.length > 0 && (
            <Tarjeta
              className="lg:col-span-2"
              titulo="Presupuesto del mes"
              subtitulo="Consumo de cada tope"
              acciones={
                <Link
                  to="/presupuesto"
                  className="text-xs font-medium"
                  style={{ color: "var(--serie-1)" }}
                >
                  Gestionar
                </Link>
              }
            >
              <ul className="space-y-3">
                {data.presupuestos.slice(0, 5).map((p) => (
                  <li key={p.categoria_id}>
                    <div className="flex items-baseline gap-2 text-sm">
                      <span
                        aria-hidden
                        className="h-2.5 w-2.5 shrink-0 rounded-full"
                        style={{ background: p.color }}
                      />
                      <span className="truncate">{p.categoria}</span>
                      <span className="tabular ml-auto">
                        <b>{soles(p.gastado)}</b>
                        <span className="text-[var(--tinta-3)]"> / {soles(p.tope)}</span>
                      </span>
                    </div>
                    <div
                      className="mt-1 h-1.5 w-full overflow-hidden rounded-full"
                      style={{ background: "var(--superficie-2)" }}
                    >
                      <div
                        className="h-full rounded-full"
                        style={{
                          width: `${Math.min(100, p.pct)}%`,
                          background: COLOR_ESTADO[p.estado],
                        }}
                      />
                    </div>
                  </li>
                ))}
              </ul>
            </Tarjeta>
          )}

          {data.meta_ahorro && (
            <Tarjeta titulo="Meta de ahorro" subtitulo="Monto fijo mensual">
              <div className="text-2xl font-semibold tracking-tight">
                {soles(data.meta_ahorro.ahorro_actual)}
              </div>
              <div className="text-xs text-[var(--tinta-3)]">
                de {soles(data.meta_ahorro.meta)}
              </div>
              <div
                className="mt-3 h-2.5 w-full overflow-hidden rounded-full"
                style={{ background: "var(--superficie-2)" }}
              >
                <div
                  className="h-full rounded-full"
                  style={{
                    width: `${Math.min(100, data.meta_ahorro.pct)}%`,
                    background: data.meta_ahorro.cumple_proyeccion
                      ? "var(--bien)"
                      : "var(--aviso)",
                  }}
                />
              </div>
              <p className="mt-3 text-sm text-[var(--tinta-2)]">
                {data.meta_ahorro.ahorro_proyectado === null
                  ? "Todavia no hay historial suficiente para proyectar el cierre."
                  : data.meta_ahorro.cumple_proyeccion
                    ? `Vas en camino: al cierre proyectas ${soles(data.meta_ahorro.ahorro_proyectado)}.`
                    : `Al ritmo actual cerraras en ${soles(data.meta_ahorro.ahorro_proyectado)}.`}
              </p>
              {data.meta_ahorro.dias_restantes > 0 && (
                <p className="mt-1 text-xs text-[var(--tinta-3)]">
                  Puedes gastar {soles(data.meta_ahorro.disponible_diario)} al dia durante
                  los {data.meta_ahorro.dias_restantes} dias que quedan.
                </p>
              )}
            </Tarjeta>
          )}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <Tarjeta titulo="Donde mas gastas" subtitulo="Top comercios del periodo">
          <ListaRanking datos={data.top_comercios} vacio="Aun no hay comercios detectados" />
        </Tarjeta>

        <Tarjeta titulo="Con que pagas" subtitulo="Yape, tarjeta o efectivo">
          <ListaRanking datos={data.por_medio_pago} vacio="Sin movimientos" />
        </Tarjeta>

        <Tarjeta titulo="De que cuenta sale" subtitulo="Los yapeos salen de BCP Debito">
          <ListaRanking datos={data.por_cuenta} vacio="Sin movimientos" />
        </Tarjeta>
      </div>

      <p className="mt-6 text-xs text-[var(--tinta-3)]">
        {k.num_movimientos} movimientos · {k.dias_con_gasto} dias con gasto ·{" "}
        {k.dias_sin_gasto} dias sin gastar · ticket promedio {soles(k.ticket_promedio)}. Las
        transferencias entre tus propias cuentas no cuentan como gasto ni como ingreso.
      </p>
    </>
  );
}
