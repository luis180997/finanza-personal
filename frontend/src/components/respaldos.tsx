/**
 * Estado de las copias de seguridad.
 *
 * Una copia que falla o que dejo de hacerse no puede quedarse solo en el log del
 * servidor: nadie lo mira hasta el dia que hay que restaurar, y ese dia ya es
 * tarde. Por eso hay una tarjeta con el detalle y un aviso arriba en todas las
 * pantallas cuando algo va mal.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { DatabaseBackup, ShieldCheck } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { fechaHora } from "../lib/format";
import { Aviso, Boton, Cargando, Tarjeta } from "./ui";

const CLAVE = ["respaldos"];

function useRespaldos() {
  return useQuery({ queryKey: CLAVE, queryFn: api.respaldos, refetchInterval: 10 * 60_000 });
}

/** Aviso en lo alto de cualquier pantalla si algo va mal con las copias. */
/**
 * "Lo borre a proposito": apaga el aviso de movimientos desaparecidos sin borrar
 * ninguna copia. Se pregunta antes: si en realidad fue una perdida, apagarlo sin
 * mirar es justo lo que no debe pasar.
 */
function useAceptarPerdida() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.aceptarPerdida(),
    onSettled: () => qc.invalidateQueries({ queryKey: CLAVE }),
  });
}

function BotonAceptarPerdida({ aceptar }: { aceptar: ReturnType<typeof useAceptarPerdida> }) {
  return (
    <button
      type="button"
      className="font-medium underline"
      disabled={aceptar.isPending}
      onClick={() => {
        const seguro = window.confirm(
          "¿Esos movimientos los borraste tú a propósito? El aviso desaparece, pero las " +
            "copias que todavía los tienen se conservan por si acaso.",
        );
        if (seguro) aceptar.mutate();
      }}
    >
      Lo borré a propósito
    </button>
  );
}

export function AvisoRespaldos() {
  const { data } = useRespaldos();
  const aceptar = useAceptarPerdida();
  if (!data?.alertas.length) return null;
  return (
    <div className="px-4 pt-4 md:px-6">
      <Aviso tono="critico">
        <b>Copias de seguridad:</b> {data.alertas[0]}{" "}
        <Link to="/ajustes" className="underline">
          Ver detalle
        </Link>
        {data.perdida_sin_aceptar && (
          <>
            {" · "}
            <BotonAceptarPerdida aceptar={aceptar} />
          </>
        )}
      </Aviso>
    </div>
  );
}

function megas(bytes: number): string {
  return `${(bytes / 1e6).toFixed(1)} MB`;
}

export function TarjetaRespaldos() {
  const qc = useQueryClient();
  const { data, isLoading } = useRespaldos();
  const aceptar = useAceptarPerdida();
  const crear = useMutation({
    mutationFn: () => api.crearRespaldo(),
    onSettled: () => qc.invalidateQueries({ queryKey: CLAVE }),
  });

  return (
    <Tarjeta
      titulo="Copias de seguridad"
      subtitulo={
        data
          ? data.activo
            ? `Automáticas cada ${data.cada_dias} día(s), en ${data.carpeta}`
            : `Sin copias automáticas (RESPALDO_CADA_DIAS=0). Carpeta: ${data.carpeta}`
          : undefined
      }
    >
      {isLoading || !data ? (
        <Cargando />
      ) : (
        <div className="space-y-3">
          {data.alertas.map((alerta) => (
            <Aviso key={alerta} tono="critico">
              {alerta}
            </Aviso>
          ))}
          {data.perdida_sin_aceptar && (
            <p className="text-sm">
              <BotonAceptarPerdida aceptar={aceptar} />
            </p>
          )}

          <div className="flex items-center gap-2 text-sm">
            <ShieldCheck
              size={16}
              style={{ color: data.ultimo ? "var(--bien)" : "var(--tinta-3)" }}
            />
            {data.ultimo ? (
              <span>
                Última: <b>{fechaHora(data.ultimo.fecha)}</b>
                {data.ultimo.movimientos != null && ` · ${data.ultimo.movimientos} movimientos`}
              </span>
            ) : (
              <span>Todavía no hay ninguna copia.</span>
            )}
          </div>

          {data.respaldos.length > 0 && (
            <ul className="space-y-1 text-xs text-[var(--tinta-2)]">
              {data.respaldos.slice(0, 6).map((r) => (
                <li key={r.archivo} className="flex justify-between gap-2">
                  <span>{fechaHora(r.fecha)}</span>
                  <span className="tabular text-[var(--tinta-3)]">
                    {r.movimientos != null ? `${r.movimientos} mov. · ` : ""}
                    {megas(r.bytes)}
                  </span>
                </li>
              ))}
              {data.respaldos.length > 6 && (
                <li className="text-[var(--tinta-3)]">y {data.respaldos.length - 6} más</li>
              )}
            </ul>
          )}

          <Boton onClick={() => crear.mutate()} disabled={crear.isPending}>
            <DatabaseBackup size={15} />
            {crear.isPending ? "Copiando…" : "Hacer una copia ahora"}
          </Boton>
          {crear.isError && (
            <p className="text-xs" style={{ color: "var(--texto-malo)" }}>
              {(crear.error as Error).message}
            </p>
          )}
          <p className="text-xs text-[var(--tinta-3)]">
            Se guardan las más recientes y la última de cada día, semana y mes. Una copia con
            claramente más movimientos que la última no se borra nunca sola.
          </p>
        </div>
      )}
    </Tarjeta>
  );
}
