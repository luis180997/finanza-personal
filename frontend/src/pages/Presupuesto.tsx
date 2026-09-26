import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Target, Trash2 } from "lucide-react";
import { api } from "../lib/api";
import type { Presupuesto as PresupuestoVivo } from "../lib/api";
import { primerDiaDelMes, soles, ultimoDiaDelMes } from "../lib/format";
import { Encabezado } from "../App";
import {
  Aviso,
  Boton,
  Campo,
  Cargando,
  Entrada,
  Selector,
  Tarjeta,
  Vacio,
} from "../components/ui";

const COLOR_ESTADO: Record<string, string> = {
  en_curso: "var(--bien)",
  en_riesgo: "var(--aviso)",
  excedido: "var(--critico)",
};

const TEXTO_ESTADO: Record<string, string> = {
  en_curso: "En curso",
  en_riesgo: "En riesgo",
  excedido: "Excedido",
};

/**
 * Barra de consumo del tope. La marca vertical es la proyeccion al cierre del
 * mes: sin ella, "llevo el 60%" no dice si vas bien o mal, porque depende de
 * cuanto mes queda.
 */
function BarraTope({ p }: { p: PresupuestoVivo }) {
  const consumido = Math.min(100, p.pct);
  const proyectado =
    p.proyeccion !== null && p.tope
      ? Math.min(100, (p.proyeccion / p.tope) * 100)
      : null;
  const color = COLOR_ESTADO[p.estado];

  return (
    <div>
      <div
        className="relative h-2.5 w-full overflow-hidden rounded-full"
        style={{ background: "var(--superficie-2)" }}
        role="img"
        aria-label={`${p.categoria}: ${soles(p.gastado)} de ${soles(p.tope)} (${p.pct}%)`}
      >
        <div
          className="h-full rounded-full"
          style={{ width: `${consumido}%`, background: color }}
        />
        {p.estado !== "excedido" && proyectado !== null && proyectado > consumido && (
          <span
            aria-hidden
            title={`Proyeccion al cierre: ${soles(p.proyeccion ?? 0)}`}
            className="absolute top-0 h-full w-0.5"
            style={{ left: `${proyectado}%`, background: "var(--tinta-2)" }}
          />
        )}
      </div>
    </div>
  );
}

