/**
 * Pestañas de Movimientos para lo que ya no cuenta: lo descartado y lo borrado.
 *
 * Son dos cosas distintas, y por eso dos listas:
 *
 *  - Descartados: movimientos del banco o del Excel que quitaste (o ignoraste en
 *    Por revisar). No se borraron: siguen guardados como ignorados para que el
 *    correo no los traiga de vuelta. "Volver a contar" los reactiva.
 *
 *  - Papelera: filas borradas de verdad. Tus registros manuales que eliminaste,
 *    las de un Excel cuya importacion deshiciste o lo que borre cualquier proceso.
 *    Las copia un trigger de la base de datos; "Restaurar" las devuelve tal cual.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, RefreshCw, RotateCcw, Trash2 } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { api, ErrorApi } from "../lib/api";
import type { Categoria, Direccion } from "../lib/api";
import { ETIQUETA_ORIGEN, fecha, fechaHora, importe } from "../lib/format";
import { Boton, Cargando, Etiqueta, Tarjeta, Vacio } from "./ui";

export type VistaMovimientos = "activos" | "descartados" | "papelera";

export function PestanasMovimientos({
  vista,
  onCambiar,
  descartados,
  borrados,
}: {
  vista: VistaMovimientos;
  onCambiar: (vista: VistaMovimientos) => void;
  descartados: number;
  borrados: number;
}) {
  const pestanas: { id: VistaMovimientos; texto: string; n?: number; icono?: LucideIcon }[] = [
    { id: "activos", texto: "Activos" },
    { id: "descartados", texto: "Descartados", n: descartados },
    { id: "papelera", texto: "Papelera", n: borrados, icono: Trash2 },
  ];
  return (
    <div
      role="tablist"
      aria-label="Vista de movimientos"
      className="mb-4 inline-flex flex-wrap gap-1 rounded-lg p-1"
      style={{ background: "var(--superficie-2)" }}
    >
      {pestanas.map(({ id, texto, n, icono: Icono }) => {
        const activa = vista === id;
        return (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={activa}
            onClick={() => onCambiar(id)}
            className="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition-colors"
            style={
              activa
                ? {
                    background: "var(--superficie)",
                    color: "var(--tinta)",
                    boxShadow: "0 0 0 1px var(--borde)",
                    fontWeight: 500,
                  }
                : { color: "var(--tinta-2)" }
            }
          >
            {Icono && <Icono size={14} />}
            {texto}
            {n ? <span className="tabular text-xs text-[var(--tinta-3)]">{n}</span> : null}
          </button>
        );
      })}
    </div>
  );
}

function concepto(texto: string | null | undefined): string {
  return texto ? texto.replace(/\b\w/g, (c) => c.toUpperCase()) : "—";
}

function signo(direccion: Direccion | null | undefined): string {
  return direccion === "ingreso" ? "+" : direccion === "gasto" ? "−" : "";
}

function Renglon({
  cuando,
  titulo,
  detalle,
  etiquetas,
  monto,
  moneda,
  direccion,
  accion,
}: {
  cuando: string;
  titulo: string;
  detalle: string;
  etiquetas?: React.ReactNode;
  monto: number;
  moneda?: string | null;
  direccion: Direccion | null | undefined;
  accion: React.ReactNode;
}) {
  return (
    <li
      className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t py-2.5 first:border-t-0"
      style={{ borderColor: "var(--borde)" }}
    >
      <span className="w-28 shrink-0 text-xs text-[var(--tinta-3)]">{cuando}</span>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium">{titulo}</div>
        <div className="flex flex-wrap items-center gap-1.5 pt-0.5 text-xs text-[var(--tinta-3)]">
          <span>{detalle}</span>
          {etiquetas}
        </div>
      </div>
      <span className="tabular w-24 shrink-0 text-right text-sm font-medium whitespace-nowrap">
        {signo(direccion)} {importe(monto, moneda)}
      </span>
      <div className="w-40 shrink-0 text-right">{accion}</div>
    </li>
  );
}

function MensajeError({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <p className="mb-3 text-sm" style={{ color: "var(--texto-malo)" }}>
      {error instanceof ErrorApi ? error.message : "No se pudo completar. Revisa que la app esté corriendo."}
    </p>
  );
}

/**
 * Recuperar un movimiento cambia las listas, los totales y la bandeja. Sin
 * refrescarlas, la fila restaurada seguia en pantalla como si no hubiera pasado
 * nada, y un segundo clic devolvia "Ese movimiento no esta en la papelera".
 */
function useRefrescarTrasRecuperar() {
  const qc = useQueryClient();
  return () => {
    for (const clave of ["movimientos", "papelera", "resumen", "revision", "mensual"]) {
      qc.invalidateQueries({ queryKey: [clave] });
    }
  };
}

