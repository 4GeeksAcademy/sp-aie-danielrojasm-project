# Informe de caching — TrackFlow

Qué se ha cacheado en la API (`services/api`) y en el backoffice (`uis/backoffice`), por qué, con qué TTL
y qué se decidió no cachear. Cada decisión parte de una medición: los scripts y los JSON de resultados
están en [`audit/caching/`](audit/caching/).

---

## 1. Cómo se midió

### Timing por petición

`services/api/main.py` añade un middleware que escribe una línea por petición en el logger
`trackflow.timing` y devuelve la cabecera `Server-Timing: app;dur=<ms>`:

```
INFO:     trackflow.timing GET /inventory/products -> 200 | 377.2ms
```

Para que esas líneas se vean hubo que corregir algo previo: uvicorn solo configura sus propios loggers,
así que los `logger.info` de `trackflow.*` (inventario, incidencias y ahora timing y caché) se perdían.
`_configure_logging()` añade un handler al logger `trackflow`.

[`audit/caching/measure_api.py`](audit/caching/measure_api.py) pide cada GET 31 veces seguidas con la
misma URL (la ráfaga que se buscaría en los logs), descarta la primera como calentamiento y guarda la
mediana y el p95 del `Server-Timing` (coste dentro de la API) y de la ida y vuelta completa.

### Dos escenarios, porque miden cosas distintas

| Escenario | Base de datos | Volumen | Qué aísla |
|---|---|---|---|
| **Supabase** | PostgreSQL de Supabase (Transaction pooler), datos reales | 6 SKUs, 13 movimientos, 95 incidencias, 15 proveedores | Coste de red: cada consulta es una ida y vuelta al pooler |
| **Volumen** | SQLite local sembrado con `scripts/seed_load_test.py` | 1.200 SKUs, 43.200 recepciones, 28.800 salidas (72.000 movimientos), 5.000 incidencias, 15 proveedores | Coste de cálculo: agregaciones, JOIN y parseo de TinyDB con datos de tamaño real |

En producción los dos costes se suman. El seeder no escribe en Supabase: la base es compartida por el
equipo y el script rechaza cualquier URL que no sea SQLite o PostgreSQL en `localhost`. Genera clientes,
categorías, almacenes, cantidades y fechas variadas (18 meses de histórico, salidas que nunca dejan el
stock en negativo, reparto de incidencias parecido al de la muestra real) para que los `GROUP BY` y los
filtros trabajen de verdad.

### Frontend

- **Bundle por ruta:** [`audit/caching/route-js.mjs`](audit/caching/route-js.mjs) suma los `<script>` del HTML
  prerenderizado de cada ruta tras `next build` (lo que el navegador descarga al abrirla).
- **Coste por pulsación:** [`audit/caching/typing-probe.mjs`](audit/caching/typing-probe.mjs) abre
  `/inventory/orders/outbound` en Chrome headless con la CPU a 4×, espera al catálogo completo (1.203
  `<option>`) y escribe 40 caracteres en el número de seguimiento. Por pulsación mide el tiempo entre la
  captura del evento `input` en `window` y el final de sus microtareas, que es donde React ejecuta
  `onChange`, render y commit. La Event Timing API no servía porque no registra eventos de menos de 16 ms.
  Son 5 corridas y se da la mediana.

---

## 2. Backend

### Evaluación de los endpoints

Coste medido (p50 del `Server-Timing`). La frecuencia se estima a partir de las vistas del backoffice
que llaman a cada ruta.

