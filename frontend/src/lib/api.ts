/**
 * Cliente de la API. Un solo lugar donde vive el contrato con el backend.
 * En desarrollo Vite hace proxy de /api hacia http://127.0.0.1:8000.
 */

export type Direccion = "gasto" | "ingreso" | "transferencia";
export type Necesidad = "esencial" | "discrecional" | "evitable";
/** Con que pagaste, que no es lo mismo que de que cuenta salio: un yapeo sale
 *  de BCP Debito pero se paga por Yape. */
export type MedioPago =
  | "efectivo"
  | "debito"
  | "credito"
  | "yape"
  | "plin"
  | "transferencia"
  | "otro";
export type Estado = "confirmada" | "por_revisar" | "duplicada" | "ignorada";
export type Origen = "gmail" | "manual" | "excel";

export interface Cuenta {
  id: number;
  name: string;
  bank: string;
  type: "debito" | "credito" | "billetera" | "efectivo";
  currency: string;
  last4: string | null;
  aliases: string[];
  billing_day: number | null;
  active: boolean;
}

export interface Categoria {
  id: number;
  name: string;
  parent_id: number | null;
  kind: Direccion;
  color: string;
  icon: string;
  default_necessity: Necesidad | null;
  is_system: boolean;
  sort: number;
}

export interface Movimiento {
  id: number;
  occurred_at: string;
  booking_date: string;
  amount: number;
  currency: string;
  direction: Direccion;
  account_id: number | null;
  account_name: string | null;
  payment_method: MedioPago | null;
  category_id: number | null;
  category_name: string | null;
  category_parent: string | null;
  category_color: string | null;
  merchant: string | null;
  merchant_raw: string | null;
  description: string | null;
  /** Numero de operacion del banco, para cotejar con tu banca */
  operation_number: string | null;
  necessity: Necesidad | null;
  tags: string[];
  notes: string | null;
  is_recurring: boolean;
  source: Origen;
  status: Estado;
  confidence: number;
  parser: string | null;
  email_id: number | null;
  duplicate_of_id: number | null;
  /** Lo registraste o corregiste tu: protegido contra borrados y reprocesos. */
  locked_by_user: boolean;
  /** Por que pide atencion. Solo viene cuando esta por revisar. */
  motivos: MotivoRevision[];
  motivo_resumen: string | null;
}

export interface MotivoRevision {
  clave: string;
  texto: string;
  accion: string;
}

/** Lo ultimo que tocaste en Movimientos: desde ahi sigue lo que falta validar. */
export interface UltimaModificacion {
  /** Cuando lo tocaste (ISO, UTC). */
  momento: string;
  movimiento: Movimiento;
}

export interface PaginaMovimientos {
  items: Movimiento[];
  total: number;
  pagina: number;
  tamano: number;
  suma_gastos: number;
  suma_ingresos: number;
}

export interface Regla {
  id: number;
  name: string;
  priority: number;
  active: boolean;
  field: string;
  op: string;
  value: string;
  min_amount: number | null;
  max_amount: number | null;
  direction: Direccion | null;
  set_category_id: number | null;
  set_necessity: Necesidad | null;
  set_merchant: string | null;
  set_recurring: boolean | null;
  stop: boolean;
  hits: number;
}

export interface Kpis {
  gastos: number;
  ingresos: number;
  neto: number;
  tasa_ahorro: number;
  gasto_evitable: number;
  pct_evitable: number;
  promedio_diario: number;
  /** null si aun no hay historial suficiente para predecir el cierre */
  proyeccion_periodo: number | null;
  dias_con_gasto: number;
  dias_sin_gasto: number;
  num_movimientos: number;
  ticket_promedio: number;
  variacion_gastos: number | null;
  variacion_ingresos: number | null;
  /** El periodo anterior entero: la linea de referencia del grafico de ritmo. */
  gastos_periodo_anterior: number;
  /** Lo gastado en los mismos dias del periodo anterior: contra esto se mide la variacion. */
  gastos_anterior_comparable: number;
  /** true si el periodo esta en curso y se compara solo con los mismos dias. */
  comparacion_parcial: boolean;
}

