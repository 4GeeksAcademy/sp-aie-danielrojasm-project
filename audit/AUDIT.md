# Auditoría de rendimiento — website y backoffice

Commit auditado: `140351b` · Next.js 16.2.10 (Turbopack) · React 19.2.4

Este documento recoge la **medición inicial**, los **problemas encontrados con su causa raíz** y el **análisis de código duplicado**. Las
correcciones y la comparativa antes/después están en [`REPORT.md`](REPORT.md).

---

## 1. Metodología

### 1.1 Qué se midió

| App | Vista | Por qué |
|-----|-------|---------|
| Website (`uis/website`, :3000) | `/` | Página de entrada y la que más importa para SEO: hero con imagen, 5 secciones y 2 imágenes remotas. |
| Website | `/aplicar` | Vista más interactiva: formulario de ~20 campos hidratado en cliente (`ApplicationForm`). |
| Backoffice (`uis/backoffice`, :3002) | `/` | Panel de operaciones: KPIs, tablas, simulador y validaciones renderizados a la vez. Es la vista que el equipo abre a diario. |
| Backoffice | `/inventory/products` | Única vista del hito con datos reales de la API (tabla de stock cargada tras autenticar). |

Las dos vistas del backoffice se midieron **con sesión iniciada**: con un usuario de auditoría, el JWT se guarda en `localStorage`
igual que hace `/login`. Sin sesión, Lighthouse solo habría medido la pantalla «Redirigiendo al acceso…».

### 1.2 Condiciones

- **Build de producción** (`next build` + `next start`). `next dev` penaliza la puntuación con JS sin minificar y compilación bajo demanda.
- **Lighthouse 12 (CLI)** con Chromium headless 153, sin extensiones, contra `localhost`.
- **Móvil**: emulación estándar de Lighthouse (412×823, DPR 1,75, 4G lenta simulada, CPU 4×). **Desktop**: preset `desktop-config`
  (1350×940, sin throttling de CPU).
- **3 corridas por URL y modo**; se guarda la **mediana** (`computeMedianRun`). El script está en
  [`audit/lighthouse-runner.mjs`](lighthouse-runner.mjs) y la medición final usa el mismo script.
