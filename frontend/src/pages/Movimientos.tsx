import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Search, Trash2 } from "lucide-react";
import { api } from "../lib/api";
import type { Categoria, Movimiento } from "../lib/api";
import { useParametros } from "../components/filtros";
import { PestanasMovimientos, VistaDescartados, VistaPapelera } from "../components/papelera";
import type { VistaMovimientos } from "../components/papelera";
import {
  ETIQUETA_ORIGEN,
  fechaHora,
  importe,
  primerDiaDelAnio,
  primerDiaDelMes,
  soles,
  ultimoDiaDelAnio,
  ultimoDiaDelMes,
} from "../lib/format";
import { Encabezado } from "../App";
import {
  Boton,
  Cargando,
  Entrada,
  Etiqueta,
  Selector,
  Tarjeta,
  Vacio,
} from "../components/ui";

const TAMANO = 50;

const COLOR_NECESIDAD: Record<string, string> = {
  esencial: "var(--bien)",
  discrecional: "var(--aviso)",
  evitable: "var(--critico)",
};

export function SelectorCategoria({
  valor,
  categorias,
  direccion,
  onChange,
}: {
  valor: number | null;
  categorias: Categoria[];
  direccion: string;
  onChange: (id: number | null) => void;
}) {
  const arbol = useMemo(() => {
    const padres = categorias.filter((c) => !c.parent_id && c.kind === direccion);
    return padres.map((p) => ({
      padre: p,
      hijos: categorias.filter((c) => c.parent_id === p.id),
    }));
  }, [categorias, direccion]);

  return (
    <select
      value={valor ?? ""}
      onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
      className="w-full rounded-md border bg-transparent px-2 py-1 text-xs outline-none"
      style={{ borderColor: "var(--borde)" }}
    >
      <option value="">Sin categoria</option>
      {arbol.map(({ padre, hijos }) => (
        <optgroup key={padre.id} label={padre.name}>
          <option value={padre.id}>{padre.name} (general)</option>
          {hijos.map((h) => (
            <option key={h.id} value={h.id}>
              {h.name}
            </option>
          ))}
        </optgroup>
      ))}
    </select>
  );
}

