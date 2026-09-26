# =============================================================================
#  Frontend: se compila con Node y se sirve con nginx
# =============================================================================
#  Dos etapas. Node solo existe durante la compilacion; la imagen final es
#  nginx + archivos estaticos (~75 MB). Nada de Node en produccion.
#
#  nginx tambien hace de unica puerta de entrada: sirve la SPA y reenvia /api al
#  backend. Asi el navegador ve un solo origen y no hay CORS que configurar.
# =============================================================================
FROM node:22-alpine AS build

WORKDIR /app

# npm ci usa el lockfile: build reproducible. Esta capa se cachea.
COPY package.json package-lock.json ./
RUN npm ci

COPY tsconfig.json vite.config.ts index.html ./
COPY src ./src
RUN npm run build


FROM nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
