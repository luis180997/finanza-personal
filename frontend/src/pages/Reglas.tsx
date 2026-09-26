import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { api } from "../lib/api";
import type { Regla } from "../lib/api";
import { Encabezado } from "../App";
import {
  Boton,
  Campo,
  Cargando,
  Entrada,
  Etiqueta,
  Selector,
  Tarjeta,
  Vacio,
} from "../components/ui";

const REGLA_NUEVA: Partial<Regla> = {
  name: "",
  field: "merchant",
  op: "contains",
  value: "",
  priority: 50,
  active: true,
  stop: true,
};

export default function Reglas() {
  const qc = useQueryClient();
  const [borrador, setBorrador] = useState<Partial<Regla>>(REGLA_NUEVA);

  const { data: reglas, isLoading } = useQuery({ queryKey: ["reglas"], queryFn: api.reglas });
  const { data: categorias } = useQuery({ queryKey: ["categorias"], queryFn: api.categorias });

  const refrescar = () => {
    qc.invalidateQueries({ queryKey: ["reglas"] });
    qc.invalidateQueries({ queryKey: ["resumen"] });
  };

  const crear = useMutation({
    mutationFn: api.crearRegla,
    onSuccess: () => {
      setBorrador(REGLA_NUEVA);
      refrescar();
    },
  });
  const editar = useMutation({
    mutationFn: ({ id, datos }: { id: number; datos: Partial<Regla> }) =>
      api.editarRegla(id, datos),
    onSuccess: refrescar,
  });
  const borrar = useMutation({ mutationFn: api.borrarRegla, onSuccess: refrescar });

  const nombreCategoria = (id: number | null) =>
    categorias?.find((c) => c.id === id)?.name ?? "—";

  if (isLoading) return <div className="p-6"><Cargando /></div>;

  return (
    <div className="p-4 md:p-6">
      <Encabezado
        titulo="Reglas"
        descripcion="Las reglas mandan por encima de todo lo demas. Se evaluan de menor a mayor prioridad y la primera que coincide decide la categoria."
      />

      <div className="grid gap-4 lg:grid-cols-3">
        <Tarjeta titulo="Nueva regla" className="lg:col-span-1">
          <div className="space-y-3">
            <Campo etiqueta="Nombre">
              <Entrada
                placeholder="Uber es taxi"
                value={borrador.name ?? ""}
                onChange={(e) => setBorrador({ ...borrador, name: e.target.value })}
              />
            </Campo>

            <div className="grid grid-cols-2 gap-3">
              <Campo etiqueta="Campo">
                <Selector
                  value={borrador.field}
                  onChange={(e) => setBorrador({ ...borrador, field: e.target.value })}
                >
                  <option value="merchant">Comercio</option>
                  <option value="description">Descripcion</option>
                  <option value="subject">Asunto del correo</option>
                  <option value="sender">Remitente</option>
                  <option value="account">Cuenta</option>
                </Selector>
              </Campo>
              <Campo etiqueta="Operador">
                <Selector
                  value={borrador.op}
                  onChange={(e) => setBorrador({ ...borrador, op: e.target.value })}
                >
                  <option value="contains">contiene</option>
                  <option value="equals">es igual a</option>
                  <option value="startswith">empieza por</option>
                  <option value="regex">regex</option>
                </Selector>
              </Campo>
            </div>

            <Campo
              etiqueta="Valor"
              hint={borrador.op === "regex" ? "Expresion regular, sin tildes" : undefined}
            >
              <Entrada
                placeholder="uber"
                value={borrador.value ?? ""}
                onChange={(e) => setBorrador({ ...borrador, value: e.target.value })}
              />
            </Campo>

            <Campo etiqueta="Asignar categoria">
              <Selector
                value={borrador.set_category_id ?? ""}
                onChange={(e) =>
                  setBorrador({
                    ...borrador,
                    set_category_id: e.target.value ? Number(e.target.value) : null,
                  })
                }
              >
                <option value="">Sin cambio</option>
                {/* Agrupadas por categoria, y con la propia categoria elegible: antes
                    solo salian subcategorias, sueltas y mezcladas, y no habia forma de
                    mandar una regla a "Sin clasificar" ni a una categoria general. */}
                {(categorias ?? [])
                  .filter((c) => !c.parent_id)
                  .map((padre) => (
                    <optgroup key={padre.id} label={padre.name}>
                      <option value={padre.id}>{padre.name} (general)</option>
                      {(categorias ?? [])
                        .filter((c) => c.parent_id === padre.id)
                        .map((c) => (
                          <option key={c.id} value={c.id}>
                            {c.name}
                          </option>
                        ))}
                    </optgroup>
                  ))}
              </Selector>
            </Campo>

            <div className="grid grid-cols-2 gap-3">
              <Campo etiqueta="Necesidad">
                <Selector
                  value={borrador.set_necessity ?? ""}
                  onChange={(e) =>
                    setBorrador({
                      ...borrador,
                      set_necessity: (e.target.value || null) as Regla["set_necessity"],
                    })
                  }
                >
                  <option value="">Sin cambio</option>
                  <option value="esencial">Esencial</option>
                  <option value="discrecional">Discrecional</option>
                  <option value="evitable">Evitable</option>
                </Selector>
              </Campo>
              <Campo etiqueta="Prioridad" hint="menor = se evalua antes">
                <Entrada
                  type="number"
                  value={borrador.priority ?? 50}
                  onChange={(e) => setBorrador({ ...borrador, priority: Number(e.target.value) })}
                />
              </Campo>
            </div>

            <Boton
              variante="primario"
              onClick={() => crear.mutate(borrador)}
              disabled={!borrador.name || !borrador.value || crear.isPending}
            >
              <Plus size={15} /> Crear regla
            </Boton>
            {crear.isError && (
              <p className="text-xs" style={{ color: "var(--texto-malo)" }}>
                {(crear.error as Error).message}
              </p>
            )}
          </div>
        </Tarjeta>

        <Tarjeta titulo={`Reglas activas (${reglas?.length ?? 0})`} className="lg:col-span-2">
          {!reglas?.length ? (
            <Vacio titulo="Sin reglas" />
          ) : (
            <div className="-mx-4 overflow-x-auto">
              <table className="w-full min-w-[720px] text-sm">
                <thead>
                  <tr className="text-left text-xs text-[var(--tinta-3)]">
                    <th className="px-4 py-2 font-medium">Prio</th>
                    <th className="px-2 py-2 font-medium">Nombre</th>
                    <th className="px-2 py-2 font-medium">Condicion</th>
                    <th className="px-2 py-2 font-medium">Asigna</th>
                    <th className="px-2 py-2 text-right font-medium">Usos</th>
                    <th className="px-4 py-2" />
                  </tr>
                </thead>
                <tbody>
                  {reglas.map((r) => (
                    <tr key={r.id} className="border-t" style={{ borderColor: "var(--borde)" }}>
                      <td className="tabular px-4 py-2 text-[var(--tinta-3)]">{r.priority}</td>
                      <td className="px-2 py-2">
                        <div className="font-medium">{r.name}</div>
                        {!r.active && <Etiqueta>Inactiva</Etiqueta>}
                      </td>
                      <td className="px-2 py-2 font-mono text-xs text-[var(--tinta-2)]">
                        {r.field} {r.op} “{r.value}”
                      </td>
                      <td className="px-2 py-2">
                        <div className="flex flex-wrap gap-1">
                          {r.set_category_id && (
                            <Etiqueta>{nombreCategoria(r.set_category_id)}</Etiqueta>
                          )}
                          {r.set_necessity && <Etiqueta>{r.set_necessity}</Etiqueta>}
                        </div>
                      </td>
                      <td className="tabular px-2 py-2 text-right text-[var(--tinta-3)]">
                        {r.hits}
                      </td>
                      <td className="px-4 py-2">
                        <div className="flex justify-end gap-1">
                          <button
                            onClick={() =>
                              editar.mutate({ id: r.id, datos: { ...r, active: !r.active } })
                            }
                            className="rounded-md px-2 py-1 text-xs hover:bg-[var(--superficie-2)]"
                          >
                            {r.active ? "Desactivar" : "Activar"}
                          </button>
                          <button
                            onClick={() => borrar.mutate(r.id)}
                            className="rounded-md p-1.5 hover:bg-[var(--superficie-2)]"
                            style={{ color: "var(--tinta-3)" }}
                            title="Borrar"
                          >
                            <Trash2 size={14} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Tarjeta>
      </div>
    </div>
  );
}
