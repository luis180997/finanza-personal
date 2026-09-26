import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileSpreadsheet, Sparkles, Trash2, Upload } from "lucide-react";
import { api, ErrorApi } from "../lib/api";
import type { AnalisisExcel, LoteImportacion } from "../lib/api";
import { fecha, fechaHora, soles } from "../lib/format";
import { Encabezado } from "../App";
import {
  Aviso,
  Boton,
  Campo,
  Etiqueta,
  Selector,
  Tarjeta,
  Vacio,
} from "../components/ui";

/**
 * Importacion en dos pasos: primero ANALIZAR (no escribe nada) y luego
 * confirmar. Importar cuatro anios de datos a ciegas y descubrir despues que el
 * mapeo estaba mal es justo el error que este flujo evita.
 */
export default function Importar() {
  const qc = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);

  const [archivo, setArchivo] = useState<File | null>(null);
  const [hoja, setHoja] = useState<string>("");
  const [cuentaId, setCuentaId] = useState<number | "">("");
  const [usarObs, setUsarObs] = useState(true);
  const [analisis, setAnalisis] = useState<AnalisisExcel | null>(null);
  const [arrastrando, setArrastrando] = useState(false);

  const { data: cuentas } = useQuery({ queryKey: ["cuentas"], queryFn: api.cuentas });
  const { data: lotes } = useQuery({
    queryKey: ["lotes-importacion"],
    queryFn: api.lotesImportacion,
  });

  function refrescar() {
    qc.invalidateQueries({ queryKey: ["lotes-importacion"] });
    qc.invalidateQueries({ queryKey: ["movimientos"] });
    qc.invalidateQueries({ queryKey: ["resumen"] });
    qc.invalidateQueries({ queryKey: ["mensual"] });
  }

  const analizar = useMutation({
    mutationFn: ({ f, h }: { f: File; h?: string }) => api.analizarExcel(f, h),
    onSuccess: (r) => {
      setAnalisis(r);
      setHoja(r.hoja);
    },
  });

  const importar = useMutation({
    mutationFn: () =>
      api.importarExcel(archivo!, {
        hoja: hoja || undefined,
        cuenta_id: cuentaId === "" ? null : cuentaId,
        usar_observaciones: usarObs,
      }),
    onSuccess: () => {
      setAnalisis(null);
      setArchivo(null);
      if (inputRef.current) inputRef.current.value = "";
      refrescar();
    },
  });

  const deshacer = useMutation({
    mutationFn: ({ id, incluirProtegidos }: { id: number; incluirProtegidos: boolean }) =>
      api.deshacerImportacion(id, incluirProtegidos),
    onSuccess: refrescar,
  });

  /** Deshacer borra miles de filas de golpe: nunca con un solo clic. Y si alguna la
   *  corregiste tú, el servidor lo dice y se vuelve a preguntar. */
  async function pedirDeshacer(l: LoteImportacion) {
    const mensaje =
      `¿Deshacer la importación de ${l.filename}? Se borrarán sus ${l.created_count} ` +
      "movimientos. Antes se hace una copia de la base, y lo borrado queda en la papelera.";
    if (!window.confirm(mensaje)) return;
    try {
      await deshacer.mutateAsync({ id: l.id, incluirProtegidos: false });
    } catch (error) {
      if (
        error instanceof ErrorApi &&
        error.estado === 409 &&
        window.confirm(`${error.message}\n\n¿Borrar también esas correcciones?`)
      ) {
        await deshacer.mutateAsync({ id: l.id, incluirProtegidos: true }).catch(() => undefined);
      }
    }
  }

  function elegir(f: File | null) {
    setArchivo(f);
    setAnalisis(null);
    if (f) analizar.mutate({ f });
  }

  return (
    <div className="p-4 md:p-6">
      <Encabezado
        titulo="Importar Excel"
        descripcion="Sube tu hoja de ingresos y gastos. Primero se analiza sin escribir nada; solo importa cuando tú lo confirmas."
      />

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          {/* ------------------------------------------------------- archivo */}
          <Tarjeta>
            <div
              onDragOver={(e) => {
                e.preventDefault();
                setArrastrando(true);
              }}
              onDragLeave={() => setArrastrando(false)}
              onDrop={(e) => {
                e.preventDefault();
                setArrastrando(false);
                elegir(e.dataTransfer.files?.[0] ?? null);
              }}
              onClick={() => inputRef.current?.click()}
              className="flex cursor-pointer flex-col items-center gap-2 rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors"
              style={{
                borderColor: arrastrando ? "var(--serie-1)" : "var(--borde-fuerte)",
                background: arrastrando ? "var(--superficie-2)" : "transparent",
              }}
            >
              <FileSpreadsheet size={26} style={{ color: "var(--tinta-3)" }} />
              <p className="text-sm font-medium">
                {archivo ? archivo.name : "Arrastra tu archivo aquí o haz clic"}
              </p>
              <p className="text-xs text-[var(--tinta-3)]">
                .xlsx o .xlsm · máximo 20 MB
              </p>
              <input
                ref={inputRef}
                type="file"
                accept=".xlsx,.xlsm,.xltx,.xltm"
                hidden
                onChange={(e) => elegir(e.target.files?.[0] ?? null)}
              />
            </div>

            {analizar.isPending && (
              <p className="mt-3 text-sm text-[var(--tinta-3)]">Analizando el archivo…</p>
            )}
            {analizar.isError && (
              <p className="mt-3 text-sm" style={{ color: "var(--texto-malo)" }}>
                {(analizar.error as Error).message}
              </p>
            )}
          </Tarjeta>

          {/* ---------------------------------------------------- vista previa */}
          {analisis && (
            <>
              <Tarjeta
                titulo="Esto es lo que se importaría"
                subtitulo="Todavía no se ha escrito nada en la base de datos"
              >
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <Dato n={analisis.filas_con_fecha} t="filas con fecha" />
                  <Dato n={analisis.movimientos} t="movimientos" acento="var(--serie-1)" />
                  <Dato
                    n={analisis.rescatados_por_observacion}
                    t="rescatados de 'otros'"
                    acento="var(--bien)"
                  />
                  <Dato
                    n={analisis.sin_clasificar}
                    t="sin clasificar"
                    acento="var(--aviso)"
                  />
                </div>

                <div className="mt-4 grid gap-2 text-sm sm:grid-cols-2">
                  <div className="flex justify-between">
                    <span className="text-[var(--tinta-3)]">Periodo</span>
                    <b>
                      {analisis.desde ? fecha(analisis.desde) : "—"} a{" "}
                      {analisis.hasta ? fecha(analisis.hasta) : "—"}
                    </b>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-[var(--tinta-3)]">Ingresos</span>
                    <b className="tabular">{soles(analisis.total_ingresos)}</b>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-[var(--tinta-3)]">Gastos</span>
                    <b className="tabular">{soles(analisis.total_gastos)}</b>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-[var(--tinta-3)]">Hoja</span>
                    <b>{analisis.hoja}</b>
                  </div>
                </div>

                <div className="mt-4 flex flex-wrap gap-1.5">
                  {analisis.columnas_importadas.map((c) => (
                    <Etiqueta key={c} color="var(--bien)">
                      {c}
                    </Etiqueta>
                  ))}
                  {analisis.columnas_derivadas.map((c) => (
                    <Etiqueta key={c} titulo="Columna calculada: no se importa">
                      {c} (derivada)
                    </Etiqueta>
                  ))}
                  {analisis.columnas_sin_mapeo.map((c) => (
                    <Etiqueta key={c} color="var(--aviso)" titulo="Sin equivalencia: se ignora">
                      {c} (sin mapeo)
                    </Etiqueta>
                  ))}
                </div>

                <div className="mt-4 space-y-2">
                  {analisis.avisos.map((a, i) => (
                    <Aviso key={i}>{a}</Aviso>
                  ))}
                </div>
              </Tarjeta>

              <Tarjeta
                titulo="Muestra de los primeros movimientos"
                subtitulo="Las filas con ✨ son las que se rescataron leyendo la columna Observaciones"
              >
                <div className="-mx-4 max-h-96 overflow-auto">
                  <table className="w-full min-w-[720px] text-sm">
                    <thead className="sticky top-0" style={{ background: "var(--superficie)" }}>
                      <tr className="text-left text-xs text-[var(--tinta-3)]">
                        <th className="px-4 py-2 font-medium">Fecha</th>
                        <th className="px-2 py-2 font-medium">Columna</th>
                        <th className="px-2 py-2 text-right font-medium">Monto</th>
                        <th className="px-2 py-2 font-medium">Categoría</th>
                        <th className="px-2 py-2 font-medium">Necesidad</th>
                        <th className="px-4 py-2 font-medium">Observación</th>
                      </tr>
                    </thead>
                    <tbody>
                      {analisis.muestra.map((m, i) => (
                        <tr key={i} className="border-t" style={{ borderColor: "var(--borde)" }}>
                          <td className="px-4 py-1.5 text-xs whitespace-nowrap">
                            {fecha(m.fecha)}
                          </td>
                          <td className="px-2 py-1.5 text-xs text-[var(--tinta-3)]">
                            {m.columna}
                          </td>
                          <td
                            className="tabular px-2 py-1.5 text-right whitespace-nowrap"
                            style={{
                              color:
                                m.direccion === "ingreso"
                                  ? "var(--texto-bien)"
                                  : "var(--tinta)",
                            }}
                          >
                            {m.direccion === "ingreso" ? "+" : "−"} {soles(m.monto)}
                          </td>
                          <td className="px-2 py-1.5">
                            <span className="inline-flex items-center gap-1">
                              {m.origen_categoria === "observacion" && (
                                <Sparkles size={11} style={{ color: "var(--bien)" }} />
                              )}
                              {m.categoria ?? "—"}
                            </span>
                          </td>
                          <td className="px-2 py-1.5 text-xs text-[var(--tinta-2)]">
                            {m.necesidad ?? "—"}
                          </td>
                          <td className="max-w-56 truncate px-4 py-1.5 text-xs text-[var(--tinta-3)]">
                            {m.observacion ?? ""}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Tarjeta>
            </>
          )}
        </div>

        {/* -------------------------------------------------------- opciones */}
        <div className="space-y-4">
          {analisis && (
            <Tarjeta titulo="Opciones e importar">
              <div className="space-y-3">
                {analisis.hojas_disponibles.length > 1 && (
                  <Campo etiqueta="Hoja">
                    <Selector
                      value={hoja}
                      onChange={(e) => {
                        setHoja(e.target.value);
                        if (archivo) analizar.mutate({ f: archivo, h: e.target.value });
                      }}
                    >
                      {analisis.hojas_disponibles.map((h) => (
                        <option key={h} value={h}>
                          {h}
                        </option>
                      ))}
                    </Selector>
                  </Campo>
                )}

                <Campo
                  etiqueta="Cuenta"
                  hint="El Excel no dice de qué cuenta salió cada gasto. Déjalo sin asignar si no lo sabes."
                >
                  <Selector
                    value={cuentaId}
                    onChange={(e) =>
                      setCuentaId(e.target.value === "" ? "" : Number(e.target.value))
                    }
                  >
                    <option value="">Sin asignar</option>
                    {cuentas?.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </Selector>
                </Campo>

                <label className="flex items-start gap-2 text-sm">
                  <input
                    type="checkbox"
                    className="mt-0.5"
                    checked={usarObs}
                    onChange={(e) => setUsarObs(e.target.checked)}
                  />
                  <span>
                    Leer la columna Observaciones
                    <span className="block text-xs text-[var(--tinta-3)]">
                      Reparte parte de "Otros gastos" en categorías reales
                    </span>
                  </span>
                </label>

                <Boton
                  variante="primario"
                  className="w-full"
                  disabled={importar.isPending || !archivo}
                  onClick={() => importar.mutate()}
                >
                  <Upload size={15} />
                  {importar.isPending
                    ? "Importando…"
                    : `Importar ${analisis.movimientos} movimientos`}
                </Boton>
                {importar.isError && (
                  <p className="text-xs" style={{ color: "var(--texto-malo)" }}>
                    {(importar.error as Error).message}
                  </p>
                )}
                <p className="text-xs text-[var(--tinta-3)]">
                  Se puede deshacer entero. Y es idempotente: importar dos veces el mismo
                  archivo no duplica nada.
                </p>
              </div>
            </Tarjeta>
          )}

          <Tarjeta titulo="Importaciones anteriores">
            {!lotes?.length ? (
              <Vacio titulo="Todavía no has importado nada" />
            ) : (
              <ul className="space-y-3">
                {lotes.map((l) => (
                  <li
                    key={l.id}
                    className="rounded-lg border p-3"
                    style={{ borderColor: "var(--borde)" }}
                  >
                    <div className="flex items-start gap-2">
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-medium">{l.filename}</div>
                        <div className="text-xs text-[var(--tinta-3)]">
                          {fechaHora(l.created_at)} · hoja {l.sheet}
                        </div>
                        <div className="mt-1 text-xs">
                          <b>{l.created_count}</b> movimientos
                          {l.duplicated_count > 0 && (
                            <span className="text-[var(--tinta-3)]">
                              {" "}
                              · {l.duplicated_count} ya existían
                            </span>
                          )}
                        </div>
                        {l.desde && l.hasta && (
                          <div className="text-xs text-[var(--tinta-3)]">
                            {fecha(l.desde)} a {fecha(l.hasta)}
                          </div>
                        )}
                      </div>
                      <button
                        onClick={() => pedirDeshacer(l)}
                        disabled={deshacer.isPending}
                        title="Deshacer esta importación"
                        className="rounded-md p-1.5 hover:bg-[var(--superficie-2)]"
                        style={{ color: "var(--tinta-3)" }}
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
            {deshacer.isError && (
              <p className="mt-3 text-xs" style={{ color: "var(--texto-malo)" }}>
                {(deshacer.error as Error).message}
              </p>
            )}
          </Tarjeta>
        </div>
      </div>
    </div>
  );
}

function Dato({ n, t, acento }: { n: number; t: string; acento?: string }) {
  return (
    <div>
      <div className="tabular text-xl font-semibold" style={{ color: acento }}>
        {n.toLocaleString("es-PE")}
      </div>
      <div className="text-xs text-[var(--tinta-3)]">{t}</div>
    </div>
  );
}