export default function Presupuesto() {
  const qc = useQueryClient();
  const [categoriaId, setCategoriaId] = useState<number | "">("");
  const [monto, setMonto] = useState("");
  const [meta, setMeta] = useState("");

  const rango = { desde: primerDiaDelMes(), hasta: ultimoDiaDelMes() };

  const { data: resumen, isLoading } = useQuery({
    queryKey: ["resumen", rango.desde, rango.hasta],
    queryFn: () => api.resumen(rango.desde, rango.hasta),
  });
  const { data: categorias } = useQuery({ queryKey: ["categorias"], queryFn: api.categorias });
  const { data: config } = useQuery({ queryKey: ["presupuestos"], queryFn: api.presupuestos });
  const { data: metaGuardada } = useQuery({
    queryKey: ["meta-ahorro"],
    queryFn: api.metaAhorro,
  });

  // El campo arranca con la meta guardada: ver "1000" de marcador de posicion
  // junto a "Actual: S/ 1,500" es contradictorio.
  useEffect(() => {
    if (metaGuardada && meta === "") setMeta(String(metaGuardada.amount || ""));
  }, [metaGuardada]); // eslint-disable-line react-hooks/exhaustive-deps

  function refrescar() {
    qc.invalidateQueries({ queryKey: ["resumen"] });
    qc.invalidateQueries({ queryKey: ["presupuestos"] });
    qc.invalidateQueries({ queryKey: ["meta-ahorro"] });
  }

  const guardar = useMutation({
    mutationFn: api.guardarPresupuesto,
    onSuccess: () => {
      setCategoriaId("");
      setMonto("");
      refrescar();
    },
  });
  const borrar = useMutation({ mutationFn: api.borrarPresupuesto, onSuccess: refrescar });
  const guardarMeta = useMutation({ mutationFn: api.guardarMetaAhorro, onSuccess: refrescar });

  // Solo categorias de gasto, y sin las que ya tienen tope.
  const disponibles = useMemo(() => {
    const conTope = new Set((config ?? []).map((c) => c.category_id));
    const gasto = (categorias ?? []).filter((c) => c.kind === "gasto" && !conTope.has(c.id));
    const padres = gasto.filter((c) => !c.parent_id);
    return padres.map((p) => ({
      padre: p,
      hijos: gasto.filter((c) => c.parent_id === p.id),
    }));
  }, [categorias, config]);

  if (isLoading) return <div className="p-6"><Cargando /></div>;

  const topes = resumen?.presupuestos ?? [];
  const ahorro = resumen?.meta_ahorro ?? null;

  return (
    <div className="p-4 md:p-6">
      <Encabezado
        titulo="Presupuesto"
        descripcion="Topes mensuales por categoria y meta de ahorro. Se repiten cada mes; el consumo se reinicia el dia 1."
      />

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Tarjeta
            titulo="Topes del mes"
            subtitulo="La marca vertical es la proyeccion al cierre al ritmo actual"
          >
            {!topes.length ? (
              <Vacio
                titulo="Todavia no hay ningun tope"
                detalle="Pon el primero en la categoria que mas se te escapa. No hay topes por defecto a proposito: una alarma que no significa nada ensena a ignorar las alarmas."
              />
            ) : (
              <ul className="space-y-4">
                {topes.map((p) => {
                  const cfg = config?.find((c) => c.category_id === p.categoria_id);
                  return (
                    <li key={p.categoria_id}>
                      <div className="mb-1.5 flex flex-wrap items-baseline gap-2">
                        <span
                          aria-hidden
                          className="h-2.5 w-2.5 shrink-0 rounded-full"
                          style={{ background: p.color }}
                        />
                        <span className="font-medium">{p.categoria}</span>
                        <span
                          className="rounded-md border px-1.5 py-0.5 text-xs"
                          style={{
                            borderColor: "var(--borde)",
                            color: COLOR_ESTADO[p.estado],
                          }}
                        >
                          {TEXTO_ESTADO[p.estado]}
                        </span>
                        <span className="tabular ml-auto text-sm">
                          <b>{soles(p.gastado)}</b>
                          <span className="text-[var(--tinta-3)]"> de {soles(p.tope)}</span>
                        </span>
                        {cfg && (
                          <button
                            onClick={() => borrar.mutate(cfg.id)}
                            title="Quitar tope"
                            className="rounded-md p-1 hover:bg-[var(--superficie-2)]"
                            style={{ color: "var(--tinta-3)" }}
                          >
                            <Trash2 size={13} />
                          </button>
                        )}
                      </div>
                      <BarraTope p={p} />
                      <div className="mt-1 flex flex-wrap gap-x-4 text-xs text-[var(--tinta-3)]">
                        <span>{p.pct}% consumido</span>
                        <span>
                          {p.restante >= 0
                            ? `Quedan ${soles(p.restante)}`
                            : `Te pasaste ${soles(Math.abs(p.restante))}`}
                        </span>
                        <span>
                          {p.proyeccion !== null
                            ? `Proyeccion al cierre: ${soles(p.proyeccion)}`
                            : "Sin historial suficiente para proyectar"}
                        </span>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </Tarjeta>

          <Tarjeta titulo="Añadir un tope">
            <div className="grid gap-3 sm:grid-cols-[1fr_auto_auto] sm:items-end">
              <Campo
                etiqueta="Categoria"
                hint="Un tope en la categoria padre cuenta tambien lo de sus subcategorias"
              >
                <Selector
                  value={categoriaId}
                  onChange={(e) =>
                    setCategoriaId(e.target.value === "" ? "" : Number(e.target.value))
                  }
                >
                  <option value="">Elige una categoria</option>
                  {disponibles.map(({ padre, hijos }) => (
                    <optgroup key={padre.id} label={padre.name}>
                      <option value={padre.id}>{padre.name} (todo el grupo)</option>
                      {hijos.map((h) => (
                        <option key={h.id} value={h.id}>
                          {h.name}
                        </option>
                      ))}
                    </optgroup>
                  ))}
                </Selector>
              </Campo>
              <Campo etiqueta="Tope mensual (S/)">
                <Entrada
                  inputMode="decimal"
                  placeholder="150"
                  className="tabular w-32"
                  value={monto}
                  onChange={(e) => setMonto(e.target.value)}
                />
              </Campo>
              <Boton
                variante="primario"
                disabled={categoriaId === "" || !monto || guardar.isPending}
                onClick={() =>
                  guardar.mutate({
                    category_id: Number(categoriaId),
                    amount: Number(monto.replace(",", ".")),
                  })
                }
              >
                <Plus size={15} /> Añadir
              </Boton>
            </div>
            {guardar.isError && (
              <p className="mt-2 text-xs" style={{ color: "var(--texto-malo)" }}>
                {(guardar.error as Error).message}
              </p>
            )}
          </Tarjeta>
        </div>

        <div className="space-y-4">
          <Tarjeta titulo="Meta de ahorro" subtitulo="Monto fijo que quieres guardar cada mes">
            <div className="flex items-end gap-2">
              <Campo etiqueta="Meta mensual (S/)">
                <Entrada
                  inputMode="decimal"
                  className="tabular"
                  placeholder="1000"
                  value={meta}
                  onChange={(e) => setMeta(e.target.value)}
                />
              </Campo>
              <Boton
                onClick={() => guardarMeta.mutate(Number(meta.replace(",", ".") || 0))}
                disabled={guardarMeta.isPending}
              >
                <Target size={15} /> Guardar
              </Boton>
            </div>
            <p className="mt-2 text-xs text-[var(--tinta-3)]">
              Actual: {soles(metaGuardada?.amount ?? 0)}. Pon 0 para desactivarla.
            </p>

            {ahorro && (
              <div className="mt-4 border-t pt-4" style={{ borderColor: "var(--borde)" }}>
                <div className="text-2xl font-semibold tracking-tight">
                  {soles(ahorro.ahorro_actual)}
                </div>
                <div className="text-xs text-[var(--tinta-3)]">
                  ahorrado de {soles(ahorro.meta)}
                </div>

                <div
                  className="mt-3 h-2.5 w-full overflow-hidden rounded-full"
                  style={{ background: "var(--superficie-2)" }}
                >
                  <div
                    className="h-full rounded-full"
                    style={{
                      width: `${Math.min(100, ahorro.pct)}%`,
                      background: ahorro.cumple_proyeccion
                        ? "var(--bien)"
                        : "var(--aviso)",
                    }}
                  />
                </div>

                <ul className="mt-3 space-y-1.5 text-sm">
                  <li className="flex justify-between">
                    <span className="text-[var(--tinta-3)]">Proyeccion al cierre</span>
                    {ahorro.ahorro_proyectado !== null ? (
                      <b
                        className="tabular"
                        style={{
                          color: ahorro.cumple_proyeccion
                            ? "var(--texto-bien)"
                            : "var(--texto-malo)",
                        }}
                      >
                        {soles(ahorro.ahorro_proyectado)}
                      </b>
                    ) : (
                      <span className="text-[var(--tinta-3)]">sin historial</span>
                    )}
                  </li>
                  {ahorro.dias_restantes > 0 && (
                    <li className="flex justify-between">
                      <span className="text-[var(--tinta-3)]">
                        Puedes gastar al dia ({ahorro.dias_restantes} dias)
                      </span>
                      <b className="tabular">{soles(ahorro.disponible_diario)}</b>
                    </li>
                  )}
                </ul>
              </div>
            )}
          </Tarjeta>

          <Aviso>
            El consumo del tope usa el mes natural: empieza el dia 1 y se reinicia solo.
            Las transferencias entre tus cuentas no consumen presupuesto.
          </Aviso>
        </div>
      </div>
    </div>
  );
}
