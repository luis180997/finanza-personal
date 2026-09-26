import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Wallet } from "lucide-react";
import { api } from "../lib/api";
import type { Direccion, Necesidad } from "../lib/api";
import { leerMonto, soles } from "../lib/format";
import { Encabezado } from "../App";
import {
  AreaTexto,
  Aviso,
  Boton,
  Campo,
  Cargando,
  Entrada,
  Selector,
  Tarjeta,
} from "../components/ui";

/** Atajos: lo que se registra a mano casi siempre cae en estas gavetas. */
const ATAJOS = [
  { texto: "Almuerzo", categoria: "Almuerzo", necesidad: "esencial" as const },
  { texto: "Taxi", categoria: "Taxi", necesidad: "esencial" as const },
  { texto: "Pasaje", categoria: "Transporte publico", necesidad: "esencial" as const },
  { texto: "Mercado", categoria: "Mercado y supermercado", necesidad: "esencial" as const },
  { texto: "Cafe", categoria: "Cafe", necesidad: "discrecional" as const },
  { texto: "Snack", categoria: "Snacks", necesidad: "discrecional" as const },
  { texto: "Delivery", categoria: "Delivery", necesidad: "evitable" as const },
  { texto: "Farmacia", categoria: "Farmacia", necesidad: "esencial" as const },
  { texto: "Salida", categoria: "Salidas y bares", necesidad: "discrecional" as const },
];

function ahoraLocalISO(): string {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16);
}