| Endpoint | Coste Supabase / Volumen | Frecuencia | Cambio de los datos | Decisión |
|---|---|---|---|---|
| `GET /inventory/products` | **377 ms** / **87 ms** (191 KB) | Alta: tabla de stock, selector de SKU de los formularios de entrada y de salida, y vuelta a la tabla tras cada movimiento | Con cada movimiento (decenas por hora), casi siempre desde esta API | **Cacheado, TTL 30 s** |
| `GET /api/incidents/summary` | 3 ms / **40 ms** (lineal con el fichero) | Alta: al abrir `/incidents` y de nuevo **tras cada cambio de estado** | Con cada alta o cambio de estado, siempre desde esta API salvo el seed | **Cacheado, TTL 60 s** |
| `GET /inventory/products/{id}` | 375 ms / 4 ms | Una vez por SKU elegido en el formulario de salida | Con cada movimiento de ese SKU | No: es la cifra que decide la salida (§5) |
| `GET /inventory/orders` | 302 ms / **3.037 ms (23,8 MB)** | Baja: historial | Con cada movimiento | No: le falta paginación, no caché (§5) |
| `GET /api/incidents` | 5 ms / **183 ms (1,7 MB)** | Media: al abrir el tablero y al cambiar filtros | Con cada cambio de estado | No (§5) |
| `GET /api/incidents/{id}` | 5 ms / 31 ms | Baja (sin vista que lo use hoy) | Con cada cambio de estado | No: baja frecuencia |
| `GET /auth/me`, `GET /profiles/me` | 3 ms / 3 ms | Alta (`/auth/me` al restaurar sesión) | Al editar el perfil | No: son datos personales (§5) |
| `GET /users`, `GET /users/{id}` | — | Baja (administración) | Al editar usuarios | No: personales y poco frecuentes |
| `GET /suppliers`, `GET /suppliers/{id}` | 4 ms / 5 ms | Media: `/suppliers` | Al editar tarifas o estado | No: 15 filas, no hay coste que ahorrar |
| `GET /api/incidents/results/export` | — | Baja | Tras cada análisis | Ya es un resultado en memoria (`latest_analysis`) |
| `GET /` (health) | 1 ms | Healthcheck de Docker | Nunca | No: no cuesta nada |
| `POST`/`PUT`/`PATCH`/`DELETE` (18 rutas) | — | — | — | No se cachean escrituras. Las 5 que cambian un agregado cacheado **lo invalidan** |

¿Por qué `/inventory/products` cuesta lo mismo con 6 SKUs en Supabase que `/inventory/products/{id}`?
Las dos rutas hacen 4 idas y vueltas al pooler: el `pool_pre_ping`, la lectura de SKUs y los dos
`GROUP BY` de entradas y salidas. Salen a unos 94 ms cada una, así que el coste lo pone la red y no el
volumen. Con volumen, además, se suman las agregaciones sobre 72.000 movimientos y serializar 191 KB.

### Implementación

`services/api/cache.py` define `TTLCache`: una caché en memoria del proceso, con TTL obligatorio (un TTL
≤ 0 lanza error), `maxsize` con expulsión LRU, un lock para el pool de hilos de FastAPI y un método
`invalidate(reason)` que vacía todas las claves y deja la operación en el log `trackflow.cache`.

Hay una carrera que había que cerrar. Una lectura lenta empieza, entra una escritura que hace commit e
invalida, y la lectura termina y guarda el dato de **antes** del commit. Sin control, ese valor viejo
viviría hasta que venciera el TTL. `TTLCache` guarda un número de generación al empezar a calcular y no
guarda el resultado si una invalidación ha cambiado ese número entretanto
(`test_value_computed_during_an_invalidation_is_not_stored`).

No se usa `functools.lru_cache` porque no tiene TTL ni invalidación selectiva. Tampoco Redis: la API
corre hoy en un solo proceso (uvicorn en local y en Docker Compose) y Redis añadiría un servicio que
operar. La interfaz (`get_or_compute` / `invalidate`) se mantendría igual con Redis (§4, «Límite conocido»).

### `GET /inventory/products` — TTL 30 s

- **Coste:** 377 ms p50 / 455 ms p95 en Supabase y 87 ms / 140 ms con volumen. Tras la caché:
  **3,3 ms / 9,4 ms** y **4,9 ms / 12,3 ms**. Ida y vuelta en el cliente: 393 → 16 ms (Supabase) y
  105 → 25 ms (volumen; lo que queda es serializar 191 KB).
- **Frecuencia:** cada movimiento registrado supone al menos dos llamadas (selector del formulario y
  vuelta a la tabla), y el equipo de almacén registra los movimientos en tandas.
- **Clave:** el filtro de almacén (`all`, `LA`, `ZGZ`). No incluye al usuario porque la respuesta no
  depende de él: `SKUListItem` no lleva `user_uuid` y todos los usuarios autenticados ven el mismo
  inventario.
- **Invalidación:** alta de SKU, recepción y salida (`create_product`, `create_inbound_order`,
  `create_outbound_order`) llaman a `products_cache.invalidate()` justo después del `commit`. Se vacían
  todas las claves, porque un movimiento en LA cambia `LA` y también `all`. El coste de la siguiente
  lectura tras invalidar (miss) es de 104 ms con volumen.
