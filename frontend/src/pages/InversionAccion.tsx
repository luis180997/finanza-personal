import { useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { api } from "../lib/api";
import type { OperacionInversion, RangoInversion } from "../lib/api";
import { dolares, fecha } from "../lib/format";
import { Encabezado } from "../App";
import { BarrasDividendosAccion, GraficoPrecio, SelectorRango } from "../components/inversiones";
import { Aviso, Cargando, Etiqueta, Indicador, Tarjeta, Vacio } from "../components/ui";
import { colorSigno } from "./Inversiones";

/** Una accion: su precio con tus compras y ventas encima, tu posicion y su historia. */
export default function InversionAccion() {
  const { simbolo = "" } = useParams();
  const [rango, setRango] = useState<RangoInversion>("1A");
  const detalle = useQuery({
    queryKey: ["inv", "accion", simbolo],
    queryFn: () => api.inversiones.accion(simbolo),
  });
  const precios = useQuery({
    queryKey: ["inv", "precios", simbolo, rango],
    queryFn: () => api.inversiones.precios(simbolo, rango),
    placeholderData: keepPreviousData,
  });

  const volver = (
    <Link
      to="/inversiones"
      className="inline-flex items-center gap-1.5 text-sm text-[var(--tinta-2)] hover:text-[var(--tinta)]"
    >
      <ArrowLeft size={14} /> Inversiones
    </Link>
  );

  if (detalle.isLoading) return <div className="p-4 md:p-6">{volver}<Cargando /></div>;
  if (detalle.error || !detalle.data) {
    return (
      <div className="space-y-4 p-4 md:p-6">
        {volver}
        <Aviso tono="critico">No se pudo cargar {simbolo}: {String(detalle.error)}</Aviso>
      </div>
    );
  }
  const d = detalle.data;
  const p = d.posicion;

  return (
    <div className="p-4 md:p-6">
      <div className="mb-3">{volver}</div>
      <Encabezado titulo={d.simbolo} descripcion={d.nombre ?? undefined} />
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Indicador
            etiqueta="Valor de tu posición"
            valor={p ? dolares(p.valor) : "—"}
            variacion={p?.variacion_dia_pct != null ? p.variacion_dia_pct * 100 : null}
            detalle={p ? `${p.cantidad.toLocaleString("es-PE", { maximumFractionDigits: 5 })} acciones a ${dolares(p.precio)}` : "Ya no tienes acciones"}
          />
          <Indicador
            etiqueta="Ganancia sin vender"
            valor={p ? dolares(p.ganancia) : "—"}
            variacion={p?.ganancia_pct != null ? p.ganancia_pct * 100 : null}
            detalle={p ? `costo ${dolares(p.costo)}` : undefined}
          />
          <Indicador
            etiqueta="Costo promedio"
            valor={p?.costo_promedio != null ? dolares(p.costo_promedio) : "—"}
            detalle="por acción, con comisiones"
          />
          <Indicador
            etiqueta="Ganancia ya realizada"
            valor={dolares(d.realizada)}
            detalle={`dividendos netos ${dolares(d.dividendos.neto)}`}
          />
        </div>

        <Tarjeta
          titulo="Precio"
          subtitulo={
            precios.data?.detalle === "intradia"
              ? "Durante la sesión"
              : "Al cierre de cada día, ajustado por splits: tus operaciones también"
          }
        >
          <div className="mb-2 flex">
            <SelectorRango valor={rango} onCambiar={setRango} />
          </div>
          <div style={{ opacity: precios.isPlaceholderData ? 0.6 : 1 }}>
            {precios.data ? <GraficoPrecio datos={precios.data} /> : <Cargando />}
          </div>
        </Tarjeta>

        <div className="grid gap-4 lg:grid-cols-3">
          <Tarjeta
            titulo="Dividendos"
            subtitulo={`Bruto ${dolares(d.dividendos.bruto)} · retenido ${dolares(d.dividendos.retencion)}`}
            className="min-w-0"
          >
            <BarrasDividendosAccion datos={d.dividendos.por_mes} />
          </Tarjeta>
          {/* min-w-0: sin el, la tabla ensancha la columna de la rejilla en vez de desplazarse */}
          <Tarjeta titulo="Operaciones" className="min-w-0 lg:col-span-2">
            <TablaOperaciones ops={d.operaciones} />
          </Tarjeta>
        </div>
      </div>
    </div>
  );
}

const TIPOS: Record<string, string> = {
  compra: "Compra",
  venta: "Venta",
  split: "Split",
  dividendo: "Dividendo",
  ajuste_impuesto: "Ajuste de retención",
  posicion_inicial: "Posición inicial",
};

const ESTADOS: Record<string, { texto: string; color: string; ayuda: string }> = {
  oficial: { texto: "Oficial", color: "var(--bien)", ayuda: "Figura en el estado de cuenta" },
  provisional: {
    texto: "Provisional",
    color: "var(--aviso)",
    ayuda: "Llegó por correo; la confirmará el estado de cuenta del mes",
  },
  descartada: {
    texto: "Descartada",
    color: "var(--tinta-3)",
    ayuda: "El estado de cuenta no la recoge (un correo repetido o una orden que no se ejecutó)",
  },
};

function hora(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleTimeString("es-PE", { hour: "2-digit", minute: "2-digit" });
}

function TablaOperaciones({ ops }: { ops: OperacionInversion[] }) {
  if (!ops.length) return <Vacio titulo="Sin operaciones" />;
  return (
    <div className="-mx-4 max-h-[420px] overflow-auto">
      <table className="w-full min-w-[640px] text-sm">
        <thead className="sticky top-0" style={{ background: "var(--superficie)" }}>
          <tr className="text-left text-xs text-[var(--tinta-3)]">
            <th className="px-4 py-2 font-medium">Fecha</th>
            <th className="px-2 py-2 font-medium">Tipo</th>
            <th className="px-2 py-2 text-right font-medium">Acciones</th>
            <th className="px-2 py-2 text-right font-medium">Precio</th>
            <th className="px-2 py-2 text-right font-medium">Importe</th>
            <th className="px-4 py-2 font-medium">Estado</th>
          </tr>
        </thead>
        <tbody>
          {ops.map((o) => {
            const estado = ESTADOS[o.estado];
            return (
              <tr
                key={o.id}
                className="border-t"
                style={{ borderColor: "var(--borde)", opacity: o.estado === "descartada" ? 0.55 : 1 }}
              >
                <td className="px-4 py-2 whitespace-nowrap">
                  <div title={o.fecha_estimada ? "Sin correo: deducida de la fecha de liquidación" : undefined}>
                    {fecha(o.fecha)}
                    {o.fecha_estimada && <span className="text-[var(--tinta-3)]"> ≈</span>}
                  </div>
                  {o.hora && <div className="text-xs text-[var(--tinta-3)]">{hora(o.hora)}</div>}
                </td>
                <td className="px-2 py-2">{TIPOS[o.tipo] ?? o.tipo}</td>
                <td className="tabular px-2 py-2 text-right">
                  {o.cantidad !== null ? o.cantidad.toLocaleString("es-PE", { maximumFractionDigits: 5 }) : "—"}
                </td>
                <td className="tabular px-2 py-2 text-right">{o.precio !== null ? dolares(o.precio) : "—"}</td>
                <td className="tabular px-2 py-2 text-right" style={{ color: colorSigno(o.monto) }}>
                  <div>{dolares(o.monto)}</div>
                  {o.retencion > 0 && (
                    <div className="text-xs text-[var(--tinta-3)]">retenido {dolares(o.retencion)}</div>
                  )}
                  {o.comision ? (
                    <div className="text-xs text-[var(--tinta-3)]">comisión {dolares(o.comision)}</div>
                  ) : null}
                </td>
                <td className="px-4 py-2" title={o.nota ?? estado?.ayuda}>
                  {estado && <Etiqueta color={estado.color} titulo={estado.ayuda}>{estado.texto}</Etiqueta>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