export interface PuntoDiario {
  fecha: string;
  /** null en los dias que aun no han llegado. */
  gasto: number | null;
  ingreso: number | null;
  /** Gasto real acumulado; null despues de hoy. */
  acumulado: number | null;
  /** Desde hoy hasta el cierre, al ritmo historico; null si no se proyecta. */
  proyeccion: number | null;
}

export interface Corte {
  nombre: string;
  monto: number;
  pct: number;
  /** Id de la categoria. null en los grupos que no son una categoria ("Otras", "Sin categoria"). */
  id?: number | null;
  movimientos?: number;
  /** true cuando la fila junta varias entidades (p. ej. pagos a personas) */
  agrupado?: boolean;
  color?: string;
  icono?: string;
  padre?: string;
  clave?: string;
}

export interface Resumen {
  rango: { desde: string; hasta: string; dias: number };
  kpis: Kpis;
  serie_diaria: PuntoDiario[];
  por_categoria: Corte[];
  por_subcategoria: Corte[];
  por_necesidad: Corte[];
  por_cuenta: Corte[];
  por_medio_pago: Corte[];
  top_comercios: Corte[];
  presupuestos: Presupuesto[];
  meta_ahorro: MetaAhorro | null;
  alertas: { tipo: string; texto: string }[];
}

export interface Presupuesto {
  id: number;
  categoria_id: number;
  categoria: string;
  color: string;
  tope: number;
  gastado: number;
  restante: number;
  pct: number;
  /** null cuando aun no hay historial suficiente para predecir nada */
  proyeccion: number | null;
  estado: "en_curso" | "en_riesgo" | "excedido";
}

export interface PresupuestoConfig {
  id: number;
  category_id: number;
  categoria: string;
  color: string;
  amount: number;
  active: boolean;
}

export interface MetaAhorro {
  meta: number;
  ahorro_actual: number;
  ahorro_proyectado: number | null;
  pct: number;
  cumple_proyeccion: boolean;
  faltan: number;
  dias_restantes: number;
  disponible_diario: number;
}

export interface PuntoMensual {
  periodo: string;
  etiqueta: string;
  gasto: number;
  ingreso: number;
  neto: number;
}

export interface PuntoPeriodo extends PuntoMensual {
  movimientos: number;
  /** % de variacion del gasto contra el periodo anterior de la serie. */
  variacion: number | null;
  /** Gasto de cada serie por su `clave`: el id de la categoria, "sin" u "otras". */
  por_categoria: Record<string, number>;
}

export interface NodoCategoria {
  id: number;
  nombre: string;
  monto: number;
  subcategorias: { id: number; nombre: string; monto: number }[];
}

export interface SeriePeriodos {
  agrupar: "mes" | "anio";
  rango: { desde: string; hasta: string };
  periodos: PuntoPeriodo[];
  /** Series del grafico apilado, de mayor a menor gasto en el rango. */
  categorias: Corte[];
  /** Categorias y subcategorias con gasto en el rango: las opciones del filtro. */
  arbol_categorias: NodoCategoria[];
  /** Categoria por la que se filtro la serie; null sin filtro. */
  categoria_id: number | null;
  totales: {
    gasto: number;
    ingreso: number;
    neto: number;
    movimientos: number;
    periodos_con_datos: number;
    promedio: number;
    mayor: PuntoPeriodo | null;
  };
}

export interface EstadoGmail {
  backend: "imap" | "gmail";
  servidor?: string;
  sync_automatica_min: number;
  /** Dias hacia atras que mira la sincronizacion automatica. */
  ventana_automatica: number;
  retencion_dias: number;
  credenciales_presentes: boolean;
  tipo_cliente?: "web" | "installed" | null;
  redirect_uri?: string;
  autorizado: boolean;
  cuenta: string | null;
  ultima_sync: string | null;
  query: string;
  remitentes: string[];
  parsers: { id: string; label: string; banco: string; prioridad: number }[];
}

export interface ResultadoSync {
  correos_leidos: number;
  correos_nuevos: number;
  transacciones_creadas: number;
  por_revisar: number;
  duplicados: number;
  sin_parser: number;
  errores: string[];
  ejecutado_en: string;
}

