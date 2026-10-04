# Finanzas personales

Lee las notificaciones de **BCP, Yape y BBVA** desde tu Gmail, las convierte en
movimientos clasificados, y te da el resumen de en qué se te va el dinero. Los gastos
en efectivo se registran a mano en una pantalla pensada para eso.

Sustituye el Excel manual: una fila por movimiento en vez de una fila por día, con
categorías de dos niveles y un campo que mide lo que antes anotabas como
*"gasto innecesario"*.

- **Backend**: Python · FastAPI · SQLModel · SQLite
- **Frontend**: React 19 · Vite · TypeScript · Tailwind 4 · Recharts
- **Correo**: IMAP con contraseña de aplicación (o Gmail API OAuth). Lee cada 15 min, solo
- **Despliegue**: Docker Compose · un solo comando · nginx como única puerta de entrada
- **Arquitectura**: hexagonal por módulos · integridad de datos garantizada por la propia base · migraciones con Alembic · 191 pruebas

> **Contexto completo del proyecto y decisiones de diseño:** [`docs/CONTEXTO.md`](docs/CONTEXTO.md)
> **Cómo ajustar la lectura de correos:** [`docs/CALIBRAR_PARSERS.md`](docs/CALIBRAR_PARSERS.md)

---

## Arquitectura

El backend está partido en módulos de negocio (`movimientos`, `clasificacion`, `correo`,
`excel`, `analitica`, `seguimiento`), y todos tienen las mismas capas:

```
app/<modulo>/
├── dominio/       reglas de negocio puras. No importa FastAPI ni SQL
├── aplicacion/    casos de uso + puertos (lo que necesita de fuera, como interfaz)
└── adaptadores/   entrada (API HTTP) · salida (SQLite, IMAP, Gmail, Excel) · fabrica.py
```

El dominio no conoce a nadie; los adaptadores conocen a todos. Lo común vive en
`compartido/` (dinero, tipos, normalización de comercios, el corte histórico) y lo
técnico en `plataforma/` (configuración, base de datos, migraciones con Alembic, respaldos).

### Integridad de los datos

Las reglas completas están en `AGENTS.md`. Lo esencial:

- **Lo que el usuario decide no se pisa.** Un movimiento registrado, editado o revisado
  a mano queda protegido (`locked_by_user`): ninguna sincronización, regla ni migración
  lo vuelve a clasificar.
- **La base de datos impide borrarlo**, no solo el código: un trigger rechaza el
  `DELETE` de un movimiento protegido, y otro copia todo lo borrado a una papelera que
  se restaura desde la interfaz.
- **Una sola fuente de verdad por periodo.** Hasta el 31/08/2026 manda el Excel
  histórico; desde el 01/09/2026, los correos y lo registrado a mano. La fecha vive en
  un único sitio (`backend/app/compartido/corte.py`), así nada se cuenta dos veces.
- **El dinero se guarda en céntimos enteros**, nunca en coma flotante.
- **Las pruebas nunca tocan la base real**: `conftest.py` las aísla en una temporal.

---

## Puesta en marcha con Docker (recomendado)

Requisito único: Docker Desktop (o Docker Engine + Compose v2).

```bash
docker compose up -d --build
```

Y ya está: **http://localhost:8080**

Eso levanta dos contenedores:

| Servicio | Qué hace |
|---|---|
| `web` | nginx. Sirve la interfaz y reenvía `/api` al backend. Es la única puerta de entrada |
| `api` | FastAPI. **No publica puerto al exterior**: solo se llega a través de nginx |

Comandos habituales:

```bash
docker compose logs -f          # ver qué está pasando
docker compose ps               # estado y salud de los contenedores
docker compose down             # parar (los datos se conservan)
docker compose up -d --build    # aplicar cambios de código
```

Documentación de la API: http://localhost:8080/api/docs

### Datos para explorar

```bash
docker compose exec api python scripts/datos_demo.py --dias 120
```