- **Verificado por HTTP y en la UI:** una recepción de +25 en ZGZ pasa el SKU de 7519 a 7544 en la lectura
  siguiente, y una salida de 5 desde el formulario deja la tabla de stock en 7539 al volver.

### `GET /api/incidents/summary` — TTL 60 s

- **Coste:** TinyDB lee y parsea el JSON entero en cada petición: 40 ms p50 / 50 ms p95 con 5.000
  incidencias, y crece de forma lineal. Tras la caché: **2,9 ms / 6,7 ms**; ida y vuelta 61 → 17 ms. Con
  las 95 incidencias reales no hay nada que ganar (3,4 → 2,3 ms). Se cachea por lo que pasará al crecer:
  el gestor acumula incidencias sin archivarlas.
- **Frecuencia:** `IncidentManager` vuelve a pedir el resumen tras **cada** cambio de estado confirmado
  (`refreshKey`), además de al abrir la vista. Si varias personas triando las mismas incidencias, el
  resumen se pide mucho más que se escribe.
- **Clave:** una sola (`all`, `maxsize=1`). El resumen solo tiene recuentos globales y no lleva
  `reported_by` ni ningún otro dato de quien consulta.
- **Invalidación:** `create_incident` y `update_incident_status` invalidan después de escribir. La
  prueba en HTTP: con el resumen en caché, pasar una incidencia a `in_progress` cambia `open` de 1363 a
  1362 e `in_progress` de 477 a 478 en la lectura siguiente.

### Datos privados

Las dos rutas cacheadas cuelgan de routers con `dependencies=[Depends(get_current_user)]`. La
dependencia se ejecuta antes que el handler, así que sin un token válido no se llega a leer la caché
(`test_cached_endpoints_still_require_a_token`: 401 con el resumen ya en caché). Ninguna respuesta
cacheada varía por usuario, y los endpoints que sí varían (`/auth/me`, `/profiles/me`, `/users/*`) no se
cachean.

---

## 3. Frontend

### Lazy loading 1 — resultados del analizador CSV (`/incidents/analyzer`)

- **Qué:** `IncidentAnalysisResults` (KPIs, cuatro desgloses, calidad de registros y exportación) sale de
  `IncidentAnalysis` y se carga con `next/dynamic`, con un esqueleto mientras llega.
- **Por qué:** esos resultados solo existen después de subir y analizar un CSV. Hasta entonces la vista
  es un formulario de subida, y quien entra a consultar o se equivoca de fichero nunca ve los resultados.
  Es el caso que describe la guía de Next 16 (`lazy-loading.md`): cargar cuando se cumple una condición.
- **Medido:** el chunk (6,4 KB, 2,2 KB gzip) no aparece en el HTML inicial y el navegador lo pide al
  llegar la respuesta del análisis. Resultado correcto: 100 / 95 / 5 / 3,06. El JS inicial de la ruta
  baja de 644,9 a 642,1 KB (193,5 → 193,2 KB gzip).

### Lazy loading 2 — simulador de transportista del dashboard (`/`)

- **Qué:** `LazyCarrierSimulator`, un Client Component que carga `CarrierSimulator` (formulario, scoring
  y `CarrierEvaluationTable`) con `next/dynamic` cuando el panel queda a menos de 400 px del viewport
  (`IntersectionObserver`). Mientras tanto muestra un esqueleto del mismo tamaño aproximado.
- **Por qué un wrapper:** la página del dashboard es un Server Component, y la guía de Next 16 avisa de
  que desde ahí `next/dynamic` no divide el código de un Client Component.
- **Por qué este componente:** va debajo de los KPIs y del inventario y es la única parte interactiva
  pesada del panel. Medido: en móvil (412 px) el panel empieza a 1.999 px, 2,4 pantallas más abajo, y el
  chunk solo se pide al hacer scroll. En escritorio empieza a 866 px (1920×1080) o 942 px (1280×900),
  justo en el pliegue, y se pide nada más montar, aunque en un chunk aparte.
- **Medido:** chunk de 7,2 KB (2,6 KB gzip). JS inicial de `/`: de 645,8 a 642,6 KB (194,1 → 193,5 KB gzip).
  Recomendación correcta tras cargarse: UPS, 76,40 puntos, 30,89 US$.

