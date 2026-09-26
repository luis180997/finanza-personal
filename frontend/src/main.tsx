import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./index.css";

const cliente: QueryClient = new QueryClient({
  // Cualquier escritura (registrar, recategorizar, importar, sincronizar...) deja
  // viejos los resumenes de TODAS las pantallas. Invalidar a mano en cada
  // mutacion fallaba por omision: Tendencia no se enteraba de ningun cambio.
  // Invalidar todo solo vuelve a pedir lo que esta en pantalla; lo demas queda
  // marcado como viejo y se recarga al volver a verlo.
  mutationCache: new MutationCache({
    onSettled: () => {
      void cliente.invalidateQueries();
    },
  }),
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={cliente}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
