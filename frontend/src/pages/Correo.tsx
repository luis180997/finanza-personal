import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  FlaskConical,
  KeyRound,
  PlugZap,
  RefreshCw,
  RotateCw,
  XCircle,
} from "lucide-react";
import { api } from "../lib/api";
import type { CorreoArchivado, PruebaParser, ResultadoSync } from "../lib/api";
import { fechaHora } from "../lib/format";
import { Encabezado } from "../App";
import {
  AreaTexto,
  Aviso,
  Boton,
  Campo,
  Cargando,
  Entrada,
  Etiqueta,
  Selector,
  Tarjeta,
  Vacio,
} from "../components/ui";

/** Ejemplo precargado: el laboratorio debe funcionar al primer clic. */
const EJEMPLO_LAB = {
  sender: "notificaciones@notificaciones.viabcp.com",
  subject: "Realizaste un consumo",
  body: `Hola Carlos,
Realizaste un consumo con tu Tarjeta de Credito BCP terminada en 4821
por S/ 39.63 en RAPPI*RAPPI PERU LIMA PE el 09/08/2026 a las 13:45.
Numero de operacion: 004512376`,
};

export default function Correo() {
  const qc = useQueryClient();
  const [dias, setDias] = useState(30);
  const [filtroCorreos, setFiltroCorreos] = useState("sin_parser");
  const [ultimaSync, setUltimaSync] = useState<ResultadoSync | null>(null);
  const [lab, setLab] = useState(EJEMPLO_LAB);
  const [resultadoLab, setResultadoLab] = useState<PruebaParser | null>(null);

  // El backend nos devuelve aqui tras el callback de Google: ?gmail=ok|error
  const [resultadoOAuth] = useState<string | null>(() => {
    const p = new URLSearchParams(window.location.search);
    const estadoOauth = p.get("gmail");
    if (!estadoOauth) return null;
    // limpiamos la URL para que un F5 no repita el mensaje
    window.history.replaceState({}, "", window.location.pathname);
    return estadoOauth === "ok" ? "ok" : (p.get("detalle") ?? estadoOauth);
  });

  const { data: estado, isLoading } = useQuery({
    queryKey: ["gmail-estado"],
    queryFn: api.estadoGmail,
  });
  const { data: correos } = useQuery({
    queryKey: ["correos", filtroCorreos],
    queryFn: () => api.correos(filtroCorreos || undefined, 60),
  });

  function refrescar() {
    qc.invalidateQueries({ queryKey: ["gmail-estado"] });
    qc.invalidateQueries({ queryKey: ["correos"] });
    qc.invalidateQueries({ queryKey: ["movimientos"] });
    qc.invalidateQueries({ queryKey: ["resumen"] });
    qc.invalidateQueries({ queryKey: ["revision"] });
  }

  // Paso 1: pedimos la URL de consentimiento y llevamos ahi el navegador.
  // Google nos devolvera a /correo?gmail=ok despues del callback del backend.
  const autorizar = useMutation({
    mutationFn: api.autorizarGmail,
    onSuccess: (r) => {
      window.location.href = r.url;
    },
  });
  const desconectar = useMutation({ mutationFn: api.desconectarGmail, onSuccess: refrescar });
  const probarConexion = useMutation({ mutationFn: api.probarCorreo });
  const sincronizar = useMutation({
    mutationFn: () => api.sincronizar(dias),
    onSuccess: (r) => {
      setUltimaSync(r);
      refrescar();
    },
  });
  const reparsear = useMutation({
    mutationFn: api.reparsear,
    onSuccess: (r) => {
      setUltimaSync(r);
      refrescar();
    },
  });
  const recargar = useMutation({ mutationFn: api.recargarParsers, onSuccess: refrescar });
  const probar = useMutation({
    mutationFn: () => api.probarParser(lab),
    onSuccess: setResultadoLab,
  });

  function cargarEnLab(c: CorreoArchivado) {
    api.correo(c.id).then((completo) => {
      setLab({
        sender: completo.sender,
        subject: completo.subject,
        body: completo.body_text ?? "",
      });
      setResultadoLab(null);
      document.getElementById("laboratorio")?.scrollIntoView({ behavior: "smooth" });
    });
  }

  if (isLoading) return <div className="p-6"><Cargando /></div>;

  return (
    <div className="p-4 md:p-6">
      <Encabezado
        titulo="Correo"
        descripcion="La app lee tu Gmail en solo lectura y convierte las notificaciones de BCP, Yape y BBVA en movimientos. Nunca envia ni borra correo."
      />

      <div className="grid gap-4 lg:grid-cols-3">
        <Tarjeta titulo="Conexion" className="lg:col-span-1">
          <ul className="space-y-2 text-sm">
            <Estado ok={estado?.autorizado ?? false}>
              {estado?.autorizado
                ? `Conectado: ${estado.cuenta}`
                : "Sin conectar — la app aún no lee tu correo"}
            </Estado>
            {estado?.backend === "imap" && (
              <li className="text-xs text-[var(--tinta-3)]">
                IMAP · {estado.servidor}
              </li>
            )}
            <li className="text-xs text-[var(--tinta-3)]">
              {estado?.sync_automatica_min
                ? `Lectura automática cada ${estado.sync_automatica_min} min`
                : "Lectura automática desactivada"}
            </li>
            <li className="text-xs text-[var(--tinta-3)]">
              Ultima sincronizacion:{" "}
              {estado?.ultima_sync ? fechaHora(estado.ultima_sync) : "nunca"}
            </li>
          </ul>

          {/* ------------------------------------------ modo IMAP (por defecto) */}
          {estado?.backend === "imap" && !estado.autorizado && (
            <div className="mt-3 space-y-3">
              <Aviso tono="aviso">
                Faltan las credenciales. Son <b>dos líneas en el archivo .env</b> y se
                consiguen en dos minutos.
              </Aviso>
              <ol className="space-y-2 text-xs text-[var(--tinta-2)]">
                <li>
                  <b>1.</b> Activa la verificación en 2 pasos en{" "}
                  <a
                    href="https://myaccount.google.com/security"
                    target="_blank"
                    rel="noreferrer"
                    style={{ color: "var(--serie-1)" }}
                  >
                    tu cuenta de Google
                  </a>
                  . Sin ella el paso 2 no existe.
                </li>
                <li>
                  <b>2.</b> Crea una contraseña de aplicación en{" "}
                  <a
                    href="https://myaccount.google.com/apppasswords"
                    target="_blank"
                    rel="noreferrer"
                    style={{ color: "var(--serie-1)" }}
                  >
                    myaccount.google.com/apppasswords
                  </a>{" "}
                  y copia las 16 letras.
                </li>
                <li>
                  <b>3.</b> En el archivo <code>.env</code> de la carpeta del proyecto:
                  <pre
                    className="mt-1 overflow-x-auto rounded-md p-2 font-mono text-[11px]"
                    style={{ background: "var(--superficie-2)" }}
                  >
{`IMAP_USER=tucorreo@gmail.com
IMAP_PASSWORD=las16letras`}
                  </pre>
                </li>
                <li>
                  <b>4.</b> Reinicia:{" "}
                  <code className="text-[11px]">docker compose up -d</code>
                </li>
              </ol>
            </div>
          )}

          {estado?.backend === "imap" && (
            <div className="mt-3">
              <Boton
                onClick={() => probarConexion.mutate()}
                disabled={probarConexion.isPending}
              >
                <PlugZap size={15} />
                {probarConexion.isPending ? "Probando…" : "Probar conexión"}
              </Boton>
              {probarConexion.data && (
                <p
                  className="mt-2 text-xs"
                  style={{
                    color: probarConexion.data.ok
                      ? "var(--texto-bien)"
                      : "var(--texto-malo)",
                  }}
                >
                  {probarConexion.data.ok
                    ? `Conexión correcta con ${probarConexion.data.cuenta} · ${probarConexion.data.mensajes_en_inbox} correos en la bandeja`
                    : probarConexion.data.error}
                </p>
              )}
            </div>
          )}

          {estado?.backend === "gmail" && !estado.credenciales_presentes && (
            <div className="mt-3">
              <Aviso tono="aviso">
                Falta el archivo de credenciales. En Google Cloud Console: habilita la
                Gmail API, crea un ID de cliente OAuth de tipo <b>Aplicacion web</b>,
                registra como URI de redireccion{" "}
                <code className="break-all">{estado?.redirect_uri}</code> y guarda el
                JSON en la carpeta <code>secrets/</code> del proyecto.
              </Aviso>
            </div>
          )}

          {estado?.backend === "gmail" && estado.tipo_cliente === "installed" && (
            <div className="mt-3">
              <Aviso tono="aviso">
                El JSON que subiste es de tipo <b>Aplicacion de escritorio</b>. Este flujo
                necesita uno de tipo <b>Aplicacion web</b> con el URI{" "}
                <code className="break-all">{estado.redirect_uri}</code> registrado.
              </Aviso>
            </div>
          )}

          {resultadoOAuth === "ok" && (
            <p className="mt-3 text-sm" style={{ color: "var(--texto-bien)" }}>
              Cuenta conectada. Ya puedes sincronizar.
            </p>
          )}
          {resultadoOAuth && resultadoOAuth !== "ok" && (
            <p className="mt-3 text-sm" style={{ color: "var(--texto-malo)" }}>
              Google devolvio un error: {resultadoOAuth}
            </p>
          )}

          <div className={`mt-4 flex flex-wrap gap-2 ${estado?.backend === "imap" ? "hidden" : ""}`}>
            <Boton
              variante={estado?.autorizado ? "secundario" : "primario"}
              onClick={() => autorizar.mutate()}
              disabled={!estado?.credenciales_presentes || autorizar.isPending}
            >
              <KeyRound size={15} />
              {autorizar.isPending
                ? "Abriendo Google…"
                : estado?.autorizado
                  ? "Reconectar"
                  : "Conectar Gmail"}
            </Boton>
            {estado?.autorizado && (
              <Boton variante="peligro" onClick={() => desconectar.mutate()}>
                Desconectar
              </Boton>
            )}
          </div>
          {estado?.backend === "gmail" && (
            <p className="mt-2 text-xs text-[var(--tinta-3)]">
              Se abre la pantalla de consentimiento de Google en tu navegador. El permiso
              pedido es solo lectura de Gmail.
            </p>
          )}
          {autorizar.isError && (
            <p className="mt-2 text-xs" style={{ color: "var(--texto-malo)" }}>
              {(autorizar.error as Error).message}
            </p>
          )}

          <div className="mt-4 border-t pt-4" style={{ borderColor: "var(--borde)" }}>
            <Campo etiqueta="Ventana a sincronizar">
              <Selector value={dias} onChange={(e) => setDias(Number(e.target.value))}>
                <option value={7}>Ultimos 7 dias</option>
                <option value={30}>Ultimos 30 dias</option>
                <option value={90}>Ultimos 90 dias</option>
                <option value={180}>Ultimos 6 meses</option>
                <option value={365}>Ultimo año</option>
              </Selector>
            </Campo>
            <p className="mt-1.5 text-xs text-[var(--tinta-3)]">
              La sincronizacion automatica mira solo los ultimos{" "}
              {estado?.ventana_automatica ?? 30} dias, que es de sobra para el dia a dia.
              Las ventanas largas son para la primera carga: tardan mas y traen todo el
              historial de una vez. Repetirlas no duplica nada.
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <Boton
                variante="primario"
                onClick={() => sincronizar.mutate()}
                disabled={!estado?.autorizado || sincronizar.isPending}
              >
                <RefreshCw size={15} className={sincronizar.isPending ? "animate-spin" : ""} />
                {sincronizar.isPending ? "Sincronizando…" : "Sincronizar"}
              </Boton>
              <Boton onClick={() => reparsear.mutate()} disabled={reparsear.isPending}>
                <RotateCw size={15} /> Re-parsear pendientes
              </Boton>
            </div>
            <p className="mt-2 text-xs text-[var(--tinta-3)]">
              Re-parsear vuelve a intentar los correos ya descargados. Uselo despues de
              editar <code>patterns.yaml</code>; no vuelve a bajar nada de Gmail.
            </p>
          </div>
        </Tarjeta>

        <div className="space-y-4 lg:col-span-2">
          {ultimaSync && (
            <Tarjeta titulo="Resultado de la ultima ejecucion">
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
                <Dato n={ultimaSync.correos_leidos} t="leidos" />
                <Dato n={ultimaSync.correos_nuevos} t="nuevos" />
                <Dato n={ultimaSync.transacciones_creadas} t="movimientos" acento="var(--bien)" />
                <Dato n={ultimaSync.por_revisar} t="por revisar" acento="var(--aviso)" />
                <Dato n={ultimaSync.duplicados} t="duplicados" />
                <Dato n={ultimaSync.sin_parser} t="sin parser" acento="var(--critico)" />
              </div>
              {ultimaSync.errores.length > 0 && (
                <ul className="mt-3 space-y-1">
                  {ultimaSync.errores.map((e, i) => (
                    <li key={i} className="text-xs" style={{ color: "var(--texto-malo)" }}>
                      {e}
                    </li>
                  ))}
                </ul>
              )}
            </Tarjeta>
          )}

          <Tarjeta
            titulo="Correos archivados"
            subtitulo="Los que ningun parser reconocio son la lista de trabajo para calibrar los patrones"
            acciones={
              <Selector
                className="w-44"
                value={filtroCorreos}
                onChange={(e) => setFiltroCorreos(e.target.value)}
              >
                <option value="sin_parser">Sin parser</option>
                <option value="parseado">Parseados</option>
                <option value="">Todos</option>
              </Selector>
            }
          >
            {!correos?.length ? (
              <Vacio
                titulo="Nada por aqui"
                detalle="Sincroniza para traer correos, o cambia el filtro."
              />
            ) : (
              <ul className="divide-y" style={{ borderColor: "var(--borde)" }}>
                {correos.map((c) => (
                  <li key={c.id} className="flex items-start gap-3 py-2.5">
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium">{c.subject || "(sin asunto)"}</div>
                      <div className="truncate text-xs text-[var(--tinta-3)]">{c.sender}</div>
                      <div className="mt-1 flex flex-wrap items-center gap-1.5">
                        <span className="text-xs text-[var(--tinta-3)]">
                          {fechaHora(c.received_at)}
                        </span>
                        {c.parser && <Etiqueta color="var(--bien)">{c.parser}</Etiqueta>}
                        {c.error && (
                          <span className="text-xs text-[var(--tinta-3)]" title={c.error}>
                            {c.error.slice(0, 70)}
                          </span>
                        )}
                      </div>
                    </div>
                    <Boton variante="fantasma" onClick={() => cargarEnLab(c)}>
                      <FlaskConical size={14} /> Probar
                    </Boton>
                  </li>
                ))}
              </ul>
            )}
          </Tarjeta>
        </div>
      </div>

      {/* ------------------------------------------------------- laboratorio */}
      <div id="laboratorio" className="mt-4 grid gap-4 lg:grid-cols-2">
        <Tarjeta
          titulo="Laboratorio de parsers"
          subtitulo="Pega un correo real y mira exactamente que extraen los patrones"
          acciones={
            <Boton variante="fantasma" onClick={() => recargar.mutate()}>
              <RotateCw size={14} /> Recargar patterns.yaml
            </Boton>
          }
        >
          <div className="space-y-3">
            <Campo etiqueta="Remitente">
              <Entrada
                placeholder="notificaciones@notificaciones.viabcp.com"
                value={lab.sender}
                onChange={(e) => setLab({ ...lab, sender: e.target.value })}
              />
            </Campo>
            <Campo etiqueta="Asunto">
              <Entrada
                placeholder="Realizaste un consumo"
                value={lab.subject}
                onChange={(e) => setLab({ ...lab, subject: e.target.value })}
              />
            </Campo>
            <Campo etiqueta="Cuerpo del correo">
              <AreaTexto
                rows={10}
                className="font-mono text-xs"
                placeholder="Pega aqui el texto del correo…"
                value={lab.body}
                onChange={(e) => setLab({ ...lab, body: e.target.value })}
              />
            </Campo>
            <Boton variante="primario" onClick={() => probar.mutate()} disabled={!lab.body}>
              <FlaskConical size={15} /> Probar patrones
            </Boton>
          </div>
        </Tarjeta>

        <Tarjeta titulo="Resultado">
          {!resultadoLab ? (
            <Vacio
              titulo="Sin ejecutar"
              detalle="Cuando un correo real no se reconozca, pegalo aqui y ajusta patterns.yaml hasta que salga verde."
            />
          ) : resultadoLab.reconocido ? (
            <div className="space-y-3">
              <div className="flex items-center gap-2 text-sm" style={{ color: "var(--texto-bien)" }}>
                <CheckCircle2 size={16} />
                Reconocido por <b>{resultadoLab.parser}</b>
              </div>
              {resultadoLab.motivo && (
                <p className="text-xs text-[var(--tinta-3)]">{resultadoLab.motivo}</p>
              )}
              <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
                {Object.entries(resultadoLab.resultado ?? {}).map(([k, v]) => (
                  <div key={k} className="contents">
                    <dt className="text-[var(--tinta-3)]">{k.replace(/_/g, " ")}</dt>
                    <dd className="tabular truncate font-medium">{String(v ?? "—")}</dd>
                  </div>
                ))}
              </dl>
            </div>
          ) : (
            <div className="space-y-3">
              <div className="flex items-center gap-2 text-sm" style={{ color: "var(--texto-malo)" }}>
                <XCircle size={16} /> No reconocido
              </div>
              <p className="text-sm text-[var(--tinta-2)]">{resultadoLab.motivo}</p>
              <details>
                <summary className="cursor-pointer text-xs text-[var(--tinta-3)]">
                  Ver el texto normalizado que ven los patrones
                </summary>
                <pre className="mt-2 max-h-64 overflow-auto rounded-lg p-3 font-mono text-xs whitespace-pre-wrap"
                     style={{ background: "var(--superficie-2)" }}>
                  {resultadoLab.texto_normalizado}
                </pre>
              </details>
            </div>
          )}
        </Tarjeta>
      </div>

      {estado && (
        <Tarjeta titulo="Parsers activos" className="mt-4">
          <div className="flex flex-wrap gap-2">
            {estado.parsers.map((p) => (
              <Etiqueta key={p.id} titulo={`prioridad ${p.prioridad}`}>
                {p.label}
              </Etiqueta>
            ))}
          </div>
          <p className="mt-3 font-mono text-xs break-all text-[var(--tinta-3)]">
            Query de Gmail: {estado.query}
          </p>
        </Tarjeta>
      )}
    </div>
  );
}

function Estado({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return (
    <li className="flex items-center gap-2">
      {ok ? (
        <CheckCircle2 size={15} style={{ color: "var(--bien)" }} />
      ) : (
        <XCircle size={15} style={{ color: "var(--critico)" }} />
      )}
      <span className={ok ? "" : "text-[var(--tinta-2)]"}>{children}</span>
    </li>
  );
}

function Dato({ n, t, acento }: { n: number; t: string; acento?: string }) {
  return (
    <div>
      <div className="tabular text-xl font-semibold" style={{ color: acento }}>
        {n}
      </div>
      <div className="text-xs text-[var(--tinta-3)]">{t}</div>
    </div>
  );
}