export interface CorreoArchivado {
  id: number;
  gmail_id: string;
  sender: string;
  subject: string;
  received_at: string;
  snippet: string;
  parse_status: string;
  parser: string | null;
  error: string | null;
  body_text: string | null;
}

export interface PruebaParser {
  reconocido: boolean;
  parser: string | null;
  motivo: string | null;
  resultado: Record<string, unknown> | null;
  texto_normalizado: string | null;
}

const BASE = "/api";

export class ErrorApi extends Error {
  constructor(
    message: string,
    public estado: number,
  ) {
    super(message);
  }
}

async function pedir<T>(ruta: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${ruta}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detalle = res.statusText;
    try {
      const cuerpo = await res.json();
      detalle = cuerpo.detail ?? detalle;
      if (Array.isArray(detalle)) {
        detalle = detalle.map((d: { msg?: string }) => d.msg ?? "").join(", ");
      }
    } catch {
      /* respuesta sin JSON */
    }
    throw new ErrorApi(String(detalle), res.status);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

/** Igual que pedir(), pero deja que el navegador ponga el Content-Type: en un
 *  multipart tiene que incluir el "boundary", y fijarlo a mano lo rompe. */
async function subir<T>(ruta: string, cuerpo: FormData): Promise<T> {
  const res = await fetch(`${BASE}${ruta}`, { method: "POST", body: cuerpo });
  if (!res.ok) {
    let detalle = res.statusText;
    try {
      const j = await res.json();
      detalle = j.detail ?? detalle;
      if (Array.isArray(detalle)) {
        detalle = detalle.map((d: { msg?: string }) => d.msg ?? "").join(", ");
      }
    } catch {
      /* respuesta sin JSON */
    }
    throw new ErrorApi(String(detalle), res.status);
  }
  return res.json() as Promise<T>;
}

function qs(params: Record<string, unknown>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

export const api = {
  salud: () => pedir<{ estado: string }>("/salud"),

  cuentas: () => pedir<Cuenta[]>("/cuentas"),
  crearCuenta: (datos: Partial<Cuenta>) =>
    pedir<Cuenta>("/cuentas", { method: "POST", body: JSON.stringify(datos) }),
  editarCuenta: (id: number, datos: Partial<Cuenta>) =>
    pedir<Cuenta>(`/cuentas/${id}`, { method: "PATCH", body: JSON.stringify(datos) }),

  categorias: () => pedir<Categoria[]>("/categorias"),
  crearCategoria: (datos: Partial<Categoria>) =>
    pedir<Categoria>("/categorias", { method: "POST", body: JSON.stringify(datos) }),

  movimientos: (filtros: Record<string, unknown>) =>
    pedir<PaginaMovimientos>(`/movimientos${qs(filtros)}`),
  crearMovimiento: (datos: Record<string, unknown>) =>
    pedir<Movimiento>("/movimientos", { method: "POST", body: JSON.stringify(datos) }),
  editarMovimiento: (id: number, datos: Record<string, unknown>) =>
    pedir<Movimiento>(`/movimientos/${id}`, { method: "PATCH", body: JSON.stringify(datos) }),
  borrarMovimiento: (id: number) =>
    pedir<void>(`/movimientos/${id}`, { method: "DELETE" }),
  /** Lo revisaste y esta bien: queda protegido y con fecha, sin cambiar nada. */
  marcarRevisado: (id: number) =>
    pedir<Movimiento>(`/movimientos/${id}/revisado`, { method: "POST" }),
  ultimaModificacion: () => pedir<UltimaModificacion | null>("/movimientos/ultima-modificacion"),
  /** `sin_importe_en_soles`: cobros en otra moneda que no se confirmaron porque
   *  falta escribir los soles; siguen en la bandeja. */
  editarLote: (datos: Record<string, unknown>) =>
    pedir<{ afectados: number; sin_importe_en_soles: number }>("/movimientos/lote", {
      method: "POST",
      body: JSON.stringify(datos),
    }),
  colaRevision: () => pedir<Movimiento[]>("/movimientos/revision"),

  reglas: () => pedir<Regla[]>("/reglas"),
  crearRegla: (datos: Partial<Regla>) =>
    pedir<Regla>("/reglas", { method: "POST", body: JSON.stringify(datos) }),
  editarRegla: (id: number, datos: Partial<Regla>) =>
    pedir<Regla>(`/reglas/${id}`, { method: "PATCH", body: JSON.stringify(datos) }),
  borrarRegla: (id: number) => pedir<void>(`/reglas/${id}`, { method: "DELETE" }),

  presupuestos: () => pedir<PresupuestoConfig[]>("/presupuestos"),
  guardarPresupuesto: (datos: { category_id: number; amount: number }) =>
    pedir<PresupuestoConfig>("/presupuestos", { method: "PUT", body: JSON.stringify(datos) }),
  borrarPresupuesto: (id: number) =>
    pedir<void>(`/presupuestos/${id}`, { method: "DELETE" }),
  metaAhorro: () => pedir<{ amount: number }>("/meta-ahorro"),
  guardarMetaAhorro: (amount: number) =>
    pedir<{ amount: number }>("/meta-ahorro", {
      method: "PUT",
      body: JSON.stringify({ amount }),
    }),

  resumen: (desde?: string, hasta?: string) =>
    pedir<Resumen>(`/resumen${qs({ desde, hasta })}`),
  resumenMensual: (meses = 12) => pedir<PuntoMensual[]>(`/resumen/mensual${qs({ meses })}`),
  resumenPeriodos: (
    agrupar: "mes" | "anio",
    desde?: string,
    hasta?: string,
    categoria?: string,
  ) => pedir<SeriePeriodos>(`/resumen/periodos${qs({ agrupar, desde, hasta, categoria })}`),

  estadoGmail: () => pedir<EstadoGmail>("/gmail/estado"),
  /** Devuelve la URL de consentimiento de Google; el navegador va ahi. */
  autorizarGmail: () =>
    pedir<{ url: string; redirect_uri: string }>("/gmail/autorizar", { method: "POST" }),
  probarCorreo: () =>
    pedir<{ ok: boolean; cuenta?: string; mensajes_en_inbox?: number; error?: string }>(
      "/correo/probar",
      { method: "POST" },
    ),
  desconectarGmail: () =>
    pedir<{ autorizado: boolean }>("/gmail/desconectar", { method: "POST" }),
  sincronizar: (dias?: number) =>
    pedir<ResultadoSync>("/gmail/sincronizar", {
      method: "POST",
      // El tope de correos crece con la ventana: con 300 fijos, pedir un ano
      // entero traia los mismos 300 que pedir un mes y el resto se perdia.
      body: JSON.stringify({
        dias: dias ?? null,
        max_correos: Math.min(1000, Math.max(300, Math.round((dias ?? 30) * 4))),
      }),
    }),
  reparsear: () => pedir<ResultadoSync>("/gmail/reparsear", { method: "POST" }),
  correos: (estado?: string, limite = 50) =>
    pedir<CorreoArchivado[]>(`/gmail/correos${qs({ estado, limite })}`),
  correo: (id: number) => pedir<CorreoArchivado>(`/gmail/correos/${id}`),

  probarParser: (datos: { sender: string; subject: string; body: string }) =>
    pedir<PruebaParser>("/parsers/probar", { method: "POST", body: JSON.stringify(datos) }),
  recargarParsers: () =>
    pedir<{ parsers: number; ids: string[] }>("/parsers/recargar", { method: "POST" }),

  seguimiento: () => pedir<Seguimiento>("/seguimiento"),
  crearCorte: (datos: CorteNuevo) =>
    pedir<{ id: number }>("/seguimiento/cortes", { method: "POST", body: JSON.stringify(datos) }),
  editarCorte: (id: number, datos: CorteNuevo) =>
    pedir<{ id: number }>(`/seguimiento/cortes/${id}`, {
      method: "PUT",
      body: JSON.stringify(datos),
    }),
  borrarCorte: (id: number) => pedir<void>(`/seguimiento/cortes/${id}`, { method: "DELETE" }),
  importarSeguimiento: (archivo: File) => {
    const fd = new FormData();
    fd.append("archivo", archivo);
    return subir<ImportacionSeguimiento>("/seguimiento/importar", fd);
  },

  respaldos: () => pedir<EstadoRespaldos>("/respaldos"),
  crearRespaldo: () => pedir<Respaldo>("/respaldos", { method: "POST" }),
  /** "Lo borre a proposito": apaga el aviso de movimientos desaparecidos. */
  aceptarPerdida: () =>
    pedir<EstadoRespaldos>("/respaldos/aceptar-perdida", { method: "POST" }),

  papelera: (limite = 200) => pedir<EntradaPapelera[]>(`/papelera${qs({ limite })}`),
  restaurarPapelera: (id: number) =>
    pedir<{ id: number }>(`/papelera/${id}/restaurar`, { method: "POST" }),

  inversiones: {
    resumen: () => pedir<ResumenInversiones>("/inversiones/resumen"),
    posiciones: () => pedir<PosicionInversion[]>("/inversiones/posiciones"),
    serie: (rango: RangoInversion) => pedir<SerieInversion>(`/inversiones/serie${qs({ rango })}`),
    rentabilidad: () => pedir<RentabilidadInversion>("/inversiones/rentabilidad"),
    dividendos: () => pedir<DividendosInversion>("/inversiones/dividendos"),
    estados: () => pedir<EstadoCuentaImportado[]>("/inversiones/estados"),
    accion: (simbolo: string) =>
      pedir<DetalleAccion>(`/inversiones/acciones/${encodeURIComponent(simbolo)}`),
    precios: (simbolo: string, rango: RangoInversion) =>
      pedir<PreciosAccion>(`/inversiones/acciones/${encodeURIComponent(simbolo)}/precios${qs({ rango })}`),
    sincronizar: () => pedir<SincronizacionInversiones>("/inversiones/sincronizar", { method: "POST" }),
    previsualizar: (archivos: File[]) => {
      const fd = new FormData();
      archivos.forEach((a) => fd.append("archivos", a));
      return subir<ImportacionEstados>("/inversiones/estados/previsualizar", fd);
    },
    importar: (archivos: File[]) => {
      const fd = new FormData();
      archivos.forEach((a) => fd.append("archivos", a));
      return subir<ImportacionEstados>("/inversiones/estados", fd);
    },
  },
};

/* ------------------------------------------------------------------ inversiones */
/* Todo en dolares: la seccion de inversiones no convierte a soles. Los porcentajes
   llegan como fraccion (0.12 = 12 %). */

/** YTD: lo que va del anio. */
export type RangoInversion = "1D" | "1S" | "1M" | "3M" | "6M" | "YTD" | "1A" | "TODO";
export type EstadoOperacionInv = "provisional" | "oficial" | "descartada";

export interface ResumenInversiones {
  configuracion: { precios: boolean; correo: boolean };
  valor: number;
  acciones: number;
  efectivo: number;
  /** Depositos - retiros: lo que pusiste de tu bolsillo y sigue dentro. */
  aportes: number;
  ganancia: number;
  ganancia_pct: number | null;
  dia: { variacion: number | null; variacion_pct: number | null };
  /** Rentabilidad anual que tiene en cuenta cuando entro cada dolar (XIRR). */
  rentabilidad_anual: number | null;
  /** Lo que entro de media cada mes en el ultimo anio, neto de retiros. */
  aporte_mensual: number;
  referencia: { simbolo: string; valor: number | null; rentabilidad_anual: number | null };
  realizada: number;
  no_realizada: number;
  dividendos: { bruto: number; retencion: number; neto: number };
  costos: { operaciones: number; depositos: number; retiros: number; total: number };
  intereses: number;
  ajustes: number;
  /** Momento del precio mas reciente usado (ISO, UTC). */
  precios_al: string | null;
  ultimo_estado: { periodo: string; fin: string; cuadra: boolean; diferencia_efectivo: number } | null;
  provisionales: number;
  avisos: string[];
}

export interface PosicionInversion {
  simbolo: string | null;
  nombre: string | null;
  cantidad: number;
  precio: number | null;
  precio_fuente: "intradia" | "cierre" | "estado_cuenta" | "operacion" | null;
  precio_al: string | null;
  valor: number;
  costo: number;
  costo_promedio: number | null;
  ganancia: number;
  ganancia_pct: number | null;
  peso: number | null;
  variacion_dia: number | null;
  variacion_dia_pct: number | null;
  dividendos_netos: number;
  realizada: number;
}

export interface PuntoValor {
  t: string;
  valor: number;
  aportes: number;
}

/** Ganancia de un periodo. La rentabilidad no cuenta los depositos como ganancia
 *  (ponderada en el tiempo); la referencia es la del S&P 500 en el mismo periodo. */
export interface PeriodoInversion {
  ganancia: number;
  rentabilidad: number;
  referencia: number | null;
}

export interface SerieInversion {
  detalle: "intradia" | "diario";
  puntos: PuntoValor[];
  periodo: PeriodoInversion | null;
}

export interface FilaRentabilidad extends PeriodoInversion {
  /** Lo que entro menos lo que salio en el periodo. */
  aportes: number;
  valor_final: number;
}

export interface RentabilidadInversion {
  /** Simbolo del indice de referencia (VOO). */
  referencia: string;
  por_mes: (FilaRentabilidad & { mes: string })[];
  por_anio: (FilaRentabilidad & { anio: number; en_curso: boolean })[];
  acumulada: { t: string; tuya: number; referencia: number | null }[];
  total: FilaRentabilidad | null;
}

export interface FilaDividendos {
  bruto: number;
  retencion: number;
  neto: number;
}

export interface DividendosInversion {
  por_mes: (FilaDividendos & { mes: string })[];
  por_valor: (FilaDividendos & { simbolo: string; nombre: string | null })[];
  total: FilaDividendos;
}

export interface OperacionInversion {
  id: number;
  tipo: string;
  simbolo: string | null;
  nombre: string | null;
  fecha: string;
  /** Sin correo, la fecha se deduce de la liquidacion. */
  fecha_estimada: boolean;
  /** Hora exacta del correo (ISO, UTC). */
  hora: string | null;
  fecha_liquidacion: string | null;
  cantidad: number | null;
  precio: number | null;
  monto: number;
  retencion: number;
  comision: number | null;
  estado: EstadoOperacionInv;
  fuente: "correo" | "estado_cuenta";
  nota: string | null;
  con_correo: boolean;
}

export interface DetalleAccion {
  simbolo: string;
  nombre: string | null;
  posicion: PosicionInversion | null;
  realizada: number;
  comisiones: number;
  dividendos: FilaDividendos & { por_mes: { mes: string; neto: number }[] };
  operaciones: OperacionInversion[];
}

export interface MarcaOperacion {
  t: string;
  tipo: "compra" | "venta";
  cantidad: number | null;
  precio: number | null;
  monto: number;
  estado: EstadoOperacionInv;
}

export interface PreciosAccion {
  detalle: "intradia" | "diario";
  puntos: { t: string; precio: number }[];
  marcas: MarcaOperacion[];
}

export interface EstadoCuentaImportado {
  periodo: string;
  inicio: string;
  fin: string;
  archivo: string;
  caja: number;
  fdic: number;
  valores: number;
  total: number;
  operaciones: number;
  con_correo: number;
  fechas_estimadas: number;
  correos_no_recogidos: number;
}

export interface ComparacionEstado {
  /** Habia correos de ese mes antes de subir el estado. */
  seguido_por_correo: boolean;
  efectivo: number;
  total: number;
  acciones: { simbolo: string; segun_app: number; segun_estado: number; valor: number }[];
}

export interface DocumentoImportado {
  nombre: string;
  periodo: string | null;
  estado: "nuevo" | "ya_importado" | "error";
  errores: string[];
  operaciones_nuevas: number;
  conciliadas_con_correo: number;
  correos_descartados: number;
  comparacion: ComparacionEstado | null;
}

export interface ImportacionEstados {
  documentos: DocumentoImportado[];
  errores: string[];
  confirmado: boolean;
  importables: number;
}

export interface SincronizacionInversiones {
  correos: { leidos: number; nuevos: number; operaciones: number; completadas: number; repetidos: number };
  precios: { configurado: boolean; cierres: number; intradia: number; error: string | null };
}

/** Un movimiento borrado de verdad. Lo copia un trigger de la base, lo borre quien lo borre. */
export interface EntradaPapelera {
  id: number;
  tx_id: number;
  /** El movimiento ya volvio (se reproceso su correo): restaurarlo lo duplicaria. */
  tx_actual_id: number | null;
  borrado_en: string | null;
  origen: string;
  editado_por_usuario: boolean;
  fecha: string | null;
  monto: number;
  moneda: string | null;
  direccion: Direccion | null;
  comercio: string | null;
  categoria_id: number | null;
  notas: string | null;
}

export interface Respaldo {
  archivo: string;
  fecha: string;
  bytes: number;
  /** null si la copia no se pudo leer */
  movimientos: number | null;
}

export interface EstadoRespaldos {
  activo: boolean;
  cada_dias: number;
  conservar: number;
  carpeta: string;
  ultimo: Respaldo | null;
  proximo: string | null;
  /** Movimientos de la base en uso, para compararla con la ultima copia. */
  movimientos_en_uso: number | null;
  ultimo_intento: { fecha: string; ok: boolean; error: string | null } | null;
  /** Lo que va mal, en castellano. Vacio si todo esta en orden. */
  alertas: string[];
  /** Alguna alerta es de movimientos desaparecidos y se puede dar por buena. */
  perdida_sin_aceptar: boolean;
  respaldos: Respaldo[];
}

/* ------------------------------------------------------------------ seguimiento */
export type Moneda = "PEN" | "USD";

export interface SaldoSeguimiento {
  cuenta: string;
  moneda: Moneda;
  /** Una deuda (la tarjeta de credito) resta del total. */
  es_deuda: boolean;
  /** En la moneda de la cuenta. */
  monto: number;
}

/** La comparacion de un corte con el anterior. */
export interface PeriodoSeguimiento {
  desde: string;
  dias: number;
  /** Total de este corte menos el del anterior. */
  dif_real: number;
  ingresos: number;
  gastos: number;
  /** Ingresos menos gastos registrados en la app entre los dos cortes. */
  registrado: number;
  /** Lo que ganaron o perdieron tus dolares solo por el tipo de cambio. */
  efecto_dolar: number;
  /** dif_real - efecto_dolar - registrado. Cero: registraste todo. */
  descuadre: number;
  sin_ingresos: boolean;
}

export interface CorteSeguimiento {
  id: number;
  fecha: string;
  tipo_cambio: number;
  origen: string;
  notas: string | null;
  total: number;
  saldos: SaldoSeguimiento[];
  /** null en el primer corte: no hay con que comparar. */
  periodo: PeriodoSeguimiento | null;
}

export interface Seguimiento {
  /** Del mas antiguo al mas reciente. */
  cortes: CorteSeguimiento[];
  resumen: {
    cortes: number;
    total_actual: number | null;
    fecha_actual: string | null;
    descuadre_ultimo: number | null;
    descuadre_medio_6: number | null;
  };
  cuentas_sugeridas: { cuenta: string; moneda: Moneda; es_deuda: boolean }[];
  /** null si no hay cortes suficientes en el ultimo año. */
  proyeccion: ProyeccionSeguimiento | null;
}

/** Estimacion simple: la tendencia del ultimo año prolongada desde el ultimo corte. */
export interface ProyeccionSeguimiento {
  /** Primer corte usado para calcular la tendencia. */
  desde: string;
  cortes_usados: number;
  /** Cuanto crece (o baja) tu dinero al mes segun la tendencia. */
  ritmo_mensual: number;
  /** Lo estimado a fin de cada uno de los proximos 12 meses. */
  meses: { fecha: string; total: number }[];
}

export interface CorteNuevo {
  fecha: string;
  tipo_cambio: number | null;
  notas: string | null;
  saldos: SaldoSeguimiento[];
}

export interface ImportacionSeguimiento {
  hoja: string;
  leidos: number;
  creados: number;
  ya_existian: number;
  avisos: string[];
}