**Sobre el tamaño:** el ahorro neto (0,3–0,6 KB gzip) es menor que el chunk diferido, porque el wrapper y
el cargador de `next/dynamic` sí van en el bundle inicial, y el JS de cada ruta está dominado por React y
Next (~190 KB gzip de los ~194). No son grandes ahorros de red. Lo que se consigue es que el trabajo de
render del simulador y de los resultados no ocupe el hilo principal al abrir la vista, sobre todo en móvil,
y que su peso futuro (gráficas en los resultados, más transportistas en el simulador) quede fuera de la
carga inicial.

### `useMemo` — opciones del selector de SKU (`useSkuCatalog`)

- **Qué:** `useSkuCatalog` devuelve `options`, los `<option>` del catálogo memorizados con
  `useMemo(() => items.map(...), [items])`. `StockEntryForm` y `StockExitForm` los usan en lugar de
  mapear el catálogo en cada render.
- **Por qué no es trivial:** los dos formularios son componentes controlados, así que **cada pulsación**
  en cantidad, referencia o tracking re-renderiza el formulario entero. Antes, cada render formateaba un
  texto y creaba un elemento por SKU, y React comparaba 1.200 `<option>`. Con los mismos elementos entre
  renders, React se salta ese diff.
- **Dependencias:** solo `items`, que `useApiList` sustituye únicamente al cargar o reintentar. El texto de
  cada opción (`formatSKUOption`) depende solo del SKU.
- **Medido** (CPU 4×, 1.203 opciones, 5 corridas × 40 pulsaciones): **4,6 → 1,5 ms de mediana** y
  **9,5 → 3,0 ms de p95** por pulsación. Unos dos tercios del trabajo de cada pulsación eran las
  opciones. Con los 6 SKUs actuales de Supabase la diferencia no se notaría, pero el catálogo crece con
  cada marca cliente y en los terminales de almacén (CPU modesta) se escribe mucho en estos campos.
- **Descartado:** `useMemo` en `IncidentBoard`. Parecía el candidato natural (filtrar, calcular «más de
  24 h» y formatear fechas por fila), pero cada cambio de estado sustituye la lista en el estado
  (actualización optimista y confirmación), así que el memo se recalcularía en casi todos los renders que
  importan. Añadiría complejidad sin beneficio.

---

## 4. Intercambios reconocidos (frescura frente a rendimiento)

### Por qué el stock tolera 30 s

Las escrituras de esta API invalidan al momento. El TTL solo acota lo que tarda en verse un cambio que
**no** pasa por este proceso: `scripts/seed_inventory.py`, SQL lanzado directamente en Supabase o, cuando
la API tenga varios workers o réplicas, una salida atendida por otra instancia. En esos casos la tabla de
stock y sus avisos de «stock bajo» pueden ir hasta 30 s por detrás.

Es aceptable porque ese dato **no decide nada irreversible**:

1. La cifra de «disponible» que ve el operario antes de una salida viene de `GET /inventory/products/{id}`,
   que no se cachea.
2. La regla de stock la aplica `create_outbound_order`, que recalcula con la fila del SKU bloqueada
   (`FOR UPDATE`). Aunque una lista en caché mostrara stock de más, la API rechazaría la salida con 400
   (`test_exit_checks_live_stock_not_the_cached_list`).
3. La reposición por stock bajo se planifica en horas; 30 s de retraso en un aviso no cambia ninguna
   decisión.

No se eligió un TTL más largo (5 min) porque, con varias réplicas, una salida registrada en otra instancia
no se vería en ese tiempo, y el panel de stock tiene que parecer en tiempo real. Tampoco uno más corto
(5 s): el operario tarda más que eso en rellenar un formulario y volver a la tabla, así que casi todas las
lecturas serían miss.

### Por qué el resumen de incidencias tolera 60 s

Se aplica el mismo razonamiento. Los cambios hechos desde el tablero invalidan al momento; solo un seed
(una importación por lotes que se lanza a mano) o una réplica distinta dejarían los recuentos hasta 60 s
atrás. Son métricas de un panel, y el SLA de una incidencia se mide en horas (el tablero marca las de más
de 24 h). Es el doble que el stock porque aquí hay aún menos escrituras externas y ninguna decisión
depende del recuento exacto.

### Límite conocido: una caché por proceso

