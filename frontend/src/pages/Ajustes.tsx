import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CreditCard, Plus } from "lucide-react";
import { api } from "../lib/api";
import type { Cuenta } from "../lib/api";
import { Encabezado } from "../App";
import { TarjetaRespaldos } from "../components/respaldos";
import {
  Aviso,
  Boton,
  Campo,
  Cargando,
  Entrada,
  Etiqueta,
  Selector,
  Tarjeta,
} from "../components/ui";

const NUEVA: Partial<Cuenta> = { name: "", bank: "otro", type: "debito", currency: "PEN" };

export default function Ajustes() {
  const qc = useQueryClient();
  const [borrador, setBorrador] = useState<Partial<Cuenta>>(NUEVA);

  const { data: cuentas, isLoading } = useQuery({ queryKey: ["cuentas"], queryFn: api.cuentas });
  const { data: categorias } = useQuery({ queryKey: ["categorias"], queryFn: api.categorias });

  const refrescar = () => qc.invalidateQueries({ queryKey: ["cuentas"] });

  const crear = useMutation({
    mutationFn: api.crearCuenta,
    onSuccess: () => {
      setBorrador(NUEVA);
      refrescar();
    },
  });
  const editar = useMutation({
    mutationFn: ({ id, datos }: { id: number; datos: Partial<Cuenta> }) =>
      api.editarCuenta(id, datos),
    onSuccess: refrescar,
  });

  if (isLoading) return <div className="p-6"><Cargando /></div>;

  const padres = categorias?.filter((c) => !c.parent_id) ?? [];

  return (
    <div className="p-4 md:p-6">
      <Encabezado
        titulo="Cuentas, categorias y copias"
        descripcion="Los ultimos 4 digitos son la pieza clave: con ellos el sistema sabe si un consumo salio de tu tarjeta de credito o de la de debito."
      />

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Tarjeta titulo="Tus cuentas">
            <div className="space-y-3">
              {cuentas?.map((c) => (
                <div
                  key={c.id}
                  className="flex flex-wrap items-center gap-3 rounded-lg border p-3"
                  style={{ borderColor: "var(--borde)" }}
                >
                  <CreditCard size={16} className="text-[var(--tinta-3)]" />
                  <div className="min-w-32">
                    <div className="text-sm font-medium">{c.name}</div>
                    <div className="text-xs text-[var(--tinta-3)]">
                      {c.bank} · {c.type} · {c.currency}
                    </div>
                  </div>
                  <label className="ml-auto flex items-center gap-2 text-xs text-[var(--tinta-3)]">
                    Ultimos 4
                    <Entrada
                      className="w-20 text-center"
                      maxLength={4}
                      placeholder="4821"
                      defaultValue={c.last4 ?? ""}
                      onBlur={(e) =>
                        editar.mutate({ id: c.id, datos: { ...c, last4: e.target.value || null } })
                      }
                    />
                  </label>
                  <label className="flex items-center gap-2 text-xs">
                    <input
                      type="checkbox"
                      checked={c.active}
                      onChange={(e) =>
                        editar.mutate({ id: c.id, datos: { ...c, active: e.target.checked } })
                      }
                    />
                    Activa
                  </label>
                </div>
              ))}
            </div>
          </Tarjeta>

          <Tarjeta
            titulo="Taxonomia de categorias"
            subtitulo="Dos niveles: categoria y subcategoria. El panel agrupa por el nivel superior."
          >
            <div className="grid gap-3 sm:grid-cols-2">
              {padres.map((p) => (
                <div key={p.id}>
                  <div className="mb-1.5 flex items-center gap-2 text-sm font-medium">
                    <span
                      aria-hidden
                      className="h-2.5 w-2.5 rounded-full"
                      style={{ background: p.color }}
                    />
                    {p.name}
                    <span className="text-xs font-normal text-[var(--tinta-3)]">{p.kind}</span>
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {categorias
                      ?.filter((c) => c.parent_id === p.id)
                      .map((c) => (
                        <Etiqueta key={c.id}>{c.name}</Etiqueta>
                      ))}
                  </div>
                </div>
              ))}
            </div>
          </Tarjeta>
        </div>

        <div className="space-y-4">
          <TarjetaRespaldos />

          <Tarjeta titulo="Añadir cuenta">
            <div className="space-y-3">
              <Campo etiqueta="Nombre">
                <Entrada
                  placeholder="Interbank Debito"
                  value={borrador.name ?? ""}
                  onChange={(e) => setBorrador({ ...borrador, name: e.target.value })}
                />
              </Campo>
              <Campo etiqueta="Banco">
                <Entrada
                  placeholder="interbank"
                  value={borrador.bank ?? ""}
                  onChange={(e) => setBorrador({ ...borrador, bank: e.target.value })}
                />
              </Campo>
              <Campo etiqueta="Tipo">
                <Selector
                  value={borrador.type}
                  onChange={(e) =>
                    setBorrador({ ...borrador, type: e.target.value as Cuenta["type"] })
                  }
                >
                  <option value="debito">Debito</option>
                  <option value="credito">Credito</option>
                  <option value="billetera">Billetera</option>
                  <option value="efectivo">Efectivo</option>
                </Selector>
              </Campo>
              <Campo etiqueta="Ultimos 4 digitos">
                <Entrada
                  maxLength={4}
                  value={borrador.last4 ?? ""}
                  onChange={(e) => setBorrador({ ...borrador, last4: e.target.value })}
                />
              </Campo>
              <Boton
                variante="primario"
                onClick={() => crear.mutate(borrador)}
                disabled={!borrador.name || crear.isPending}
              >
                <Plus size={15} /> Crear cuenta
              </Boton>
              {crear.isError && (
                <p className="text-xs" style={{ color: "var(--texto-malo)" }}>
                  {(crear.error as Error).message}
                </p>
              )}
            </div>
          </Tarjeta>

          <Aviso>
            Cuando añadas un banco nuevo, tambien hay que enseñarle a leer sus correos:
            agrega su remitente y sus patrones en{" "}
            <code>backend/app/ingest/parsers/patterns.yaml</code> y pruebalos en el
            laboratorio de la pantalla Correo.
          </Aviso>
        </div>
      </div>
    </div>
  );
}
