import { useRef, useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { CheckCircle2, FileUp, RefreshCw } from "lucide-react";
import { api } from "../lib/api";
import type {
  DocumentoImportado,
  EstadoCuentaImportado,
  ImportacionEstados,
  PeriodoInversion,
  PosicionInversion,
  RangoInversion,
  RentabilidadInversion,
  ResumenInversiones,
} from "../lib/api";
import { dolares, fecha, fechaHora, pctDe } from "../lib/format";
import { Encabezado } from "../App";
import {
  GraficoDividendos,
  GraficoGanancia,
  GraficoRentabilidadAcumulada,
  GraficoRentabilidadMensual,
  GraficoValor,
  Proyeccion,
  SelectorRango,
} from "../components/inversiones";
import { Aviso, Boton, Cargando, Indicador, Tarjeta, Vacio } from "../components/ui";

/**
 * Inversiones: tu cuenta de Hapi en dolares.
 *
 * Las operaciones llegan al momento por los correos de Hapi (provisionales) y
 * cada mes el estado de cuenta de Apex las confirma con sus importes oficiales.
 * Al subir un estado se ve antes cuanto se desvio lo que la app sabia por correo.
 */
export default function Inversiones() {
  const qc = useQueryClient();
  const [rango, setRango] = useState<RangoInversion>("1A");

  const resumen = useQuery({ queryKey: ["inv", "resumen"], queryFn: api.inversiones.resumen });
  const posiciones = useQuery({ queryKey: ["inv", "posiciones"], queryFn: api.inversiones.posiciones });
  const serie = useQuery({
    queryKey: ["inv", "serie", rango],
    queryFn: () => api.inversiones.serie(rango),
    placeholderData: keepPreviousData,
  });
  const rentabilidad = useQuery({ queryKey: ["inv", "rentabilidad"], queryFn: api.inversiones.rentabilidad });
  const dividendos = useQuery({ queryKey: ["inv", "dividendos"], queryFn: api.inversiones.dividendos });
  const estados = useQuery({ queryKey: ["inv", "estados"], queryFn: api.inversiones.estados });

  const refrescar = () => qc.invalidateQueries({ queryKey: ["inv"] });
  const sincronizar = useMutation({ mutationFn: api.inversiones.sincronizar, onSuccess: refrescar });

  if (resumen.isLoading) return <Pagina><Cargando /></Pagina>;
  if (resumen.error || !resumen.data) {
    return (
      <Pagina>
        <Aviso tono="critico">No se pudo cargar Inversiones: {String(resumen.error)}</Aviso>
      </Pagina>
    );
  }
  const r = resumen.data;
  const sinDatos = !estados.data?.length && !posiciones.data?.length && r.valor === 0;

  return (
    <Pagina
      acciones={
        <Boton onClick={() => sincronizar.mutate()} disabled={sincronizar.isPending}>
          <RefreshCw size={14} className={sincronizar.isPending ? "animate-spin" : ""} />
          Actualizar
        </Boton>
      }
    >
      <div className="space-y-4">
        <Avisos r={r} sincronizacion={sincronizar.data} error={sincronizar.error} />

        {sinDatos ? (
          <Tarjeta>
            <Vacio
              titulo="Todavía no hay datos de tu cuenta de Hapi"
              detalle="Sube tus estados de cuenta mensuales (PDF de Apex) más abajo y pulsa Actualizar para leer los correos de Hapi."
            />
          </Tarjeta>
        ) : (
          <>
            <Indicadores r={r} />

            <Tarjeta
              titulo="Valor de tu cuenta"
              subtitulo={
                serie.data?.detalle === "intradia"
                  ? "Hoy, cada pocos minutos, con lo que tienes ahora"
                  : "Al cierre de cada día de bolsa"
              }
            >
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <ResumenPeriodo rango={rango} r={r} periodo={serie.data?.periodo ?? null} />
                <SelectorRango valor={rango} onCambiar={setRango} />
              </div>
              <div style={{ opacity: serie.isPlaceholderData ? 0.6 : 1 }}>
                <GraficoValor puntos={serie.data?.puntos ?? []} intradia={serie.data?.detalle === "intradia"} />
                <GraficoGanancia puntos={serie.data?.puntos ?? []} intradia={serie.data?.detalle === "intradia"} />
              </div>
            </Tarjeta>

            <Tarjeta
              titulo="Posiciones"
              subtitulo={r.precios_al ? `Precios al ${fechaHora(r.precios_al)}` : undefined}
            >
              <TablaPosiciones filas={posiciones.data ?? []} efectivo={r.efectivo} />
            </Tarjeta>

            <Tarjeta
              titulo="Rentabilidad por mes"
              subtitulo="Sin contar tus depósitos ni retiros como ganancia. El S&P 500 incluye sus dividendos reinvertidos."
            >
              <GraficoRentabilidadMensual
                datos={rentabilidad.data?.por_mes ?? []}
                simbolo={rentabilidad.data?.referencia ?? r.referencia.simbolo}
              />
            </Tarjeta>

            <div className="grid gap-4 2xl:grid-cols-2">
              <Tarjeta className="min-w-0" titulo="Rentabilidad acumulada" subtitulo="Desde tu primer depósito">
                <GraficoRentabilidadAcumulada
                  puntos={rentabilidad.data?.acumulada ?? []}
                  simbolo={rentabilidad.data?.referencia ?? r.referencia.simbolo}
                />
              </Tarjeta>
              <Tarjeta className="min-w-0" titulo="Rentabilidad por año">
                <TablaRentabilidadAnual datos={rentabilidad.data} />
              </Tarjeta>
            </div>

            <Tarjeta
              titulo="Proyección"
              subtitulo="Cuánto podría valer tu cuenta si sigues aportando: con la rentabilidad que elijas y con la del S&P 500"
            >
              <Proyeccion valorInicial={r.valor} aporteMedio={r.aporte_mensual} />
            </Tarjeta>

            <div className="grid gap-4 lg:grid-cols-2">
              <Tarjeta
                className="min-w-0"
                titulo="Dividendos por mes"
                subtitulo={`Netos en total: ${dolares(r.dividendos.neto)} · retenido ${dolares(r.dividendos.retencion)}`}
              >
                <GraficoDividendos datos={dividendos.data?.por_mes ?? []} />
              </Tarjeta>
              <Tarjeta titulo="De dónde sale la ganancia" className="min-w-0">
                <Desglose r={r} />
              </Tarjeta>
            </div>
          </>
        )}

        <Tarjeta
          titulo="Estados de cuenta"
          subtitulo="El PDF mensual de Apex confirma lo que llegó por correo y fija los importes oficiales"
        >
          <SubirEstados onImportado={refrescar} />
          <TablaEstados filas={estados.data ?? []} />
        </Tarjeta>
      </div>
    </Pagina>
  );
}

function Pagina({ children, acciones }: { children: React.ReactNode; acciones?: React.ReactNode }) {
  return (
    <div className="p-4 md:p-6">
      <Encabezado
        titulo="Inversiones"
        descripcion="Tu cuenta de Hapi, en dólares. Las operaciones llegan por correo y el estado de cuenta de cada mes las confirma."
        acciones={acciones}
      />
      {children}
    </div>
  );
}

/* ------------------------------------------------------------------ avisos */

function Avisos({
  r,
  sincronizacion,
  error,
}: {
  r: ResumenInversiones;
  sincronizacion?: Awaited<ReturnType<typeof api.inversiones.sincronizar>>;
  error: unknown;
}) {
  return (
    <>
      {error ? <Aviso tono="critico">No se pudo actualizar: {String(error)}</Aviso> : null}
      {sincronizacion?.precios.error && (
        <Aviso tono="aviso">Precios: {sincronizacion.precios.error}</Aviso>
      )}
      {sincronizacion && !sincronizacion.precios.error && (
        <Aviso>
          {sincronizacion.correos.nuevos} correos nuevos de Hapi
          {sincronizacion.correos.repetidos ? ` (${sincronizacion.correos.repetidos} repetidos)` : ""}
          {sincronizacion.precios.configurado
            ? ` · ${sincronizacion.precios.cierres + sincronizacion.precios.intradia} precios nuevos`
            : ""}
          .
        </Aviso>
      )}
      {!r.configuracion.precios && (
        <Aviso>
          Sin precios en vivo: se valora con el precio del último estado de cuenta. Para ver el valor
          de hoy, crea una cuenta gratuita en alpaca.markets y pon ALPACA_KEY_ID y ALPACA_SECRET_KEY en
          el .env.
        </Aviso>
      )}
      {!r.configuracion.correo && (
        <Aviso tono="aviso">
          La lectura de correo no está configurada: las operaciones solo llegarán con los estados de cuenta.
        </Aviso>
      )}
      {r.ultimo_estado && !r.ultimo_estado.cuadra && (
        <Aviso tono="aviso">
          Lo registrado hasta {fecha(r.ultimo_estado.fin)} no coincide con el estado de cuenta de{" "}
          {r.ultimo_estado.periodo} (efectivo: {dolares(r.ultimo_estado.diferencia_efectivo)}). Revisa
          las operaciones provisionales.
        </Aviso>
      )}
      {r.avisos.map((a) => (
        <Aviso key={a} tono="aviso">
          {a}
        </Aviso>
      ))}
    </>
  );
}

/* ------------------------------------------------------------------ indicadores */

function Indicadores({ r }: { r: ResumenInversiones }) {
  const comparacion =
    r.referencia.rentabilidad_anual !== null
      ? `S&P 500 (${r.referencia.simbolo}): ${pctDe(r.referencia.rentabilidad_anual)} al año`
      : undefined;
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <Indicador
        etiqueta="Valor total"
        valor={dolares(r.valor)}
        variacion={r.dia.variacion_pct !== null ? r.dia.variacion_pct * 100 : null}
        detalle={r.dia.variacion !== null ? `hoy ${dolares(r.dia.variacion)}` : `efectivo ${dolares(r.efectivo)}`}
      />
      <Indicador
        etiqueta="Ganancia total"
        valor={dolares(r.ganancia)}
        variacion={r.ganancia_pct !== null ? r.ganancia_pct * 100 : null}
        detalle={`aportaste ${dolares(r.aportes)}`}
      />
      <Indicador
        etiqueta="Rentabilidad anual"
        valor={r.rentabilidad_anual !== null ? pctDe(r.rentabilidad_anual) : "—"}
        detalle={comparacion}
      />
      <Indicador
        etiqueta="Dividendos netos"
        valor={dolares(r.dividendos.neto)}
        detalle={`bruto ${dolares(r.dividendos.bruto)}`}
      />
    </div>
  );
}

