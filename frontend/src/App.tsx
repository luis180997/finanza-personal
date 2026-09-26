import { useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Inbox,
  LayoutDashboard,
  Mail,
  Moon,
  PlusCircle,
  PiggyBank,
  ReceiptText,
  Scale,
  Upload,
  Settings2,
  SlidersHorizontal,
  TrendingUp,
  Sun,
  Wallet,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { api } from "./lib/api";
import type { ConfigApp } from "./lib/api";
import { AvisoRespaldos } from "./components/respaldos";
import { Tarjeta, Vacio } from "./components/ui";
import Panel from "./pages/Panel";
import Tendencia from "./pages/Tendencia";
import Seguimiento from "./pages/Seguimiento";
import Movimientos from "./pages/Movimientos";
import Registrar from "./pages/Registrar";
import Revision from "./pages/Revision";
import Presupuesto from "./pages/Presupuesto";
import Importar from "./pages/Importar";
import Reglas from "./pages/Reglas";
import Correo from "./pages/Correo";
import Ajustes from "./pages/Ajustes";

interface EntradaNav {
  a: string;
  icono: LucideIcon;
  texto: string;
  contador?: boolean;
  /** La entrada solo aparece si el servidor tiene encendido este interruptor. */
  requiere?: keyof ConfigApp;
}

const NAV: EntradaNav[] = [
  { a: "/panel", icono: LayoutDashboard, texto: "Panel" },
  { a: "/registrar", icono: PlusCircle, texto: "Registrar gasto" },
  { a: "/movimientos", icono: ReceiptText, texto: "Movimientos" },
  { a: "/tendencia", icono: TrendingUp, texto: "Tendencia" },
  // Las 5 primeras forman la barra inferior del movil: "Por revisar" (con su
  // contador) tiene que seguir entre ellas.
  { a: "/revision", icono: Inbox, texto: "Por revisar", contador: true },
  { a: "/seguimiento", icono: Scale, texto: "Seguimiento" },
  { a: "/presupuesto", icono: PiggyBank, texto: "Presupuesto" },
  { a: "/correo", icono: Mail, texto: "Correo" },
  { a: "/importar", icono: Upload, texto: "Importar Excel", requiere: "importar_excel" },
  { a: "/reglas", icono: SlidersHorizontal, texto: "Reglas" },
  { a: "/ajustes", icono: Settings2, texto: "Cuentas y copias" },
];

function useTema() {
  const [tema, setTema] = useState<"claro" | "oscuro" | "sistema">(
    () => (localStorage.getItem("tema") as "claro" | "oscuro" | "sistema") ?? "sistema",
  );
  useEffect(() => {
    const raiz = document.documentElement;
    if (tema === "sistema") raiz.removeAttribute("data-theme");
    else raiz.setAttribute("data-theme", tema === "oscuro" ? "dark" : "light");
    localStorage.setItem("tema", tema);
  }, [tema]);
  return { tema, setTema };
}

export default function App() {
  const { tema, setTema } = useTema();

  const { data: pendientes } = useQuery({
    queryKey: ["revision"],
    queryFn: api.colaRevision,
    refetchInterval: 60_000,
  });
  const numPendientes = pendientes?.length ?? 0;

  // Los interruptores los decide el servidor (variables de entorno): asi el menu
  // y la API nunca discrepan, y no hace falta recompilar la interfaz.
  const { data: config } = useQuery({
    queryKey: ["config"],
    queryFn: api.config,
    staleTime: Infinity,
  });
  const nav = NAV.filter((n) => !n.requiere || config?.[n.requiere]);

  return (
    <div className="flex min-h-screen">
      <aside
        className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r p-4 md:flex"
        style={{ borderColor: "var(--borde)", background: "var(--superficie)" }}
      >
        <div className="mb-6 flex items-center gap-2 px-2">
          <Wallet size={20} style={{ color: "var(--serie-1)" }} />
          <div>
            <div className="text-sm font-semibold">Finanzas</div>
            <div className="text-xs text-[var(--tinta-3)]">personales</div>
          </div>
        </div>

        <nav className="flex-1 space-y-1">
          {nav.map(({ a, icono: Icono, texto, contador }) => (
            <NavLink
              key={a}
              to={a}
              className={({ isActive }) =>
                `flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors ${
                  isActive
                    ? "font-medium text-[var(--tinta)]"
                    : "text-[var(--tinta-2)] hover:bg-[var(--superficie-2)]"
                }`
              }
              style={({ isActive }) =>
                isActive ? { background: "var(--superficie-2)" } : undefined
              }
            >
              <Icono size={16} />
              <span className="flex-1">{texto}</span>
              {contador && numPendientes > 0 && (
                <span
                  className="tabular rounded-full px-1.5 py-0.5 text-[10px] font-semibold text-white"
                  style={{ background: "var(--critico)" }}
                >
                  {numPendientes}
                </span>
              )}
            </NavLink>
          ))}
        </nav>

        <button
          onClick={() => setTema(tema === "oscuro" ? "claro" : "oscuro")}
          className="mt-4 flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-[var(--tinta-2)] hover:bg-[var(--superficie-2)]"
        >
          {tema === "oscuro" ? <Sun size={16} /> : <Moon size={16} />}
          {tema === "oscuro" ? "Tema claro" : "Tema oscuro"}
        </button>
      </aside>

      {/* Navegacion inferior en movil */}
      <nav
        className="fixed inset-x-0 bottom-0 z-20 flex justify-around border-t py-1 md:hidden"
        style={{ borderColor: "var(--borde)", background: "var(--superficie)" }}
      >
        {nav.slice(0, 5).map(({ a, icono: Icono, texto, contador }) => (
          <NavLink
            key={a}
            to={a}
            className={({ isActive }) =>
              `relative flex flex-col items-center gap-0.5 rounded-lg px-3 py-1.5 text-[10px] ${
                isActive ? "text-[var(--tinta)]" : "text-[var(--tinta-3)]"
              }`
            }
          >
            <Icono size={18} />
            {texto.split(" ")[0]}
            {contador && numPendientes > 0 && (
              <span
                className="absolute top-0 right-1 h-2 w-2 rounded-full"
                style={{ background: "var(--critico)" }}
              />
            )}
          </NavLink>
        ))}
      </nav>

      <main className="min-w-0 flex-1 pb-20 md:pb-0">
        <AvisoRespaldos />
        <Routes>
          <Route path="/" element={<Navigate to="/panel" replace />} />
          <Route path="/panel" element={<Panel />} />
          <Route path="/tendencia" element={<Tendencia />} />
          <Route path="/seguimiento" element={<Seguimiento />} />
          <Route path="/registrar" element={<Registrar />} />
          <Route path="/movimientos" element={<Movimientos />} />
          <Route path="/revision" element={<Revision />} />
          <Route path="/correo" element={<Correo />} />
          <Route path="/presupuesto" element={<Presupuesto />} />
          <Route
            path="/importar"
            element={
              !config ? null : config.importar_excel ? <Importar /> : <ImportarDeshabilitado />
            }
          />
          <Route path="/reglas" element={<Reglas />} />
          <Route path="/ajustes" element={<Ajustes />} />
          {/* Una ruta que ya no existe (un marcador a /comparativa, retirada en
              set. 2026) llevaba a una pantalla en blanco sin explicacion. */}
          <Route path="*" element={<Navigate to="/panel" replace />} />
        </Routes>
      </main>
    </div>
  );
}

/** Quien llegue a /importar con un enlace guardado ve por que no esta, no un 404. */
function ImportarDeshabilitado() {
  return (
    <div className="p-4 md:p-6">
      <Encabezado titulo="Importar Excel" />
      <Tarjeta>
        <Vacio
          titulo="La importación de Excel está deshabilitada"
          detalle="El Excel ya está importado hasta el 31/08/2026 y desde setiembre los gastos llegan por correo: otro archivo con filas nuevas los duplicaría. Para usarla, pon IMPORTAR_EXCEL_HABILITADO=true en el .env y reinicia la aplicación."
        />
      </Tarjeta>
    </div>
  );
}

export function Encabezado({
  titulo,
  descripcion,
  acciones,
}: {
  titulo: string;
  descripcion?: string;
  acciones?: React.ReactNode;
}) {
  return (
    <header className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{titulo}</h1>
        {descripcion && (
          <p className="mt-1 max-w-2xl text-sm text-[var(--tinta-3)]">{descripcion}</p>
        )}
      </div>
      {acciones && <div className="flex flex-wrap items-center gap-2">{acciones}</div>}
    </header>
  );
}