- Layout shifts por ancho de pantalla: [`audit/layout-shift-probe.mjs`](layout-shift-probe.mjs) (`PerformanceObserver`, CPU 4×).
- Resultados: [`audit/before/lighthouse/`](before/lighthouse/): informe JSON y captura PNG por vista y modo. El JSON se puede
  abrir en el [Lighthouse Viewer](https://googlechrome.github.io/lighthouse/viewer/) para ver el informe completo.

---

## 2. Puntuaciones iniciales

### 2.1 Categorías

| App | Vista | Modo | Performance | Accessibility | Best Practices | SEO |
|-----|-------|------|:-:|:-:|:-:|:-:|
| Website | `/` | Mobile | **96** | 91 | 100 | 100 |
| Website | `/` | Desktop | 100 | 91 | 100 | 100 |
| Website | `/aplicar` | Mobile | **92** | 92 | 100 | 100 |
| Website | `/aplicar` | Desktop | 100 | 92 | 100 | 100 |
| Backoffice | `/` | Mobile | 98 | **93** | 100 | 60 ¹ |
| Backoffice | `/` | Desktop | 100 | 100 | 100 | 60 ¹ |
| Backoffice | `/inventory/products` | Mobile | **94** | 96 | 100 | 60 ¹ |
| Backoffice | `/inventory/products` | Desktop | 100 | 100 | 100 | 60 ¹ |

¹ Intencionado: `uis/backoffice/app/layout.tsx` declara `robots: { index: false, follow: false }` porque es una app interna. Lighthouse
lo marca como `is-crawlable` fallido. **No se corrige.**

Variabilidad observada entre las 3 corridas (Performance móvil): website `/` 93–96, `/aplicar` 92–96, backoffice `/` 93–98,
inventario 94–99. Una diferencia de ±3 puntos entre antes y después **está dentro del ruido** y no se considera mejora.

### 2.2 Métricas clave (mediana)

| Vista | Modo | FCP | LCP | TBT | CLS | Speed Index | TTFB ² |
|-------|------|----:|----:|----:|----:|----:|----:|
| Website `/` | Mobile | 0,8 s | **2,7 s** ³ | 90 ms | 0 | 0,8 s | 10 ms |
| Website `/aplicar` | Mobile | 0,8 s | 2,5 s ⚠️ | **260 ms** ⚠️ | 0 | 0,8 s | 10 ms |
| Backoffice `/` | Mobile | 0,6 s | 1,3 s | 180 ms | 0 | 0,9 s | 10 ms |
| Backoffice inventario | Mobile | 0,6 s | 1,4 s | **290 ms** ⚠️ | 0,03 | 1,0 s | 0 ms |
| Todas | Desktop | 0,2 s | 0,4–0,6 s | 0–10 ms | 0 | 0,3–0,4 s | ≤10 ms |

Umbrales: LCP < 2,5 s · CLS < 0,1 · TBT < 200 ms (en laboratorio es el indicador aproximado de INP; el INP real requiere datos de
campo, que no existen porque el sitio no tiene tráfico real).

² El TTFB en `localhost` no representa producción: no hay red ni CDN. Todas las páginas se sirven prerenderizadas (`x-nextjs-cache: HIT`)
y comprimidas con gzip, y los chunks con hash llevan `Cache-Control: public, max-age=31536000, immutable`. **No hay un problema de servidor
que corregir.**

³ Valor simulado (Lantern). Con throttling real la home móvil da LCP 1,7 s (ver P1).

**Lectura:** en desktop las dos apps ya cumplen todos los umbrales. El margen real está en **móvil**, donde la CPU emulada es 4× más
lenta y la red es 4G lenta: un TBT alto en `/aplicar` y en el inventario, y un LCP simulado por encima del umbral en la home que la
medición con throttling real no confirma (P1). En
accesibilidad hay fallos reales en las dos apps.

---

## 3. Problemas identificados y causa raíz

Ordenados por impacto en usuarios reales, primero los Core Web Vitals.

### P1 — LCP móvil de la home del website: 2,7 s simulado, 1,7 s real

- **Evidencia.** En móvil el elemento LCP es el `<h1 id="hero-title">`, un **texto**; en desktop es la imagen del hero (0,6 s). El
  2,7 s procede del modo por defecto de Lighthouse (`simulate`, modelo Lantern). Al repetir la medición con throttling real
  (`throttlingMethod: devtools`, misma emulación móvil, 3 corridas) el resultado es **FCP 1,7 s = LCP 1,7 s**: el `<h1>` se pinta en
  el mismo frame que el primer contenido.
- **Causa raíz del valor simulado.** Lantern estima el LCP con todas las peticiones que empezaron antes del LCP observado. Contra
  `localhost`, todo arranca en los primeros ~150 ms: HTML, CSS (6 KB), fuente (30 KB), imagen del hero precargada (95 KB) y 164 KB
  de JS del runtime de Next/React. Al reproducir esas descargas sobre 4G lenta simulada, el LCP estimado se infla hasta 2,7 s aunque el
  `<h1>` no dependa de la imagen ni del JS. **No es un problema que sufra el usuario**; en producción, con red real, el orden de
  llegada sí pesa, y por eso se vigila con la medición con throttling real.
- **Hipótesis probada y descartada.** Se sospechó del `<link rel="preload">` de la imagen del hero, que se adelanta al CSS. Se probó
  a quitarlo (`loading="lazy"` + `fetchPriority="high"`; con `loading="eager"` React 19 vuelve a generar el preload en el SSR): en
  móvil no cambió nada con throttling real (1,7 s → 1,7 s) y en desktop apareció `lcp-lazy-loaded`, porque allí la imagen sí es el
  LCP. El preload es correcto y se mantiene. Detalle en `REPORT.md`.
- **Hallazgo colateral.** `FramedImage` usaba `priority`, **deprecado** en Next 16 en favor de `preload`, que tiene el mismo
  comportamiento. Se migra sin impacto en rendimiento.

### P2 — TBT móvil alto en `/aplicar` (260 ms) y en el inventario del backoffice (290 ms)

- **Evidencia (`/aplicar`).** Hay tareas largas de 292 ms en el chunk de React (`0ke84o…js`) y de 214 ms en el propio documento
  (parseo del payload RSC más hidratación), con 1,8 s de trabajo en el hilo principal. `ApplicationForm` es un client component de
  325 líneas que se hidrata entero al cargar.
- **Evidencia (backoffice).** Hay 1,5–1,8 s de hilo principal repartidos entre los chunks de React/Next y la app. La cadena de
  renderizado es secuencial: HTML con solo «Verificando sesión…» → descarga y ejecución de JS → hidratación → `GET /api/auth/me`
  → render del panel → en el inventario, `GET /api/inventory/products` → render de la tabla.
- **Causa raíz (backoffice).** La autenticación es solo de cliente: `AuthProvider` y `ProtectedShell` envuelven **todo** el layout, así
  que ni la barra lateral ni la cabecera se pintan hasta tener la respuesta de `/auth/me`. Es una decisión de arquitectura documentada en
  `memory-bank/techContext.md` (sin `middleware.ts`). Cambiarla a autenticación en servidor sería una reestructuración, y la tarea la
  excluye expresamente, así que se deja como riesgo.
- **Causa raíz (inventario, CLS 0,03).** `layout-shifts` señala la leyenda de niveles (`p.mt-3` de `InventoryStockTable`). Un
  `PerformanceObserver` de `layout-shift` en el navegador muestra quién la empuja: el `<select>` de almacén baja de y=591 a y=659.
  La cabecera de la tabla es una fila `flex-wrap` con el título y el selector. Mientras carga, el texto de estado («Cargando
  inventario...») es corto y el selector cabe al lado; al llegar los datos, «6 SKUs · 0 sin stock · 1 con stock bajo» ensancha la
  columna del título, el selector salta a una segunda fila y todo lo de debajo baja 68 px. Solo ocurre entre ~380 y 640 px de ancho.

### P7 — CLS de proveedores entre 360 y 1279 px (hasta 0,18)

- **Evidencia.** La vista `/suppliers` no estaba entre las auditadas, pero el mismo `PerformanceObserver` la mide al revisar el patrón
  de P2: CLS 0,11 a 360 px, 0,05 a 412, 0,09 a 640, 0,14 a 768 y **0,18 a 1024** (umbral 0,1). A partir de 1280 px es 0.
- **Causa raíz.** Por debajo de `xl` (1280 px) el formulario de alta va **debajo** de la lista. La lista carga con un esqueleto de 4
  filas y al llegar los datos se convierte en una tabla de 14 filas: el formulario, visible en pantalla, se desplaza cientos de píxeles.
  El esqueleto no reserva el alto real porque el número de proveedores no se conoce hasta que responde la API.
- **Segunda causa (≤ 640 px).** La sección de la lista es un elemento de grid con `min-width: auto`, así que adopta el ancho mínimo
  de la tabla (`min-w-[760px]`) y el `overflow-x-auto` interior nunca actúa: a 360 px la sección pasa de 286 a 760 px al llegar los
  datos, la página se desborda en horizontal (`scrollWidth` 818) y los filtros cambian de fila.

### P3 — CSS bloqueante en el website (≈150 ms estimados en móvil)

- **Evidencia.** `render-blocking-insight` señala el único CSS de la app (6 KB comprimidos, Tailwind v4) como bloqueante, con un ahorro
  estimado de 150 ms en la home y de 110 ms en `/aplicar`.
- **Causa raíz.** Es el comportamiento por defecto de Next: una hoja global enlazada en `<head>`. Con 6 KB, el coste real es la latencia
  de la petición, no su tamaño. Next 16 ofrece `experimental.inlineCss` para incrustarla en el HTML. Es una **hipótesis** que se validará
  midiendo, porque la opción es experimental.

### P4 — JavaScript «legacy» y «sin usar» (13–14 KiB y 29 KiB)

- **Evidencia.** Hay polyfills de `Array.prototype.at`, `flat`, etc. (13–14 KiB) y un 41 % sin usar del chunk principal del website
  (29 KiB de 73 KiB).
- **Causa raíz.** Los dos están en **chunks del framework** (runtime de Next/React), no en código de TrackFlow. El website solo tiene
  tres client components (`ApplicationForm`, `error`, `global-error`), y el backoffice importa `lucide-react` por nombre, algo que Next
  optimiza por defecto (`optimizePackageImports`). **No es accionable** sin cambiar la configuración de navegadores objetivo del framework.
  Se documenta y no se toca.

### P5 — Accesibilidad del website (91–92)

| Auditoría | Dónde | Causa raíz |
|-----------|-------|------------|
| `color-contrast` | `SiteFooter.tsx:42`, línea de copyright | `text-slate-500` (`#62748e`) sobre `bg-slate-950` (`#020618`) da **4,23:1**, por debajo del 4,5:1 que exige WCAG AA para texto de 12 px. |
| `target-size` | `SiteFooter.tsx:19,24`, enlaces `tel:` y `mailto:` | Enlaces en línea de **18 px de alto**, por debajo del mínimo de 24×24 px de WCAG 2.2 (2.5.8) y demasiado juntos. En móvil se pulsa el enlace equivocado. |
| `label-content-name-mismatch` | `Logo.tsx:12`, `SiteHeader.tsx:27`, `ContactSection.tsx:34,41` (vía `ButtonLink` → `ariaLabel`) | Un `aria-label` **sustituye** al texto visible («Aplicar» → «Ir al formulario de aplicación»). Quien usa control por voz dice lo que ve y el comando no coincide (WCAG 2.5.3, *Label in Name*). El patrón viene de `ButtonLink`, que acepta `ariaLabel` para enlaces cuyo texto ya es descriptivo. |

### P6 — Accesibilidad del backoffice (93–96 en móvil)

| Auditoría | Dónde | Causa raíz |
|-----------|-------|------------|
| `link-name` | `components/layout/TopBar.tsx:26`, enlace a «Mi perfil» | El único texto del enlace es un `<span className="hidden sm:inline">`. Por debajo de 640 px queda **sin nombre accesible**: un lector de pantalla anuncia solo «enlace». Afecta a todas las vistas protegidas en móvil. |
| `color-contrast` | `<thead>` de `components/dashboard/InventoryTable.tsx:19` y `CarrierEvaluationTable.tsx:14` | `text-slate-500` sobre `bg-slate-100` da **4,34:1**, por debajo de 4,5:1. |

### Descartados tras el análisis

| Señal | Por qué no es un problema de la app |
|-------|------------------------------------|
| «Peticiones RSC duplicadas» (`/?_rsc=…` ×3–4) | No son duplicados: Next 16 prefetchea **por segmento** (layout, page…), como indica `Vary: next-router-segment-prefetch`. Cada petición trae un segmento distinto. |

---

## 4. Análisis de código duplicado (candidatos a refactorización)

La regla de arquitectura de `memory-bank/techContext.md` («Layouts separados: [website y backoffice] no comparten layout ni
componentes») descarta extraer componentes **entre** apps. Los error boundaries y `FormField` de las dos apps se parecen, pero tienen
estilos y textos distintos a propósito (tema oscuro público frente a tema claro interno). Los candidatos están **dentro** de cada app.

### Caso 1 — Carga de datos con cancelación y reintento (backoffice) → Custom Hook `useApiList`

**Dónde aparece.** El mismo bloque de unas 20 líneas se repite, con solo el loader y el mensaje cambiados, en:

| Archivo | Líneas | Loader | Mensaje de error |
|---------|--------|--------|------------------|
| `components/inventory/InventoryStockTable.tsx` | 26–53 | `listSKUs()` | «No se pudo cargar el inventario.» |
| `components/inventory/InventoryOrderHistory.tsx` | 52–79 | `listInventoryOrders()` | «No se pudo cargar el historial de movimientos.» |
| `components/inventory/useSkuCatalog.ts` | 16–44 | `listSKUs()` | «No se pudo cargar la lista de SKUs.» |
| `components/suppliers/SupplierDirectory.tsx` | 90–114 | `requestJson('/api/suppliers?…')` con filtros | «No se pudo cargar el directorio de proveedores.» |

Cada copia declara 4 estados (`data`, `loading`, `error`, `attempt`) y un `useEffect` con la misma bandera `active` (para no escribir
estado tras desmontar), el mismo `Array.isArray` defensivo, el mismo `getUserMessage(error, fallback)` y el mismo contador `attempt`
para reintentar.

**Por qué es candidato.**
- **Riesgo de divergencia.** Es la ruta que garantiza que «ningún fallo de la API queda en silencio» (AGENTS.md §5.3). Si se corrige
  un detalle en una copia (por ejemplo, conservar los datos anteriores al reintentar o abortar la petición con `AbortController`),
  las otras tres se quedan atrás.
- **Duplicación ya reconocida.** `useSkuCatalog` es literalmente la versión «hook» del bloque de `InventoryStockTable`, y las dos llaman
  a `listSKUs()`.
- **Mismo contrato de estados en toda la app.** Carga, error legible y reintento deben comportarse igual en stock, historial,
  formularios de movimientos y proveedores; con un único hook, un cambio de UX (por ejemplo, un indicador de carga distinto) se
  aplica en un sitio.

**Abstracción propuesta** (`uis/backoffice/lib/use-api-list.ts`). Las cuatro copias cargan **listas**, así que el hook es específico de
listas y absorbe también el `Array.isArray` defensivo:

```ts
export interface ApiList<T> {
  items: T[];
  setItems: Dispatch<SetStateAction<T[]>>; // altas/ediciones confirmadas por la API (proveedores)
  loading: boolean;
  error: string;
  retry: () => void;
}

export function useApiList<T>(
  load: () => Promise<T[]>,
  fallbackMessage: string,
  key = "", // recarga al cambiar (p. ej. la query string de los filtros)
): ApiList<T>;
```

`load` se envuelve con `useEffectEvent` (React 19.2): puede ser una función nueva en cada render (el loader de proveedores
depende de los filtros) sin relanzar la carga ni saltarse `react-hooks/exhaustive-deps`; lo que decide cuándo recargar es `key`.

Uso resultante:

```ts
const { items: skus, loading, error, retry } = useApiList<SKU>(listSKUs, "No se pudo cargar el inventario.");
```

`useSkuCatalog` queda como un envoltorio sobre `useApiList` con el mismo contrato, para no tocar `StockEntryForm` ni `StockExitForm`.
`SupplierDirectory` pasa la query string de los filtros como `key` y usa `setItems` para reflejar altas y cambios de tarifa o estado.
El hook tiene su propio test (`__tests__/use-api-list.test.tsx`, jsdom).

### Caso 2 — Pantalla de error duplicada entre `error.tsx` y `global-error.tsx` (en cada app) → componente `ErrorFallback`

**Dónde aparece.**

| App | Archivos | Qué se repite |
|-----|----------|---------------|
| Website | `app/error.tsx` (53 líneas) y `app/global-error.tsx` (53 líneas) | El mismo `useEffect` de log con `error.digest ?? error.name`, el mismo par de botones «Reintentar» / «Ir al inicio» con las mismas clases, y el mismo párrafo «Si el problema continúa, escríbenos a {company.email}». Solo cambian el título, el texto y el contenedor (`<section>` frente a `<html><body><main>`). |
| Backoffice | `app/error.tsx` (52 líneas) y `app/global-error.tsx` (50 líneas) | El mismo patrón: log con `digest`, los botones «Reintentar» / enlace al panel con clases idénticas, y el aviso «indicando la referencia {digest}». |

**Por qué es candidato.** Son las pantallas que ve una persona cuando algo falla. Si se cambia el texto de soporte, el correo de
contacto o el estilo de los botones, hay que recordar editar dos archivos por app, y hoy ya divergen en detalles: «Ir al panel de
operaciones» frente a «Ir a la página principal» en el backoffice.

**Abstracción propuesta** (una por app, en `components/feedback/ErrorFallback.tsx`):

```tsx
interface ErrorFallbackProps {
  error: Error & { digest?: string };
  onRetry: () => void;
  title: string;
  description: string;
  /** Texto del log de consola: distingue error de ruta y error crítico. */
  logLabel: string;
  headingId?: string;
}
```

`error.tsx` renderiza `<ErrorFallback …/>` dentro de su `<section role="alert">`, y `global-error.tsx` lo renderiza dentro de
`<html><body><main role="alert">`, que es lo único que Next exige que sea distinto en el global error. Así se mantiene la
independencia entre apps: cada una tiene su `ErrorFallback` con su tema.

### Caso 3 (menor) — `ariaLabel` en `ButtonLink` (website)

`ButtonLink` acepta un `ariaLabel` que **reemplaza** el texto visible, y tres llamadas lo usan con textos que no coinciden con lo que se
ve. Es el origen de P5 (`label-content-name-mismatch`). No es tanto duplicación como un contrato que invita al error: la corrección es
quitar esos `ariaLabel` redundantes. Si alguna vez hace falta contexto extra, debe **empezar** por el texto visible.

---

## 5. Prioridad de corrección

Siguiendo la skill `performance` (addyosmani/web-quality-skills, instalada en `.agents/skills/performance/`): solo se toca el código
ligado a un cuello de botella **medido**, y cada cambio se valida volviendo a medir la misma URL en las mismas condiciones. Un problema
por commit.

| # | Problema | KPI objetivo | Tipo |
|---|----------|--------------|------|
| 1 | P1 — Verificar el LCP con throttling real; migrar `priority` → `preload` | LCP real móvil home | Verificación + deprecación de Next 16 |
| 2 | Caso 1 — `useApiList` | Menos código repetido, mismo comportamiento | Refactor requerido por la tarea |
| 3 | P2 — Cabecera del inventario estable en móvil | CLS inventario 0,03 → 0 | Corrección (layout shift) |
| 3b | P7 — Lista de proveedores con alto fijo bajo `xl` + `min-w-0` | CLS proveedores 0,18 → 0 y sin scroll horizontal | Corrección (Core Web Vital fuera de umbral) |
| 4 | Caso 2 — `ErrorFallback` en cada app | Mantenibilidad | Refactor |
| 5 | P6 — `link-name` del TopBar y contraste de `<th>` | A11y backoffice | Corrección requerida (WCAG A/AA) |
| 6 | P5 — Contraste, tamaño de objetivos y *label in name* del website | A11y website | Corrección requerida (WCAG AA) |
| 7 | P3 — CSS inline (`experimental.inlineCss`) | FCP/LCP móvil | Hipótesis: se aplica solo si la medición lo confirma |
| — | P2 (auth en cliente), P4 (JS del framework) | — | Documentados, fuera de alcance (reestructuración o framework) |