export default function Movimientos() {
  const qc = useQueryClient();
  const [pagina, setPagina] = useState(1);
  const [filtros, setFiltros] = useState({
    desde: primerDiaDelMes(),
    hasta: ultimoDiaDelMes(),
    direccion: "",
    estado: "",
    cuenta_id: "",
    categoria_id: "",
    necesidad: "",
    origen: "",
    buscar: "",
  });

  const { data: categorias } = useQuery({ queryKey: ["categorias"], queryFn: api.categorias });
  const { data: cuentas } = useQuery({ queryKey: ["cuentas"], queryFn: api.cuentas });
  const { data, isLoading } = useQuery({
    queryKey: ["movimientos", filtros, pagina],
    queryFn: () => api.movimientos({ ...filtros, pagina, tamano: TAMANO }),
  });

  const editar = useMutation({
    mutationFn: ({ id, datos }: { id: number; datos: Record<string, unknown> }) =>
      api.editarMovimiento(id, datos),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["movimientos"] });
      qc.invalidateQueries({ queryKey: ["resumen"] });
      qc.invalidateQueries({ queryKey: ["revision"] });
    },
  });

  const borrar = useMutation({
    mutationFn: api.borrarMovimiento,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["movimientos"] });
      qc.invalidateQueries({ queryKey: ["resumen"] });
    },
  });

  const mesActualInicio = primerDiaDelMes();
  const mesActualFin = ultimoDiaDelMes();

  const fechaMesPasado = new Date();
  fechaMesPasado.setMonth(fechaMesPasado.getMonth() - 1);
  const mesPasadoInicio = primerDiaDelMes(fechaMesPasado);
  const mesPasadoFin = ultimoDiaDelMes(fechaMesPasado);

  const anioActualInicio = primerDiaDelAnio();
  const anioActualFin = ultimoDiaDelAnio();

  const presetActivo = useMemo(() => {
    if (!filtros.desde && !filtros.hasta) return "todo";
    if (filtros.desde === mesActualInicio && filtros.hasta === mesActualFin) return "mes_actual";
    if (filtros.desde === mesPasadoInicio && filtros.hasta === mesPasadoFin) return "mes_pasado";
    if (filtros.desde === anioActualInicio && filtros.hasta === anioActualFin) return "este_anio";
    return "personalizado";
  }, [filtros.desde, filtros.hasta, mesActualInicio, mesActualFin, mesPasadoInicio, mesPasadoFin, anioActualInicio, anioActualFin]);

  function cambiarMes(delta: number) {
    const base = filtros.desde ? new Date(`${filtros.desde}T12:00:00`) : new Date();
    base.setMonth(base.getMonth() + delta);
    setPagina(1);
    setFiltros((f) => ({
      ...f,
      desde: primerDiaDelMes(base),
      hasta: ultimoDiaDelMes(base),
    }));
  }

  function set(campo: string, valor: string) {
    setPagina(1);
    setFiltros((f) => ({ ...f, [campo]: valor }));
  }

  const totalPaginas = data ? Math.max(1, Math.ceil(data.total / TAMANO)) : 1;

  // La vista va en la URL (?vista=papelera): se puede enlazar y sobrevive a recargar.
  const [params, cambiarParams] = useParametros({ vista: "activos" });
  const vista: VistaMovimientos =
    params.vista === "descartados" || params.vista === "papelera" ? params.vista : "activos";
  const { data: descartados } = useQuery({
    queryKey: ["movimientos", "descartados", "total"],
    queryFn: () => api.movimientos({ estado: "ignorada", tamano: 1 }),
  });
  const { data: papelera } = useQuery({
    queryKey: ["papelera"],
    queryFn: () => api.papelera(),
  });

  const encabezado = (
    <>
      <Encabezado
        titulo="Movimientos"
        descripcion="Todo lo que entra por correo, por Excel o a mano. Cambia la categoria aqui mismo: cada correccion enseña al clasificador."
      />
      <PestanasMovimientos
        vista={vista}
        onCambiar={(v) => cambiarParams({ vista: v })}
        descartados={descartados?.total ?? 0}
        borrados={papelera?.length ?? 0}
      />
    </>
  );

  if (vista !== "activos") {
    return (
      <div className="p-4 md:p-6">
        {encabezado}
        {vista === "descartados" ? (
          <VistaDescartados />
        ) : (
          <VistaPapelera
            categorias={categorias ?? []}
            onVerActual={(busqueda) => {
              // Sin fechas ni estado: el movimiento puede ser de cualquier mes.
              setPagina(1);
              setFiltros((f) => ({ ...f, desde: "", hasta: "", estado: "", buscar: busqueda }));
              cambiarParams({ vista: "activos" });
            }}
          />
        )}
      </div>
    );
  }

  return (
    <div className="p-4 md:p-6">
      {encabezado}

      <Tarjeta className="mb-4">
        {/* Atajos rapidos de Periodo */}
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2 border-b pb-3" style={{ borderColor: "var(--borde)" }}>
          <div className="flex flex-wrap items-center gap-1.5 text-xs">
            <span className="mr-1 font-medium text-[var(--tinta-3)]">Periodo:</span>
            <button
              type="button"
              onClick={() => {
                setPagina(1);
                setFiltros((f) => ({ ...f, desde: mesActualInicio, hasta: mesActualFin }));
              }}
              className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                presetActivo === "mes_actual"
                  ? "bg-[var(--acento)] text-white shadow-sm"
                  : "bg-[var(--superficie-2)] hover:bg-[var(--superficie-3)] text-[var(--tinta-2)]"
              }`}
            >
              Este mes
            </button>
            <button
              type="button"
              onClick={() => {
                setPagina(1);
                setFiltros((f) => ({ ...f, desde: mesPasadoInicio, hasta: mesPasadoFin }));
              }}
              className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                presetActivo === "mes_pasado"
                  ? "bg-[var(--acento)] text-white shadow-sm"
                  : "bg-[var(--superficie-2)] hover:bg-[var(--superficie-3)] text-[var(--tinta-2)]"
              }`}
            >
              Mes pasado
            </button>
            <button
              type="button"
              onClick={() => {
                setPagina(1);
                setFiltros((f) => ({ ...f, desde: anioActualInicio, hasta: anioActualFin }));
              }}
              className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                presetActivo === "este_anio"
                  ? "bg-[var(--acento)] text-white shadow-sm"
                  : "bg-[var(--superficie-2)] hover:bg-[var(--superficie-3)] text-[var(--tinta-2)]"
              }`}
            >
              Este año
            </button>
            <button
              type="button"
              onClick={() => {
                setPagina(1);
                setFiltros((f) => ({ ...f, desde: "", hasta: "" }));
              }}
              className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                presetActivo === "todo"
                  ? "bg-[var(--acento)] text-white shadow-sm"
                  : "bg-[var(--superficie-2)] hover:bg-[var(--superficie-3)] text-[var(--tinta-2)]"
              }`}
            >
              Todo mi historial (Excel + Correo)
            </button>
            {presetActivo === "personalizado" && (
              <span className="rounded-md bg-[var(--superficie-2)] px-2 py-0.5 text-xs text-[var(--tinta-3)]">
                Rango a medida
              </span>
            )}
          </div>

          <div className="flex items-center gap-1 text-xs">
            <button
              type="button"
              onClick={() => cambiarMes(-1)}
              title="Mes anterior"
              className="flex items-center gap-0.5 rounded-md border px-2 py-1 text-[var(--tinta-2)] hover:bg-[var(--superficie-2)]"
              style={{ borderColor: "var(--borde)" }}
            >
              <ChevronLeft size={13} />
              <span className="hidden sm:inline">Mes ant.</span>
            </button>
            <button
              type="button"
              onClick={() => cambiarMes(1)}
              title="Mes siguiente"
              className="flex items-center gap-0.5 rounded-md border px-2 py-1 text-[var(--tinta-2)] hover:bg-[var(--superficie-2)]"
              style={{ borderColor: "var(--borde)" }}
            >
              <span className="hidden sm:inline">Mes sig.</span>
              <ChevronRight size={13} />
            </button>
          </div>
        </div>

        <div className="grid gap-3 md:grid-cols-3 lg:grid-cols-5">
          <label className="block">
            <span className="mb-1 block text-xs text-[var(--tinta-3)]">Desde</span>
            <Entrada type="date" value={filtros.desde} onChange={(e) => set("desde", e.target.value)} />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs text-[var(--tinta-3)]">Hasta</span>
            <Entrada type="date" value={filtros.hasta} onChange={(e) => set("hasta", e.target.value)} />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs text-[var(--tinta-3)]">Tipo</span>
            <Selector value={filtros.direccion} onChange={(e) => set("direccion", e.target.value)}>
              <option value="">Todos</option>
              <option value="gasto">Gastos</option>
              <option value="ingreso">Ingresos</option>
              <option value="transferencia">Transferencias</option>
            </Selector>
          </label>
          <label className="block">
            <span className="mb-1 block text-xs text-[var(--tinta-3)]">Cuenta</span>
            <Selector value={filtros.cuenta_id} onChange={(e) => set("cuenta_id", e.target.value)}>
              <option value="">Todas</option>
              {cuentas?.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Selector>
          </label>
          <label className="block">
            <span className="mb-1 block text-xs text-[var(--tinta-3)]">Buscar</span>
            <div className="relative">
              <Search
                size={14}
                className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-[var(--tinta-3)]"
              />
              <Entrada
                className="pl-8"
                placeholder="comercio, nota…"
                value={filtros.buscar}
                onChange={(e) => set("buscar", e.target.value)}
              />
            </div>
          </label>
        </div>

        <div className="mt-3 grid gap-3 sm:grid-cols-3 lg:max-w-2xl">
          <Selector
            value={filtros.estado}
            onChange={(e) => set("estado", e.target.value)}
          >
            {/* "Cualquiera" ya no incluye duplicadas ni ignoradas: no cuentan
                en los totales, y mezclarlas hacia que la cabecera de esta tabla
                dijera una cifra y el panel otra. Por eso tienen su propia
                opcion: si no, un movimiento ignorado quedaba inalcanzable y no
                habia forma de deshacerlo. */}
            <option value="">Los que cuentan</option>
            <option value="confirmada">Confirmadas</option>
            <option value="por_revisar">Por revisar</option>
            <option value="duplicada">Duplicadas</option>
            <option value="ignorada">Ignoradas</option>
          </Selector>
          <Selector
            value={filtros.necesidad}
            onChange={(e) => set("necesidad", e.target.value)}
          >
            <option value="">Cualquier necesidad</option>
            <option value="esencial">Esencial</option>
            <option value="discrecional">Discrecional</option>
            <option value="evitable">Evitable</option>
          </Selector>
          <Selector
            value={filtros.origen}
            onChange={(e) => set("origen", e.target.value)}
          >
            <option value="">Cualquier origen</option>
            <option value="gmail">Correo</option>
            <option value="manual">Manual</option>
            <option value="excel">Excel</option>
          </Selector>
        </div>
      </Tarjeta>

      {data && (
        <div className="mb-3 flex flex-wrap items-center gap-4 text-sm">
          <span className="text-[var(--tinta-3)]">{data.total} movimientos</span>
          <span>
            Gastos <b className="tabular">{soles(data.suma_gastos)}</b>
          </span>
          <span>
            Ingresos <b className="tabular">{soles(data.suma_ingresos)}</b>
          </span>
          <span>
            Neto{" "}
            <b
              className="tabular"
              style={{
                color:
                  data.suma_ingresos - data.suma_gastos >= 0
                    ? "var(--texto-bien)"
                    : "var(--texto-malo)",
              }}
            >
              {soles(data.suma_ingresos - data.suma_gastos)}
            </b>
          </span>
        </div>
      )}

      <Tarjeta>
        {isLoading ? (
          <Cargando />
        ) : !data?.items.length ? (
          <Vacio
            titulo="No hay movimientos con esos filtros"
            detalle="Prueba a ampliar el rango de fechas o sincroniza el correo."
          />
        ) : (
          <div className="-mx-4 overflow-x-auto">
            <table className="w-full min-w-[900px] text-sm">
              <thead>
                <tr className="text-left text-xs text-[var(--tinta-3)]">
                  <th className="px-4 py-2 font-medium">Fecha</th>
                  <th className="px-2 py-2 font-medium">Concepto</th>
                  <th className="px-2 py-2 font-medium">Categoria</th>
                  <th className="px-2 py-2 font-medium">Necesidad</th>
                  <th className="px-2 py-2 font-medium">Cuenta</th>
                  <th className="px-2 py-2 text-right font-medium">Monto</th>
                  <th className="px-4 py-2" />
                </tr>
              </thead>
              <tbody>
                {data.items.map((m) => (
                  <Fila
                    key={m.id}
                    m={m}
                    categorias={categorias ?? []}
                    onEditar={(datos) => editar.mutate({ id: m.id, datos })}
                    onBorrar={() => borrar.mutate(m.id)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}

        {data && totalPaginas > 1 && (
          <div className="mt-4 flex items-center justify-between">
            <Boton onClick={() => setPagina((p) => Math.max(1, p - 1))} disabled={pagina === 1}>
              <ChevronLeft size={15} /> Anterior
            </Boton>
            <span className="text-xs text-[var(--tinta-3)]">
              Pagina {pagina} de {totalPaginas}
            </span>
            <Boton
              onClick={() => setPagina((p) => Math.min(totalPaginas, p + 1))}
              disabled={pagina >= totalPaginas}
            >
              Siguiente <ChevronRight size={15} />
            </Boton>
          </div>
        )}
      </Tarjeta>
    </div>
  );
}

function Fila({
  m,
  categorias,
  onEditar,
  onBorrar,
}: {
  m: Movimiento;
  categorias: Categoria[];
  onEditar: (datos: Record<string, unknown>) => void;
  onBorrar: () => void;
}) {
  const signo = m.direction === "ingreso" ? "+" : m.direction === "gasto" ? "−" : "";
  const color =
    m.direction === "ingreso"
      ? "var(--texto-bien)"
      : m.direction === "transferencia"
        ? "var(--tinta-3)"
        : "var(--tinta)";

  return (
    <tr className="border-t align-middle" style={{ borderColor: "var(--borde)" }}>
      <td className="px-4 py-2 text-xs whitespace-nowrap text-[var(--tinta-2)]">
        {fechaHora(m.occurred_at)}
      </td>
      <td className="max-w-xs px-2 py-2">
        <div className="truncate font-medium">
          {m.merchant ? m.merchant.replace(/\b\w/g, (c) => c.toUpperCase()) : (m.description ?? "—")}
        </div>
        <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
          <span className="text-xs text-[var(--tinta-3)]">{ETIQUETA_ORIGEN[m.source]}</span>
          {m.locked_by_user && (
            <Etiqueta
              color="var(--bien)"
              titulo="Lo registraste o corregiste tú. Ningún reproceso, regla nueva ni limpieza lo cambia ni lo borra."
            >
              Protegido
            </Etiqueta>
          )}
          {m.status === "por_revisar" && (
            <Etiqueta color="var(--aviso)" titulo={m.notes ?? undefined}>
              Por revisar
            </Etiqueta>
          )}
          {m.duplicate_of_id && <Etiqueta color="var(--critico)">Posible duplicado</Etiqueta>}
          {m.direction === "transferencia" && <Etiqueta>No cuenta como gasto</Etiqueta>}
        </div>
      </td>
      <td className="px-2 py-2" style={{ minWidth: 180 }}>
        <SelectorCategoria
          valor={m.category_id}
          categorias={categorias}
          direccion={m.direction}
          onChange={(id) => onEditar({ category_id: id })}
        />
      </td>
      <td className="px-2 py-2">
        <div className="flex items-center gap-1.5">
          <span
            aria-hidden
            className="h-2 w-2 shrink-0 rounded-full"
            style={{ background: COLOR_NECESIDAD[m.necessity ?? ""] ?? "transparent" }}
          />
          <select
            value={m.necessity ?? ""}
            onChange={(e) => onEditar({ necessity: e.target.value || null })}
            className="rounded-md border bg-transparent px-2 py-1 text-xs outline-none"
            style={{ borderColor: "var(--borde)" }}
            aria-label="Necesidad"
          >
            <option value="">Sin marcar</option>
            <option value="esencial">Esencial</option>
            <option value="discrecional">Discrecional</option>
            <option value="evitable">Evitable</option>
          </select>
        </div>
      </td>
      <td className="px-2 py-2 text-xs text-[var(--tinta-2)]">{m.account_name ?? "—"}</td>
      <td className="tabular px-2 py-2 text-right font-medium whitespace-nowrap" style={{ color }}>
        {signo} {importe(m.amount, m.currency)}
      </td>
      <td className="px-4 py-2 text-right">
        <button
          onClick={() => {
            // Un registro tuyo se borra de verdad (queda en la papelera); uno del
            // banco se descarta, para que el siguiente sincronizado no lo traiga.
            if (
              m.source !== "manual" ||
              window.confirm("¿Borrar este registro tuyo? Quedará en la papelera por si fue un error.")
            ) {
              onBorrar();
            }
          }}
          title={
            m.source === "manual"
              ? "Borrar tu registro (queda en la papelera)"
              : "Descartar: deja de contar y no vuelve al sincronizar el correo"
          }
          aria-label={m.source === "manual" ? "Borrar movimiento" : "Descartar movimiento"}
          className="rounded-md p-1.5 hover:bg-[var(--superficie-2)]"
          style={{ color: "var(--tinta-3)" }}
        >
          <Trash2 size={14} />
        </button>
      </td>
    </tr>
  );
}