const TEXTO_RANGO: Record<RangoInversion, string> = {
  "1D": "hoy",
  "1S": "en la última semana",
  "1M": "en el último mes",
  "3M": "en los últimos 3 meses",
  "6M": "en los últimos 6 meses",
  YTD: "en lo que va del año",
  "1A": "en el último año",
  TODO: "desde el inicio",
};

/**
 * Lo ganado en el rango del grafico. Hoy sale del precio de ahora (como el
 * indicador de arriba); el resto, de los cierres. El porcentaje no cuenta lo
 * depositado como ganancia.
 */
function ResumenPeriodo({
  rango,
  r,
  periodo,
}: {
  rango: RangoInversion;
  r: ResumenInversiones;
  periodo: PeriodoInversion | null;
}) {
  const datos =
    rango === "1D" && r.dia.variacion !== null
      ? { ganancia: r.dia.variacion, rentabilidad: r.dia.variacion_pct, referencia: null }
      : periodo;
  if (!datos) return null;
  return (
    <p className="flex flex-wrap items-baseline gap-x-2 text-sm">
      <span className="tabular font-semibold" style={{ color: colorSigno(datos.ganancia) }}>
        {datos.ganancia > 0 ? "+" : ""}
        {dolares(datos.ganancia)} ({pctDe(datos.rentabilidad)})
      </span>
      <span className="text-[var(--tinta-3)]">
        {TEXTO_RANGO[rango]}
        {datos.referencia !== null ? ` · S&P 500 ${pctDe(datos.referencia)}` : ""}
      </span>
    </p>
  );
}