La caché vive en cada proceso. Con `uvicorn --workers N` o varias réplicas, cada una tendría su copia y
una escritura solo invalidaría la del proceso que la atendió. Hoy no pasa (un solo proceso en local y en
Docker Compose). El día que la API escale, el TTL marca el máximo de desactualización y el siguiente paso
es Redis con la misma interfaz.

---

## 5. Qué no se cacheó y por qué

- **`GET /inventory/orders` (historial), el más lento de todos:** 3.037 ms y 23,8 MB con 72.000
  movimientos. La caché lo taparía a costa de guardar 24 MB por clave en memoria de cada proceso, y el
  primer usuario tras cada movimiento seguiría esperando 3 s. El problema es que devuelve **todo** el
  histórico. Hay que paginarlo (`limit`/`cursor` por `created_at`), no cachearlo. Queda como tarea propia.
- **`GET /inventory/products/{id}`:** también cuesta 375 ms en Supabase, pero es el stock que el operario
  mira justo antes de registrar una salida. Si ahí viera un dato viejo, tomaría una decisión con él. Además
  se pide una vez por SKU elegido, así que la caché acertaría pocas veces.
- **`GET /api/incidents` (tablero):** 183 ms con 5.000 incidencias, pero tiene cuatro filtros combinables
  (hasta 1.200 claves de 1,7 MB). Los cambios de estado, que son la interacción principal de esa vista,
  invalidarían todas las claves cada pocos segundos. Como en el historial, la solución es paginar y
  filtrar en la base de datos cuando las incidencias salgan de TinyDB.
- **`GET /auth/me`, `GET /profiles/me` y `get_current_user`:** son datos personales. Además, la
  comprobación del usuario en cada petición (que lee `auth.json`, ~3 ms) tiene que seguir leyendo de la
  base: si un usuario se desactiva o se borra, su token debe dejar de valer en la petición siguiente, no
  pasado un TTL.
- **`GET /suppliers`:** 4 ms con 15 proveedores. No hay coste que justifique una caché y una invalidación
  que mantener.
- **Frontend: `useMemo` en `CarrierSimulator`:** `evaluateCarriers` recorre 5 transportistas y todas sus
  entradas cambian con cada campo del formulario, así que el memo se invalidaría en cada render.

---

## 6. Verificación

- `uv run pytest`: 198 tests en verde, 19 nuevos en `tests/cache/test_cache.py`. Cubren expiración exacta
  en el TTL, invalidación, LRU, TTL obligatorio, la carrera de generación, lecturas concurrentes, la
  invalidación en cada escritura de inventario e incidencias, cambios externos visibles tras el TTL, que la
  regla de stock ignora la caché y el 401 sin token. `tests/conftest.py` vacía las cachés entre tests,
  porque son del módulo.
- `npm test` (backoffice): 59 en verde. `npm run verify`: tipos, lint y build de las dos apps.
- En el navegador (Chrome headless contra `next start` y la API con volumen): el simulador se carga al
  hacer scroll en móvil, los resultados del CSV se cargan tras analizar, la salida de stock se registra y
  la tabla refleja el cambio al instante, sin errores de consola.

### Reproducir

```bash
# 1. Base local con volumen (nunca Supabase)
uv run python scripts/seed_load_test.py --database-url sqlite:///C:/tmp/load.db --incidents-db C:/tmp/load-incidents.json
# 2. API contra esa base
DATABASE_URL=sqlite:///C:/tmp/load.db INCIDENTS_DB_PATH=C:/tmp/load-incidents.json AUTH_DB_PATH=C:/tmp/load-auth.json \
  JWT_SECRET_KEY=<32+ caracteres> uv run uvicorn services.api.main:app --port 8011
# 3. Latencias
uv run python audit/caching/measure_api.py --base-url http://127.0.0.1:8011 --email <email> --password <pwd> --label <nombre>
# 4. Frontend (desde uis/backoffice, con TRACKFLOW_API_INTERNAL_URL apuntando a la API)
npm run build && node ../../audit/caching/route-js.mjs
npx next start --port 3102   # y, en otra terminal, audit/caching/typing-probe.mjs (necesita puppeteer-core y Chrome)
```

Resultados de esta medición: `audit/caching/results/` (`before-*` / `after-*` para la API,
`route-js-*` y `typing-*` para el frontend).