export default function Registrar() {
  const qc = useQueryClient();
  const { data: categorias } = useQuery({ queryKey: ["categorias"], queryFn: api.categorias });
  const { data: cuentas } = useQuery({ queryKey: ["cuentas"], queryFn: api.cuentas });

  const [monto, setMonto] = useState("");
  const [direccion, setDireccion] = useState<Direccion>("gasto");
  const [categoriaId, setCategoriaId] = useState<number | "">("");
  const [necesidad, setNecesidad] = useState<Necesidad | "">("");
  const [cuentaId, setCuentaId] = useState<number | "">("");
  const [comercio, setComercio] = useState("");
  const [descripcion, setDescripcion] = useState("");
  const [cuando, setCuando] = useState(ahoraLocalISO());
  const [notas, setNotas] = useState("");
  const [ok, setOk] = useState<string | null>(null);
  const [errorMonto, setErrorMonto] = useState<string | null>(null);

  const cuentaEfectivo = useMemo(
    () => cuentas?.find((c) => c.bank === "efectivo"),
    [cuentas],
  );

  const arbol = useMemo(() => {
    if (!categorias) return [];
    const padres = categorias.filter((c) => !c.parent_id && c.kind === direccion);
    return padres.map((p) => ({
      padre: p,
      hijos: categorias.filter((c) => c.parent_id === p.id),
    }));
  }, [categorias, direccion]);

  const crear = useMutation({
    mutationFn: api.crearMovimiento,
    onSuccess: (tx) => {
      setOk(`Registrado: ${soles(tx.amount)} en ${tx.category_name ?? "sin categoria"}`);
      setMonto("");
      setComercio("");
      setDescripcion("");
      setNotas("");
      setCuando(ahoraLocalISO());
      qc.invalidateQueries({ queryKey: ["resumen"] });
      qc.invalidateQueries({ queryKey: ["movimientos"] });
      qc.invalidateQueries({ queryKey: ["mensual"] });
      setTimeout(() => setOk(null), 4000);
    },
  });

  function aplicarAtajo(a: (typeof ATAJOS)[number]) {
    const cat = categorias?.find((c) => c.name === a.categoria);
    if (cat) setCategoriaId(cat.id);
    setNecesidad(a.necesidad);
    setDireccion("gasto");
  }

  function enviar(e: React.FormEvent) {
    e.preventDefault();
    const valor = leerMonto(monto);
    if (!Number.isFinite(valor) || valor <= 0) {
      setErrorMonto("El monto no es un número mayor que cero. Ejemplos: 12.50 · 12,50 · 1,234.50");
      return;
    }
    setErrorMonto(null);
    crear.mutate({
      amount: valor,
      direction: direccion,
      account_id: cuentaId === "" ? (cuentaEfectivo?.id ?? null) : cuentaId,
      category_id: categoriaId === "" ? null : categoriaId,
      necessity: necesidad === "" ? null : necesidad,
      merchant: comercio || null,
      description: descripcion || null,
      notes: notas || null,
      occurred_at: cuando.length === 16 ? `${cuando}:00` : cuando,
    });
  }

  if (!categorias || !cuentas) return <div className="p-6"><Cargando /></div>;

  return (
    <div className="p-4 md:p-6">
      <Encabezado
        titulo="Registrar gasto"
        descripcion="Para lo que el correo no ve: efectivo, propinas, menu del dia, pasajes. Se guarda en la cuenta Efectivo salvo que elijas otra."
      />

      <div className="grid gap-4 lg:grid-cols-3">
        <form onSubmit={enviar} className="lg:col-span-2">
          <Tarjeta>
            <div className="mb-4 flex flex-wrap gap-2">
              {ATAJOS.map((a) => (
                <button
                  key={a.texto}
                  type="button"
                  onClick={() => aplicarAtajo(a)}
                  className="rounded-full border px-3 py-1.5 text-xs font-medium hover:bg-[var(--superficie-2)]"
                  style={{ borderColor: "var(--borde)" }}
                >
                  {a.texto}
                </button>
              ))}
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <Campo etiqueta="Monto (S/)">
                <Entrada
                  autoFocus
                  inputMode="decimal"
                  placeholder="0.00"
                  value={monto}
                  onChange={(e) => setMonto(e.target.value)}
                  className="tabular text-2xl font-semibold"
                  required
                />
              </Campo>

              <Campo etiqueta="Tipo">
                <Selector
                  value={direccion}
                  onChange={(e) => {
                    setDireccion(e.target.value as Direccion);
                    setCategoriaId("");
                  }}
                >
                  <option value="gasto">Gasto</option>
                  <option value="ingreso">Ingreso</option>
                  <option value="transferencia">Transferencia entre mis cuentas</option>
                </Selector>
              </Campo>

              <Campo etiqueta="Categoria">
                <Selector
                  value={categoriaId}
                  onChange={(e) =>
                    setCategoriaId(e.target.value === "" ? "" : Number(e.target.value))
                  }
                >
                  <option value="">Que el sistema la proponga</option>
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
                </Selector>
              </Campo>

              <Campo
                etiqueta="Necesidad"
                hint="Esto alimenta el indicador de fuga del panel"
              >
                <Selector
                  value={necesidad}
                  onChange={(e) => setNecesidad(e.target.value as Necesidad | "")}
                >
                  <option value="">Sin marcar</option>
                  <option value="esencial">Esencial</option>
                  <option value="discrecional">Discrecional</option>
                  <option value="evitable">Evitable</option>
                </Selector>
              </Campo>

              <Campo etiqueta="Cuenta">
                <Selector
                  value={cuentaId}
                  onChange={(e) =>
                    setCuentaId(e.target.value === "" ? "" : Number(e.target.value))
                  }
                >
                  <option value="">Efectivo (por defecto)</option>
                  {cuentas.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </Selector>
              </Campo>

              <Campo etiqueta="Fecha y hora">
                <Entrada
                  type="datetime-local"
                  value={cuando}
                  onChange={(e) => setCuando(e.target.value)}
                />
              </Campo>

              <Campo etiqueta="Comercio o persona" hint="Opcional, pero mejora el aprendizaje">
                <Entrada
                  placeholder="Menu La Esquina"
                  value={comercio}
                  onChange={(e) => setComercio(e.target.value)}
                />
              </Campo>

              <Campo etiqueta="Descripcion">
                <Entrada
                  placeholder="Almuerzo del martes"
                  value={descripcion}
                  onChange={(e) => setDescripcion(e.target.value)}
                />
              </Campo>

              <div className="sm:col-span-2">
                <Campo etiqueta="Notas">
                  <AreaTexto
                    rows={2}
                    placeholder="Contexto que quieras recordar"
                    value={notas}
                    onChange={(e) => setNotas(e.target.value)}
                  />
                </Campo>
              </div>
            </div>

            <div className="mt-5 flex items-center gap-3">
              <Boton type="submit" variante="primario" disabled={crear.isPending || !monto}>
                <Check size={16} />
                {crear.isPending ? "Guardando…" : "Guardar movimiento"}
              </Boton>
              {ok && (
                <span className="text-sm" style={{ color: "var(--texto-bien)" }}>
                  {ok}
                </span>
              )}
              {errorMonto && (
                <span className="text-sm" style={{ color: "var(--texto-malo)" }}>
                  {errorMonto}
                </span>
              )}
              {crear.isError && (
                <span className="text-sm" style={{ color: "var(--texto-malo)" }}>
                  {(crear.error as Error).message}
                </span>
              )}
            </div>
          </Tarjeta>
        </form>

        <div className="space-y-4">
          <Tarjeta titulo="Como se clasifica">
            <ol className="space-y-2 text-sm text-[var(--tinta-2)]">
              <li>
                <b>1. Tus reglas.</b> Si alguna coincide, manda ella.
              </li>
              <li>
                <b>2. Memoria del comercio.</b> Lo que elegiste la ultima vez para ese
                mismo nombre.
              </li>
              <li>
                <b>3. Diccionario.</b> Comercios peruanos conocidos (Rappi, Tottus,
                Inkafarma…).
              </li>
              <li>
                <b>4. Sin clasificar.</b> Cae a la bandeja de revision.
              </li>
            </ol>
            <p className="mt-3 text-xs text-[var(--tinta-3)]">
              Cada correccion tuya entra en el paso 2, asi que el sistema acierta mas con
              el uso.
            </p>
          </Tarjeta>

          <Tarjeta titulo="Cuentas disponibles">
            <ul className="space-y-2 text-sm">
              {cuentas.map((c) => (
                <li key={c.id} className="flex items-center gap-2">
                  <Wallet size={14} className="text-[var(--tinta-3)]" />
                  <span>{c.name}</span>
                  <span className="ml-auto text-xs text-[var(--tinta-3)]">{c.type}</span>
                </li>
              ))}
            </ul>
          </Tarjeta>

          <Aviso>
            Si el gasto ya llego por correo del banco, no lo registres aqui: se duplicaria.
            Esta pantalla es solo para lo que ningun banco te notifica.
          </Aviso>
        </div>
      </div>
    </div>
  );
}