/* ------------------------------------------------------------------ rentabilidad por anio */

function TablaRentabilidadAnual({ datos }: { datos?: RentabilidadInversion }) {
  if (!datos?.por_anio.length) return <Vacio titulo="Sin historia todavía" />;
  const anios = [...datos.por_anio].reverse();
  const primero = datos.por_anio[0];
  return (
    <div className="space-y-3">
      <div className="-mx-4 overflow-x-auto">
        <table className="w-full min-w-[480px] text-sm">
          <thead>
            <tr className="text-left text-xs text-[var(--tinta-3)]">
              <th className="px-4 py-2 font-medium">Año</th>
              <th className="px-2 py-2 text-right font-medium">Tú</th>
              <th className="px-2 py-2 text-right font-medium">S&amp;P 500</th>
              <th className="px-2 py-2 text-right font-medium">Ganancia</th>
              <th className="px-2 py-2 text-right font-medium" title="Lo que depositaste menos lo que retiraste">
                Aportaste
              </th>
              <th className="px-4 py-2 text-right font-medium">Valor al cierre</th>
            </tr>
          </thead>
          <tbody>
            {anios.map((a) => (
              <tr key={a.anio} className="border-t" style={{ borderColor: "var(--borde)" }}>
                <td className="whitespace-nowrap px-4 py-2 font-medium">
                  {a.anio}
                  {a.en_curso && <span className="ml-1.5 text-xs font-normal text-[var(--tinta-3)]">en curso</span>}
                </td>
                <td className="tabular px-2 py-2 text-right font-medium" style={{ color: colorSigno(a.rentabilidad) }}>
                  {pctDe(a.rentabilidad)}
                </td>
                <td className="tabular px-2 py-2 text-right text-[var(--tinta-2)]">{pctDe(a.referencia)}</td>
                <td className="tabular px-2 py-2 text-right">{dolares(a.ganancia)}</td>
                <td className="tabular px-2 py-2 text-right">{dolares(a.aportes)}</td>
                <td className="tabular px-4 py-2 text-right">{dolares(a.valor_final)}</td>
              </tr>
            ))}
            {datos.total && (
              <tr className="border-t-2 font-medium" style={{ borderColor: "var(--borde)" }}>
                <td className="whitespace-nowrap px-4 py-2">Desde el inicio</td>
                <td className="tabular px-2 py-2 text-right" style={{ color: colorSigno(datos.total.rentabilidad) }}>
                  {pctDe(datos.total.rentabilidad)}
                </td>
                <td className="tabular px-2 py-2 text-right text-[var(--tinta-2)]">{pctDe(datos.total.referencia)}</td>
                <td className="tabular px-2 py-2 text-right">{dolares(datos.total.ganancia)}</td>
                <td className="tabular px-2 py-2 text-right">{dolares(datos.total.aportes)}</td>
                <td className="tabular px-4 py-2 text-right">{dolares(datos.total.valor_final)}</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-[var(--tinta-3)]">
        {primero.anio} empieza con tu primer depósito. Cada año pesa igual sin importar cuánto tenías, por eso
        puede no coincidir con la rentabilidad anual de arriba, que sí tiene en cuenta cuánto dinero había.
      </p>
    </div>
  );
}

function Desglose({ r }: { r: ResumenInversiones }) {
  const filas: [string, number, string?][] = [
    ["Ganancia de lo que ya vendiste", r.realizada],
    ["Ganancia de lo que aún tienes", r.no_realizada],
    ["Dividendos netos", r.dividendos.neto],
    ["Intereses del depósito asegurado", r.intereses],
    ["Comisiones de depósitos", -r.costos.depositos, "Lo que costó pasar el dinero a Hapi"],
    ["Comisiones de retiros", -r.costos.retiros],
  ];
  if (r.ajustes) {
    filas.push([
      "Ajuste del saldo inicial",
      r.ajustes,
      "Lo que los correos anteriores al primer estado de cuenta no explicaban",
    ]);
  }
  return (
    <div className="space-y-3">
      <dl className="divide-y text-sm" style={{ borderColor: "var(--borde)" }}>
        {filas.map(([texto, valor, ayuda]) => (
          <div key={texto} className="flex items-baseline justify-between gap-3 py-2" title={ayuda}>
            <dt className="text-[var(--tinta-2)]">{texto}</dt>
            <dd className="tabular font-medium" style={{ color: valor < 0 ? "var(--texto-malo)" : undefined }}>
              {dolares(valor)}
            </dd>
          </div>
        ))}
      </dl>
      <p className="text-xs text-[var(--tinta-3)]">
        Las comisiones de compra y venta ({dolares(r.costos.operaciones)}) ya están dentro de las ganancias:
        forman parte del costo de cada acción.
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ posiciones */

function TablaPosiciones({ filas, efectivo }: { filas: PosicionInversion[]; efectivo: number }) {
  const navegar = useNavigate();
  if (!filas.length) return <Vacio titulo="No tienes acciones ahora mismo" />;
  return (
    <div className="-mx-4 overflow-x-auto">
      <table className="w-full min-w-[720px] text-sm">
        <thead>
          <tr className="text-left text-xs text-[var(--tinta-3)]">
            <th className="px-4 py-2 font-medium">Acción</th>
            <th className="px-2 py-2 text-right font-medium">Acciones</th>
            <th className="px-2 py-2 text-right font-medium">Precio</th>
            <th className="px-2 py-2 text-right font-medium">Hoy</th>
            <th className="px-2 py-2 text-right font-medium">Valor</th>
            <th className="px-2 py-2 font-medium">Peso</th>
            <th className="px-4 py-2 text-right font-medium">Ganancia</th>
          </tr>
        </thead>
        <tbody>
          {filas.map((p) => (
            <tr
              key={p.simbolo ?? p.nombre}
              onClick={() => p.simbolo && navegar(`/inversiones/${p.simbolo}`)}
              className="cursor-pointer border-t hover:bg-[var(--superficie-2)]"
              style={{ borderColor: "var(--borde)" }}
            >
              <td className="px-4 py-2">
                <div className="font-medium">{p.simbolo}</div>
                <div className="max-w-[220px] truncate text-xs text-[var(--tinta-3)]">{p.nombre}</div>
              </td>
              <td className="tabular px-2 py-2 text-right">
                {p.cantidad.toLocaleString("es-PE", { maximumFractionDigits: 5 })}
              </td>
              <td className="tabular px-2 py-2 text-right" title={fuentePrecio(p)}>
                {dolares(p.precio)}
              </td>
              <td className="tabular px-2 py-2 text-right" style={{ color: colorSigno(p.variacion_dia_pct) }}>
                {p.variacion_dia_pct !== null ? pctDe(p.variacion_dia_pct) : "—"}
              </td>
              <td className="tabular px-2 py-2 text-right font-medium">{dolares(p.valor)}</td>
              <td className="px-2 py-2">
                <Peso peso={p.peso} />
              </td>
              <td className="tabular px-4 py-2 text-right" style={{ color: colorSigno(p.ganancia) }}>
                <div className="font-medium">{dolares(p.ganancia)}</div>
                <div className="text-xs">{pctDe(p.ganancia_pct)}</div>
              </td>
            </tr>
          ))}
          <tr className="border-t" style={{ borderColor: "var(--borde)" }}>
            <td className="px-4 py-2 text-[var(--tinta-2)]" colSpan={4}>
              Efectivo (caja y depósito asegurado)
            </td>
            <td className="tabular px-2 py-2 text-right font-medium">{dolares(efectivo)}</td>
            <td colSpan={2} />
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function fuentePrecio(p: PosicionInversion): string | undefined {
  const textos: Record<string, string> = {
    intradia: "Precio de hoy",
    cierre: "Cierre del último día de bolsa",
    estado_cuenta: "Precio de cierre del último estado de cuenta",
    operacion: "Precio de tu última operación",
  };
  return p.precio_fuente ? `${textos[p.precio_fuente]}${p.precio_al ? ` (${fechaHora(p.precio_al)})` : ""}` : undefined;
}

/** Barra de peso: una pista y su relleno, del mismo tono. */
function Peso({ peso }: { peso: number | null }) {
  if (peso === null) return null;
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-20 overflow-hidden rounded-full" style={{ background: "var(--superficie-2)" }}>
        <div className="h-full rounded-full" style={{ width: `${Math.min(peso * 100, 100)}%`, background: "var(--serie-1)" }} />
      </div>
      <span className="tabular text-xs text-[var(--tinta-2)]">{(peso * 100).toFixed(1)}%</span>
    </div>
  );
}

export function colorSigno(v: number | null | undefined): string | undefined {
  if (!v) return undefined;
  return v > 0 ? "var(--texto-bien)" : "var(--texto-malo)";
}

/* ------------------------------------------------------------------ estados de cuenta */

function SubirEstados({ onImportado }: { onImportado: () => void }) {
  const entrada = useRef<HTMLInputElement>(null);
  const [archivos, setArchivos] = useState<File[]>([]);
  const previa = useMutation({ mutationFn: api.inversiones.previsualizar });
  const importar = useMutation({
    mutationFn: api.inversiones.importar,
    onSuccess: () => {
      onImportado();
      previa.reset();
      setArchivos([]);
    },
  });

  function elegir(lista: FileList | null) {
    const pdfs = Array.from(lista ?? []).filter((f) => f.name.toLowerCase().endsWith(".pdf"));
    setArchivos(pdfs);
    importar.reset();
    if (pdfs.length) previa.mutate(pdfs);
  }

  return (
    <div className="mb-4 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <input
          ref={entrada}
          type="file"
          accept=".pdf,application/pdf"
          multiple
          className="hidden"
          onChange={(e) => elegir(e.target.files)}
        />
        <Boton onClick={() => entrada.current?.click()} disabled={previa.isPending || importar.isPending}>
          <FileUp size={14} />
          Subir estados de cuenta
        </Boton>
        <span className="text-xs text-[var(--tinta-3)]">
          Puedes subir todos a la vez: los ya importados se saltan.
        </span>
      </div>

      {previa.isPending && <Cargando texto={`Leyendo ${archivos.length} PDF…`} />}
      {previa.error && <Aviso tono="critico">{String(previa.error)}</Aviso>}
      {importar.error && <Aviso tono="critico">{String(importar.error)}</Aviso>}
      {importar.data && (
        <Aviso>
          <span className="inline-flex items-center gap-1.5">
            <CheckCircle2 size={14} style={{ color: "var(--bien)" }} />
            Importados {importar.data.importables} estados de cuenta.
          </span>
        </Aviso>
      )}
      {previa.data && !importar.data && (
        <VistaPrevia
          resultado={previa.data}
          importando={importar.isPending}
          onImportar={() => importar.mutate(archivos)}
        />
      )}
    </div>
  );
}

function VistaPrevia({
  resultado,
  importando,
  onImportar,
}: {
  resultado: ImportacionEstados;
  importando: boolean;
  onImportar: () => void;
}) {
  const conError = resultado.documentos.filter((d) => d.estado === "error");
  const nuevos = resultado.documentos.filter((d) => d.estado === "nuevo");
  const yaEstaban = resultado.documentos.length - conError.length - nuevos.length;
  const bloqueado = conError.length > 0 || resultado.errores.length > 0 || nuevos.length === 0;
  return (
    <div className="space-y-3 rounded-lg border p-3" style={{ borderColor: "var(--borde)" }}>
      <p className="text-sm text-[var(--tinta-2)]">
        {nuevos.length} nuevos{yaEstaban ? ` · ${yaEstaban} ya importados` : ""}
        {conError.length ? ` · ${conError.length} con errores` : ""}. Nada se guarda hasta que pulses
        Importar.
      </p>
      {resultado.errores.map((e) => (
        <Aviso key={e} tono="critico">{e}</Aviso>
      ))}
      {conError.map((d) => (
        <Aviso key={d.nombre} tono="critico">
          <strong>{d.nombre}</strong>: {d.errores.join("; ")}
        </Aviso>
      ))}
      {nuevos.length > 0 && (
        <div className="-mx-3 overflow-x-auto">
          <table className="w-full min-w-[620px] text-sm">
            <thead>
              <tr className="text-left text-xs text-[var(--tinta-3)]">
                <th className="px-3 py-1.5 font-medium">Mes</th>
                <th className="px-2 py-1.5 text-right font-medium">Confirmadas por correo</th>
                <th className="px-2 py-1.5 text-right font-medium">Nuevas</th>
                <th className="px-2 py-1.5 text-right font-medium">Correos no recogidos</th>
                <th className="px-3 py-1.5 text-right font-medium">Desfase de la app</th>
              </tr>
            </thead>
            <tbody>
              {nuevos.map((d) => (
                <FilaPrevia key={d.nombre} d={d} />
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="flex justify-end">
        <Boton variante="primario" onClick={onImportar} disabled={bloqueado || importando}>
          {importando ? "Importando…" : `Importar ${nuevos.length} estados`}
        </Boton>
      </div>
    </div>
  );
}

/**
 * El desfase es lo que la app calculaba por correo frente a lo que dice el
 * estado, en dolares al precio de cierre. Solo tiene sentido si ese mes ya se
 * seguia por correo.
 */
function FilaPrevia({ d }: { d: DocumentoImportado }) {
  const c = d.comparacion;
  const detalle = c?.acciones.length
    ? c.acciones.map((a) => `${a.simbolo}: app ${a.segun_app} / estado ${a.segun_estado}`).join(" · ")
    : undefined;
  return (
    <tr className="border-t" style={{ borderColor: "var(--borde)" }}>
      <td className="px-3 py-1.5 font-medium">{d.periodo}</td>
      <td className="tabular px-2 py-1.5 text-right">{d.conciliadas_con_correo}</td>
      <td className="tabular px-2 py-1.5 text-right">{d.operaciones_nuevas}</td>
      <td className="tabular px-2 py-1.5 text-right">{d.correos_descartados || "—"}</td>
      <td className="tabular px-3 py-1.5 text-right" title={detalle}>
        {c && c.seguido_por_correo ? (
          <span style={{ color: Math.abs(c.total) >= 0.01 ? "var(--texto-malo)" : "var(--texto-bien)" }}>
            {Math.abs(c.total) < 0.01 ? "cuadra" : dolares(c.total)}
          </span>
        ) : (
          <span className="text-[var(--tinta-3)]">sin correos</span>
        )}
      </td>
    </tr>
  );
}

function TablaEstados({ filas }: { filas: EstadoCuentaImportado[] }) {
  if (!filas.length) return null;
  return (
    <div className="-mx-4 overflow-x-auto">
      <table className="w-full min-w-[640px] text-sm">
        <thead>
          <tr className="text-left text-xs text-[var(--tinta-3)]">
            <th className="px-4 py-2 font-medium">Mes</th>
            <th className="px-2 py-2 text-right font-medium">Total al cierre</th>
            <th className="px-2 py-2 text-right font-medium">Operaciones</th>
            <th className="px-2 py-2 text-right font-medium">Con correo</th>
            <th className="px-4 py-2 text-right font-medium">Correos no recogidos</th>
          </tr>
        </thead>
        <tbody>
          {filas.map((e) => (
            <tr key={e.periodo} className="border-t" style={{ borderColor: "var(--borde)" }}>
              <td className="px-4 py-2 font-medium" title={e.archivo}>{e.periodo}</td>
              <td className="tabular px-2 py-2 text-right">{dolares(e.total)}</td>
              <td className="tabular px-2 py-2 text-right">{e.operaciones}</td>
              <td
                className="tabular px-2 py-2 text-right"
                title={e.fechas_estimadas ? `${e.fechas_estimadas} con la fecha deducida de la liquidación` : undefined}
              >
                {e.con_correo}
              </td>
              <td className="tabular px-4 py-2 text-right">{e.correos_no_recogidos || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