export function VistaDescartados() {
  const refrescar = useRefrescarTrasRecuperar();
  const { data, isLoading } = useQuery({
    queryKey: ["movimientos", "descartados"],
    queryFn: () => api.movimientos({ estado: "ignorada", tamano: 200, orden: "fecha_desc" }),
  });
  const volver = useMutation({
    mutationFn: (id: number) => api.editarMovimiento(id, { status: "confirmada" }),
    onSettled: refrescar,
  });

  return (
    <Tarjeta
      titulo="Descartados"
      subtitulo="Movimientos que quitaste. No cuentan en ningún total y siguen guardados para que el correo no los traiga de vuelta."
    >
      <MensajeError error={volver.error} />
      {isLoading ? (
        <Cargando />
      ) : !data?.items.length ? (
        <Vacio
          titulo="No has descartado nada"
          detalle="Lo que quites en Movimientos o ignores en Por revisar aparece aquí, por si quieres volver a contarlo."
        />
      ) : (
        <>
          <ul>
            {data.items.map((m) => (
              <Renglon
                key={m.id}
                cuando={fecha(m.booking_date)}
                titulo={concepto(m.merchant) !== "—" ? concepto(m.merchant) : (m.description ?? "—")}
                detalle={[ETIQUETA_ORIGEN[m.source], m.account_name, m.category_name]
                  .filter(Boolean)
                  .join(" · ")}
                monto={m.amount}
                moneda={m.currency}
                direccion={m.direction}
                accion={
                  <Boton
                    onClick={() => volver.mutate(m.id)}
                    disabled={volver.isPending && volver.variables === m.id}
                  >
                    <RefreshCw size={14} /> Volver a contar
                  </Boton>
                }
              />
            ))}
          </ul>
          {data.total > data.items.length && (
            <p className="mt-3 text-xs text-[var(--tinta-3)]">
              Se muestran los {data.items.length} más recientes de {data.total}. Para uno concreto,
              en Activos filtra por Estado: Ignoradas y busca por comercio.
            </p>
          )}
        </>
      )}
    </Tarjeta>
  );
}

export function VistaPapelera({
  categorias,
  onVerActual,
}: {
  categorias: Categoria[];
  /** Lleva a Activos buscando ese comercio. */
  onVerActual: (busqueda: string) => void;
}) {
  const { data, isLoading } = useQuery({
    queryKey: ["papelera"],
    queryFn: () => api.papelera(),
  });
  const refrescar = useRefrescarTrasRecuperar();
  const restaurar = useMutation({ mutationFn: api.restaurarPapelera, onSettled: refrescar });
  const nombreCategoria = (id: number | null) =>
    id == null ? undefined : categorias.find((c) => c.id === id)?.name;

  return (
    <Tarjeta
      titulo="Papelera"
      subtitulo="Lo que se borró de verdad: tus registros que eliminaste, las filas de un Excel deshecho o lo que borre cualquier proceso. Restaurar lo devuelve tal cual estaba."
    >
      <MensajeError error={restaurar.error} />
      {isLoading ? (
        <Cargando />
      ) : !data?.length ? (
        <Vacio
          titulo="La papelera está vacía"
          detalle="Cuando se borre un movimiento, sea desde la app o desde cualquier otro proceso, queda aquí una copia para restaurarlo."
        />
      ) : (
        <ul>
          {data.map((e) => (
            <Renglon
              key={e.id}
              cuando={e.borrado_en ? fechaHora(e.borrado_en) : "—"}
              titulo={concepto(e.comercio)}
              detalle={[
                ETIQUETA_ORIGEN[e.origen] ?? e.origen,
                e.fecha ? fecha(e.fecha) : null,
                nombreCategoria(e.categoria_id),
              ]
                .filter(Boolean)
                .join(" · ")}
              etiquetas={
                <>
                  {e.editado_por_usuario && (
                    <Etiqueta
                      color="var(--bien)"
                      titulo="Lo habías registrado o corregido tú. Al restaurarlo vuelve protegido."
                    >
                      Tenía cambios tuyos
                    </Etiqueta>
                  )}
                  {e.tx_actual_id != null && (
                    <Etiqueta
                      color="var(--aviso)"
                      titulo="Volvió solo al procesar otra vez su correo. Restaurarlo lo contaría dos veces."
                    >
                      Ya volvió al sincronizar
                    </Etiqueta>
                  )}
                </>
              }
              monto={e.monto}
              moneda={e.moneda}
              direccion={e.direccion}
              accion={
                e.tx_actual_id != null ? (
                  <Boton variante="fantasma" onClick={() => onVerActual(e.comercio ?? "")}>
                    <ExternalLink size={14} /> Ver actual
                  </Boton>
                ) : (
                  <Boton
                    onClick={() => restaurar.mutate(e.id)}
                    disabled={restaurar.isPending && restaurar.variables === e.id}
                  >
                    <RotateCcw size={14} /> Restaurar
                  </Boton>
                )
              }
            />
          ))}
        </ul>
      )}
    </Tarjeta>
  );
}
