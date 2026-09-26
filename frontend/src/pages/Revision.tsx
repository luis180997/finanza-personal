import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, CircleSlash, Copy, HelpCircle, Sparkles } from "lucide-react";
import { api } from "../lib/api";
import type { Movimiento } from "../lib/api";
import { ETIQUETA_ORIGEN, fechaHora, importe, leerMonto } from "../lib/format";
import { Encabezado } from "../App";
import { SelectorCategoria } from "./Movimientos";
import { Boton, Cargando, Etiqueta, Tarjeta, Vacio } from "../components/ui";

/**
 * Bandeja de triaje. Aqui aterriza lo que el sistema no pudo clasificar con
 * seguridad, o lo que sospecha que ya conto dos veces. La idea es despacharla
 * en segundos, no editar campo por campo.
 */
export default function Revision() {
  const qc = useQueryClient();
  const [seleccion, setSeleccion] = useState<Set<number>>(new Set());

  const { data, isLoading } = useQuery({ queryKey: ["revision"], queryFn: api.colaRevision });
  const { data: categorias } = useQuery({ queryKey: ["categorias"], queryFn: api.categorias });

  function refrescar() {
    qc.invalidateQueries({ queryKey: ["revision"] });
    qc.invalidateQueries({ queryKey: ["movimientos"] });
    qc.invalidateQueries({ queryKey: ["resumen"] });
  }

  const editar = useMutation({
    mutationFn: ({ id, datos }: { id: number; datos: Record<string, unknown> }) =>
      api.editarMovimiento(id, datos),
    onSuccess: refrescar,
  });

  const lote = useMutation({
    mutationFn: api.editarLote,
    onSuccess: () => {
      setSeleccion(new Set());
      refrescar();
    },
  });

  function alternar(id: number) {
    setSeleccion((s) => {
      const n = new Set(s);
      n.has(id) ? n.delete(id) : n.add(id);
      return n;
    });
  }

  if (isLoading) return <div className="p-6"><Cargando /></div>;

  return (
    <div className="p-4 md:p-6">
      <Encabezado
        titulo="Por revisar"
        descripcion={
          "El importe y la fecha ya estan bien: eso lo lee el correo. Aqui solo falta " +
          "que decidas TU una de dos cosas — en que categoria va, o si de verdad es un " +
          "gasto tuyo. Cada ficha dice cual de las dos y por que."
        }
        acciones={
          seleccion.size > 0 && (
            <>
              <span className="text-sm text-[var(--tinta-3)]">
                {seleccion.size} seleccionados
              </span>
              <Boton
                variante="primario"
                onClick={() => lote.mutate({ ids: [...seleccion], status: "confirmada" })}
              >
                <Check size={15} /> Confirmar
              </Boton>
              <Boton onClick={() => lote.mutate({ ids: [...seleccion], status: "ignorada" })}>
                <CircleSlash size={15} /> Ignorar
              </Boton>
              <Boton
                variante="peligro"
                onClick={() => lote.mutate({ ids: [...seleccion], status: "duplicada" })}
              >
                <Copy size={15} /> Marcar duplicados
              </Boton>
            </>
          )
        }
      />

      {!data?.length ? (
        <Tarjeta>
          <Vacio
            titulo="Bandeja vacia"
            detalle="Todo esta clasificado. Cuando llegue un correo que el sistema no entienda, aparecera aqui."
          />
        </Tarjeta>
      ) : (
        <div className="space-y-3">
          {data.map((m) => (
            <FichaRevision
              key={m.id}
              m={m}
              categorias={categorias ?? []}
              seleccionado={seleccion.has(m.id)}
              onSeleccionar={() => alternar(m.id)}
              onEditar={(datos) => editar.mutate({ id: m.id, datos })}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function FichaRevision({
  m,
  categorias,
  seleccionado,
  onSeleccionar,
  onEditar,
}: {
  m: Movimiento;
  categorias: import("../lib/api").Categoria[];
  seleccionado: boolean;
  onSeleccionar: () => void;
  onEditar: (datos: Record<string, unknown>) => void;
}) {
  const confianzaBaja = m.confidence < 0.75;
  // Cuando el movimiento entra por una deduccion nuestra (envio a ti mismo,
  // casa de cambio), la nota del sistema es la misma frase que el motivo que ya
  // se muestra arriba. Repetirla alarga la ficha sin decir nada nuevo.
  const notaRedundante = m.motivos.some(
    (mo) => mo.clave === "envio_a_mi_mismo" || mo.clave === "casa_de_cambio",
  );

  return (
    <article
      className="rounded-xl border p-4"
      style={{
        borderColor: seleccionado ? "var(--serie-1)" : "var(--borde)",
        background: "var(--superficie)",
      }}
    >
      <div className="flex flex-wrap items-start gap-3">
        <input
          type="checkbox"
          checked={seleccionado}
          onChange={onSeleccionar}
          className="mt-1 h-4 w-4"
          aria-label="Seleccionar movimiento"
        />

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-2">
            <span className="font-medium">
              {m.merchant?.replace(/\b\w/g, (c) => c.toUpperCase()) ?? m.description ?? "Sin comercio"}
            </span>
            <span className="tabular text-lg font-semibold">{importe(m.amount, m.currency)}</span>
            <span className="text-xs text-[var(--tinta-3)]">{fechaHora(m.occurred_at)}</span>
          </div>

          {m.motivo_resumen && (
            <div className="mt-1 text-xs font-medium" style={{ color: "var(--aviso)" }}>
              {m.motivo_resumen}
            </div>
          )}

          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            <Etiqueta>{ETIQUETA_ORIGEN[m.source]}</Etiqueta>
            {m.account_name && <Etiqueta>{m.account_name}</Etiqueta>}
            {m.parser && <Etiqueta titulo="Parser que lo reconocio">{m.parser}</Etiqueta>}
            {confianzaBaja && (
              <Etiqueta
                color="var(--aviso)"
                titulo={
                  "Confianza combinada: lo seguro que esta el parser al leer el correo " +
                  "por lo seguro que esta el clasificador al elegir categoria. Un 30% " +
                  "suele significar que el correo se leyo bien pero nadie supo en que " +
                  "categoria va."
                }
              >
                Confianza {Math.round(m.confidence * 100)}%
              </Etiqueta>
            )}
            {m.duplicate_of_id && (
              <Etiqueta color="var(--critico)">Duplicado de #{m.duplicate_of_id}</Etiqueta>
            )}
          </div>

          {/* Por que esta aqui. Un aviso que no dice que hacer no sirve. */}
          {m.motivos.length > 0 && (
            <ul className="mt-2.5 space-y-1.5">
              {m.motivos.map((mo) => (
                <li key={mo.clave} className="flex items-start gap-2 text-xs">
                  <HelpCircle
                    size={13}
                    className="mt-0.5 shrink-0"
                    style={{
                      color: mo.clave === "duplicado" ? "var(--critico)" : "var(--aviso)",
                    }}
                  />
                  <span>
                    <span className="text-[var(--tinta-2)]">{mo.texto}</span>{" "}
                    <span className="text-[var(--tinta-3)]">{mo.accion}</span>
                  </span>
                </li>
              ))}
            </ul>
          )}

          {m.notes && !notaRedundante && (
            <p className="mt-2 text-xs text-[var(--tinta-3)]">{m.notes}</p>
          )}
          {m.merchant_raw && m.merchant_raw !== m.merchant && (
            <p className="mt-1 font-mono text-xs text-[var(--tinta-3)]">
              texto original: {m.merchant_raw}
            </p>
          )}
          {m.operation_number && (
            <p className="mt-1 font-mono text-xs text-[var(--tinta-3)]">
              operacion: {m.operation_number}
            </p>
          )}
        </div>

        <div className="flex w-full flex-col gap-2 sm:w-64">
          {m.currency !== "PEN" && <ImporteEnSoles m={m} onEditar={onEditar} />}
          {/* `status` explicito: sin el, el backend da por confirmado todo lo
              que reciba categoria y la ficha se desmonta en el acto, antes de
              que puedas marcar la necesidad. La ficha se va cuando TU lo digas. */}
          <SelectorCategoria
            valor={m.category_id}
            categorias={categorias}
            direccion={m.direction}
            onChange={(id) => onEditar({ category_id: id, status: "por_revisar" })}
          />
          <select
            value={m.necessity ?? ""}
            onChange={(e) =>
              onEditar({ necessity: e.target.value || null, status: "por_revisar" })
            }
            className="w-full rounded-md border bg-transparent px-2 py-1 text-xs outline-none"
            style={{ borderColor: "var(--borde)" }}
          >
            <option value="">Necesidad sin marcar</option>
            <option value="esencial">Esencial</option>
            <option value="discrecional">Discrecional</option>
            <option value="evitable">Evitable</option>
          </select>
          <div className="flex gap-2">
            <Boton
              variante="primario"
              className="flex-1"
              onClick={() => onEditar({ status: "confirmada" })}
            >
              <Check size={14} /> Confirmar
            </Boton>
            <Boton onClick={() => onEditar({ status: "ignorada" })} title="No es un gasto real">
              <CircleSlash size={14} />
            </Boton>
          </div>
          {m.category_id === null && (
            <p className="flex items-center gap-1 text-xs text-[var(--tinta-3)]">
              <Sparkles size={11} /> Lo que elijas queda aprendido para este comercio.
            </p>
          )}
        </div>
      </div>
    </article>
  );
}

/**
 * El BCP avisa algunos cobros en dolares ("$ 8.85") y los debita en soles, pero el
 * correo no dice cuantos. El importe en soles lo escribes tu, mirando la operacion
 * en la app del banco: no se inventa un tipo de cambio.
 */
function ImporteEnSoles({
  m,
  onEditar,
}: {
  m: Movimiento;
  onEditar: (datos: Record<string, unknown>) => void;
}) {
  const [texto, setTexto] = useState("");
  const [error, setError] = useState<string | null>(null);

  function guardar() {
    const valor = leerMonto(texto);
    if (!Number.isFinite(valor) || valor <= 0) {
      setError("Escribe el importe en soles, por ejemplo 31.20");
      return;
    }
    setError(null);
    // La ficha sigue en la bandeja hasta que pulses Confirmar.
    onEditar({ amount: valor, currency: "PEN", status: "por_revisar" });
  }

  return (
    <div className="rounded-md border p-2" style={{ borderColor: "var(--aviso)" }}>
      <span className="block text-xs text-[var(--tinta-2)]">
        Soles que te cobró el banco por {importe(m.amount, m.currency)}
      </span>
      <div className="mt-1 flex gap-1.5">
        <input
          inputMode="decimal"
          placeholder="31.20"
          value={texto}
          onChange={(e) => setTexto(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") guardar();
          }}
          aria-label="Importe en soles"
          className="tabular w-full rounded-md border bg-transparent px-2 py-1 text-xs outline-none"
          style={{ borderColor: "var(--borde)" }}
        />
        <Boton className="px-2 py-1 text-xs" onClick={guardar}>
          Guardar
        </Boton>
      </div>
      {error && (
        <p className="mt-1 text-xs" style={{ color: "var(--texto-malo)" }}>
          {error}
        </p>
      )}
    </div>
  );
}