Y para borrarlos: `docker compose exec api python scripts/datos_demo.py --borrar`

### Dónde viven los datos

En la carpeta **`./data/`** del propio proyecto, montada dentro del contenedor
(*bind mount*). Está en `.gitignore`, así que nunca entra al repositorio.

> Antes vivían en un volumen de Docker llamado `finanzas-datos`. Si vienes de esa
> versión, ese volumen **sigue existiendo con una copia vieja** y ya no se usa.
> Para recuperarla:
> ```bash
> docker run --rm -v finanzas-datos:/viejo -v "${PWD}/data:/nuevo" alpine cp /viejo/finanzas.db /nuevo/
> ```
> Y cuando ya no la necesites: `docker volume rm finanzas-datos`.

#### Inspeccionar y consultar la base de datos

1. **Extraer el archivo para verlo con un programa visual (DBeaver o DB Browser for SQLite):**
   ```bash
   docker compose cp api:/app/data/finanzas.db ./finanzas.db
   ```
2. **Consultar directamente por terminal:**
   ```bash
   docker compose exec api sqlite3 /app/data/finanzas.db "SELECT id, merchant, amount_cents/100.0, necessity FROM transaction ORDER BY id DESC LIMIT 10;"
   ```
3. **Consola interactiva de SQLite:**
   ```bash
   docker compose exec -it api sqlite3 /app/data/finanzas.db
   ```

#### Respaldo y restauración

Los datos son **un solo archivo**, `./data/finanzas.db`, y la app lo respalda sola en
**`./data/respaldos/`**. El estado se ve en la pantalla **Cuentas y copias**, y si algo va
mal (una copia que falla, una que no se hace, movimientos que desaparecen) sale un aviso
arriba en todas las pantallas.

| Variable | Defecto | Qué hace |
|---|---|---|
| `RESPALDO_CADA_DIAS` | `7` | Días mínimos entre copias automáticas. `0` las desactiva (la copia previa a cambios de la base se hace igual) |
| `RESPALDO_CONSERVAR` | `8` | Cuántas de las más recientes se guardan siempre. `0` = no borrar ninguna |
| `RESPALDO_DIR` | vacío | Otra carpeta (vacío = `data/respaldos`) |

**Cuándo se copia**

- **Cada N días**, mirando la *fecha* de la última copia y no una hora fija: si el equipo
  estuvo apagado dos semanas, la copia sale en cuanto vuelve a encenderse.
- **Antes de que el arranque cambie la base** (versiones de esquema pendientes,
  migraciones de datos). Si esa copia falla, la app no arranca.
- **Antes de importar un Excel, de deshacer una importación** y de `scripts/datos_demo.py`.
- **A mano:** botón *Hacer una copia ahora*, o `curl -X POST http://localhost:8080/api/respaldos`.

**Qué se conserva**

- Las `RESPALDO_CONSERVAR` más recientes **y** la última de cada uno de los últimos 7 días,
  8 semanas y 12 meses con copia. Un día de muchas copias manuales solo reemplaza copias
  de ese mismo día.
- **Una copia con claramente más movimientos que la última no se borra nunca sola** (10 o
  más, y al menos el 1 %). Si la base se vacía por error, la copia buena sobrevive a
  todas las que vengan detrás. Esas copias se borran a mano.
- Solo se tocan los archivos `finanzas_AAAAMMDDTHHMMSSZ.db`: lo que dejes a mano en la
  carpeta no se borra nunca.

La copia es segura con la app en marcha: usa la API de backup de SQLite, escribe a un
temporal, lo verifica con `PRAGMA integrity_check` y solo entonces le pone nombre.

> Las copias están en el mismo disco que la base. Para tenerlas también fuera del equipo,
> el proyecto va dentro de OneDrive.

**Restaurar** — siempre con la app parada; si no, puede escribir encima de la copia:

1. Para la app: `docker compose stop api` (o cierra el `uvicorn`).
2. Aparta la base actual, por si quieres volver a ella.
3. Si existe `data/finanzas.db-journal`, apártalo también: SQLite lo aplicaría sobre la
   copia restaurada y la estropearía.
4. Copia el respaldo elegido como `data/finanzas.db` (cambia el nombre del ejemplo).
5. Arranca. Si la copia es anterior a alguna migración, se vuelve a aplicar sola, con su
   propia copia previa.

```bash
docker compose stop api
mv data/finanzas.db data/finanzas_antes_de_restaurar.db
if [ -f data/finanzas.db-journal ]; then mv data/finanzas.db-journal data/finanzas_antes_de_restaurar.db-journal; fi
cp data/respaldos/finanzas_20260913T075641Z.db data/finanzas.db
docker compose start api
```

Borrar **todo** (sin vuelta atrás): `docker compose down` y borra la carpeta `data/`, que
incluye también `data/respaldos/`.

---

### Concepto de Base de Datos: SQLite en modo DELETE (journal clásico)

El proyecto usa **SQLite** con **`PRAGMA journal_mode=DELETE`** en
[`backend/app/plataforma/db.py`](backend/app/plataforma/db.py), y los datos viven en un
*bind mount* a `./data/`. Las dos decisiones van juntas y en ese orden.

#### Por qué NO se usa WAL

WAL (*Write-Ahead Logging*) es mejor sobre el papel: los lectores no bloquean a
los escritores, así que el panel se puede consultar mientras el sincronizador
guarda movimientos. Pero **WAL necesita memoria compartida y bloqueos de archivo
reales**, y un *bind mount* de Docker Desktop a una carpeta de Windows no los
garantiza. Ahí WAL no es "más lento": puede **corromper la base**.

Como se prefirió tener el archivo a mano en `./data/` (para copiarlo, abrirlo con
DB Browser o respaldarlo sin comandos raros), el modo journal tiene que ser
`DELETE`. Es el compromiso correcto para un solo usuario.

#### Lo que se paga

Con `DELETE`, un escritor bloquea a los lectores mientras dura la transacción.
En esta app son milisegundos, y el sincronizador corre cada 15 minutos. Para
absorberlo está `timeout=30.0` en la conexión: si coincide una lectura con una
escritura, SQLite reintenta solo en vez de fallar.

#### Si algún día lo mueves a Linux o WSL2

Sobre ext4 los bloqueos sí funcionan, y ahí **sí conviene volver a WAL**: cambia
esa línea de `db.py`. Sobre Windows, no.

### Cambiar la estructura de la base (Alembic)

Las tablas y columnas se versionan con [Alembic](https://alembic.sqlalchemy.org/): cada
cambio es un script numerado en `backend/app/plataforma/migraciones_esquema/versions/`,
la base guarda en qué versión está (tabla `alembic_version`) y **al arrancar se aplican
las que falten**, en orden, todas o ninguna.

1. Cambia la entidad (por ejemplo, `backend/app/movimientos/dominio/entidades.py`).
2. Genera la versión desde `backend/`:
   ```bash
   .venv/Scripts/alembic.exe revision --autogenerate -m "renombrar merchant a comercio"
   ```
3. **Revísala.** Autogenerate no sabe que un renombrado es un renombrado (lo escribe
   como "quitar una columna y crear otra", que perdería los datos), así que los
   renombrados y los cambios de forma se corrigen a mano dentro de
   `op.batch_alter_table(...)`.
4. `docker compose up -d --build`. El arranque copia la base, aplica la versión y
   rehace los triggers de protección.

Desde la terminal Alembic solo **escribe** versiones: `upgrade`, `downgrade` y `stamp`
están bloqueados, porque se saltarían el respaldo previo y los triggers. Una prueba
(`test_el_modelo_y_las_migraciones_dicen_lo_mismo`) falla si cambias una entidad y
olvidas su versión.

Los cambios de **datos** (renombrar una categoría, mover movimientos) van aparte, en
`backend/app/plataforma/migraciones.py`.

### Cambiar el puerto

Crea un `.env` en la raíz (copia de `.env.example`) y cambia una sola línea:

```
PUERTO_WEB=9090
```

El resto se deriva solo.

---

## Puesta en marcha sin Docker (desarrollo)

Requisitos: Python 3.11+ y Node 20+.

### 1. Backend

```bash
cd backend
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

En la raíz del proyecto, copia la configuración:

```bash
cp .env.example .env
```

Arranca la API:

```bash
cd backend && .venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
```

- API: http://127.0.0.1:8000
- Documentación interactiva: http://127.0.0.1:8000/docs

La primera vez se crea la base de datos en `data/finanzas.db` y se siembran las cuentas,
la taxonomía de categorías y unas reglas de ejemplo.

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Abre http://localhost:5173. El servidor de desarrollo hace proxy de `/api` al backend.

### 3. Datos para explorar (opcional)

Si quieres ver el panel con contenido antes de conectar Gmail:

```bash
cd backend && .venv/Scripts/python.exe scripts/datos_demo.py --dias 120
```

Para borrarlos después:

```bash
cd backend && .venv/Scripts/python.exe scripts/datos_demo.py --borrar
```

---

## Conectar el correo (2 minutos)

**Sin esto la app no lee ni un correo.** Es lo único imprescindible.

1. Activa la **verificación en 2 pasos** en
   [tu cuenta de Google](https://myaccount.google.com/security). Sin ella, el paso 2
   no existe.
2. Crea una **contraseña de aplicación** en
   [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) y
   copia las 16 letras.
3. Copia `.env.example` a `.env` y rellena dos líneas:

```
IMAP_USER=tucorreo@gmail.com
IMAP_PASSWORD=las16letras
```

4. `docker compose up -d`
5. En la app, pantalla **Correo → Probar conexión**, y luego **Sincronizar**.

A partir de ahí lee tu correo **solo, cada 15 minutos**. No tienes que entrar a pulsar
nada. Se ajusta con `SYNC_INTERVAL_MINUTES` (0 lo desactiva).

**Privacidad:** pasados `EMAIL_RETENTION_DAYS` días (90 por defecto) se borra el *texto*
de cada correo guardado. Se conserva su ficha (remitente, asunto y fecha), que es lo que
impide procesarlo dos veces, y los movimientos ya extraídos no se tocan. Con `0` no se
borra nunca: útil mientras se calibran los parsers, porque a un correo sin texto ya no
se le puede aplicar un arreglo.

### ¿Por qué contraseña de aplicación y no OAuth?

La API de Gmail parece más correcta —permiso de solo lectura, sin contraseñas— pero
tiene un problema práctico que la descalifica para uso personal: `gmail.readonly` es un
*restricted scope*, y mientras la app esté en estado **"Testing"** en Google Cloud
Console, **el refresh token caduca a los 7 días**. Habría que volver a autorizar cada
semana. Salir de "Testing" exige pasar la verificación de Google, que para un proyecto
de una persona no tiene sentido.

Una contraseña de aplicación no caduca.

**El precio, dicho claramente:** da acceso IMAP completo al buzón (leer y borrar), no
solo lectura. Mitigaciones: vive en tu `.env`, en tu máquina, fuera de git; esta app
solo hace `SELECT` y `FETCH`, nunca `STORE` ni `EXPUNGE`; y se revoca en un clic desde
esa misma página de Google.

> Si prefieres OAuth pese al vencimiento semanal: pon `EMAIL_BACKEND=gmail`, crea un ID
> de cliente OAuth de tipo **Aplicación web** con el URI
> `http://localhost:8080/api/gmail/callback`, y guarda el JSON en
> `secrets/credentials.json`. La pantalla Correo te guía.

---

## Importar tu Excel

Está **apagado por defecto** (`IMPORTAR_EXCEL_HABILITADO=false`). El Excel ya está
importado hasta el 31/08/2026 y desde setiembre los gastos llegan por correo: otro archivo
con filas nuevas los duplicaría.

Para importar a propósito:

1. Pon `IMPORTAR_EXCEL_HABILITADO=true` en el `.env` y reinicia (`docker compose up -d`).
2. Abre **Importar Excel** en el menú y sube el archivo. Primero se analiza sin escribir
   nada; solo importa cuando lo confirmas.
3. Vuelve a ponerlo en `false` al terminar.

El importador convierte el formato ancho (una fila por día, una columna por tipo de gasto)
al formato largo. Las columnas *Gastos totales* y *Beneficios* **no** se importan: son
derivadas y el backend las recalcula. Es idempotente (importar dos veces no duplica) y
cada importación se deshace entera desde la misma pantalla.

> El antiguo `scripts/importar_excel.py` se retiró en set. 2026: no respetaba el
> interruptor ni el corte de entonces (31/07) y podía duplicar gastos.

---

## Las pantallas

| Pantalla | Para qué |
|---|---|
| **Panel** | El resumen: cifras del periodo, ritmo de gasto, esencial vs. fuga, categorías, tendencia de 12 meses, rankings y alertas |
| **Registrar gasto** | Alta manual con atajos. Es la puerta de entrada del efectivo |
| **Movimientos** | Tabla con filtros. La categoría se cambia en la propia fila. Incluye la papelera |
| **Tendencia** | Cómo evolucionan tus ingresos y gastos a lo largo de los meses |
| **Seguimiento** | Cortes de saldo real (cuánto hay en cada cuenta en una fecha) contra lo registrado: diferencia real, registrado, efecto del dólar y descuadre. Descuadre cerca de cero = no se te escapa ningún gasto. Gráficos por YTD, último año o todo (por defecto), con una estimación simple de los próximos meses (la tendencia de los cortes del último año). El historial se importa una vez desde el Excel de saldos; los cortes nuevos se registran en la propia pantalla |
| **Por revisar** | Bandeja de triaje: lo que cambia una cifra y la app no puede decidir sola (comercio desconocido, posible duplicado, cobro en otra moneda) |
| **Presupuesto** | Topes mensuales por categoría y meta de ahorro (opcionales) |
| **Correo** | Estado de la conexión, sincronización, correos sin parsear y laboratorio de patrones |
| **Importar Excel** | Solo aparece con `IMPORTAR_EXCEL_HABILITADO=true` |
| **Reglas** | Tus reglas de clasificación, por prioridad |
| **Cuentas y copias** | Cuentas y últimos 4 dígitos de cada tarjeta, categorías, y el estado de los respaldos |

---

## Pruebas

```bash
cd backend && .venv/Scripts/python.exe -m pytest -q
```

191 pruebas: parsers de correo contra el texto de correos reales, flujo completo de la
API, idempotencia de la ingesta, deduplicación cruzada, protección de los datos del
usuario (triggers y papelera), migraciones de datos y de esquema, respaldos, agregaciones y aprendizaje por
corrección. Corren siempre sobre una base temporal, nunca sobre `data/finanzas.db`.

```bash
cd frontend && npm run typecheck
```

---

## Cosas que conviene saber

- **El dinero se guarda en céntimos enteros.** Nunca en coma flotante.
- **Las transferencias no son gastos.** Pagar la tarjeta o recargar Yape mueve dinero
  entre tus bolsillos; no lo gasta. Queda fuera de todos los totales.
- **Nada se borra solo.** Un posible duplicado se marca para que lo revises tú, y lo que
  borras va a la papelera.
- **Cada corrección enseña al sistema.** Si cambias la categoría de un comercio, la
  próxima vez la acierta.
- **No hay login.** Sirve solo en `localhost`. Antes de exponerlo por VPN, lee la
  sección 8 de [`docs/CONTEXTO.md`](docs/CONTEXTO.md).
