# Informe de mejoras de rendimiento — website y backoffice

Rama: `feat/frontend-performance` · Base auditada: `140351b` · Análisis previo: [`AUDIT.md`](AUDIT.md)

Este informe recoge qué se corrigió, cuánto mejoró cada métrica medida y qué se descartó. Todas las cifras salen de Lighthouse 12 sobre
builds de producción en `localhost`, con Chromium headless sin extensiones. La metodología completa está en `AUDIT.md` §1.

---

## 1. Tabla de evidencias

Siguiendo la skill `performance`, las **métricas** son la evidencia y la puntuación de Lighthouse es solo un resumen. Lab = navegación
en frío, emulación móvil de Lighthouse (412 px, CPU 4×, 4G lenta). No hay datos de campo (CrUX/RUM): el sitio no tiene tráfico real y
todo lo que sigue es laboratorio.

| Señal | Vista y condiciones | Antes | Después | Fuente |
|-------|---------------------|------:|--------:|--------|
| **FCP = LCP** | Website `/`, móvil, throttling real, mediana de 5 [rango] | 1,67 s [1,66–1,75] | **0,94 s** [0,92–1,01] | `experiments/ab-website` |
| **FCP = LCP** | Website `/aplicar`, móvil, throttling real, mediana de 5 | 1,63 s [1,57–1,71] | **0,90 s** [0,87–0,96] | `experiments/ab-website` |
| **CLS** | Backoffice `/suppliers`, 1024 px, `PerformanceObserver` | 0,18 | **0** | `layout-shift-probe.mjs` |
| **CLS** | Backoffice `/suppliers`, 360–1600 px | 0,05–0,18 | **0** en todos los anchos | `layout-shift-probe.mjs` |
| **CLS** | Backoffice `/inventory/products`, móvil, mediana de 3 | 0,03 | **0** | `before/` → `after/` |
| **Ancho de página** | Backoffice `/` y `/suppliers`, 360 px | 698 y 818 px | **360 px** | revisión de 11 vistas, 320–1440 px |
| **Accessibility** | Website `/` y `/aplicar`, móvil y desktop | 91 / 92 | **100 / 100** | `before/` → `after/` |
| **Accessibility** | Backoffice `/` y `/inventory/products`, móvil | 93 / 96 | **100 / 100** | `before/` → `after/` |

---

## 2. Puntuaciones antes y después

Medición inicial (`audit/before/lighthouse/`) frente a la final (`audit/after/lighthouse/`): mismo script
([`lighthouse-runner.mjs`](lighthouse-runner.mjs)), modo simulado, 3 corridas y mediana. Formato: Performance / Accessibility / Best
Practices / SEO.

| Vista | Modo | Antes | Después |
|-------|------|-------|---------|
| Website `/` | Móvil | 96 / 91 / 100 / 100 | 84 ¹ / **100** / 100 / 100 |
| Website `/` | Desktop | 100 / 91 / 100 / 100 | 100 / **100** / 100 / 100 |
| Website `/aplicar` | Móvil | 92 / 92 / 100 / 100 | 90 ¹ / **100** / 100 / 100 |
| Website `/aplicar` | Desktop | 100 / 92 / 100 / 100 | 100 / **100** / 100 / 100 |
| Backoffice `/` | Móvil | 98 / 93 / 100 / 60 ² | 99 / **100** / 100 / 60 ² |
| Backoffice `/` | Desktop | 100 / 100 / 100 / 60 ² | 100 / 100 / 100 / 60 ² |
| Backoffice `/inventory/products` | Móvil | 94 / 96 / 100 / 60 ² | **99** / **100** / 100 / 60 ² |
| Backoffice `/inventory/products` | Desktop | 100 / 100 / 100 / 60 ² | 100 / 100 / 100 / 60 ² |

¹ **No es una regresión atribuible a los cambios; ver §4.** Las corridas finales de la home fueron 73/91/84 en un Codespace de 2
núcleos recién reiniciado. En la comparación intercalada (misma máquina, 5 rondas alternas), el código original da 92 [90–96] y el
actual 91 [84–92].

² Intencionado: el backoffice declara `robots: noindex` porque es una app interna.

**Métricas móviles (mediana de 3, modo simulado)**

| Vista | FCP | LCP | TBT | CLS | Speed Index |
|-------|-----|-----|-----|-----|-------------|
| Website `/` | 0,8 → 0,8 s | 2,7 → 3,1 s ³ | 90 → 400 ms ³ | 0 → 0 | 0,8 → 0,9 s |
| Website `/aplicar` | 0,8 → 0,8 s | 2,5 → 2,6 s ³ | 260 → 300 ms ³ | 0 → 0 | 0,8 → 0,9 s |
| Backoffice `/` | 0,6 → 0,6 s | 1,3 → 1,2 s | 180 → 110 ms ⁴ | 0 → 0 | 0,9 → 0,8 s |
| Backoffice inventario | 0,6 → 0,6 s | 1,4 → 1,2 s | 290 → 100 ms ⁴ | **0,03 → 0** | 1,0 → 0,7 s |

³ LCP y TBT simulados en el website: ver §4. Con throttling real, el LCP mejora de 1,67 a 0,94 s.
⁴ Ningún cambio del backoffice reduce trabajo de JavaScript, así que esta bajada del TBT **no se atribuye** a las correcciones: es
variación entre sesiones de medición.

Capturas: `audit/before/lighthouse/*.png` y `audit/after/lighthouse/*.png` (una por vista y modo, con el JSON completo al lado).

---

## 3. Correcciones aplicadas

Un problema por commit. Cada uno se validó volviendo a medir la misma URL, y la evidencia intermedia está en `audit/experiments/`.

### 3.1 Rendimiento y estabilidad visual

| Commit | Problema (AUDIT.md) | Cambio | Impacto medido |
|--------|--------------------|--------|----------------|
| `cdb84f0` | P3 — CSS bloqueante en el website | `experimental.inlineCss` en `uis/website/next.config.ts`: el CSS de Tailwind (~6 KB) va en un `<style>` y no en un `<link>` | FCP = LCP móvil con throttling real: **1,67 → 0,94 s** (`/`) y **1,63 → 0,90 s** (`/aplicar`). Coste: HTML 7,6 → 26,7 KB |
| `ebcc29a` | P7 — CLS en proveedores | Lista con alto fijo y scroll interno bajo `xl` (región enfocable con teclado) y `min-w-0` en la sección | CLS **0,18 → 0** (1024 px) y 0 de 360 a 1600 px; sin scroll horizontal en móvil |
| `da43c22` | P2 — CLS del inventario | En móvil el título de la tabla ocupa la fila completa, así que el selector de almacén no cambia de fila al llegar los datos | CLS **0,03 → 0**; Performance móvil **94 → 99** |
| `70f8f26` | P8 — Desbordamiento del dashboard | `min-w-0` en `Panel`, en la columna del inventario y en `CarrierSimulator`: el scroll horizontal queda dentro de las tablas | Ancho de página a 360 px **698 → 360**. Resuelve también el contraste del `<thead>` de P6 |
| `a3886f1` | P1 — Deprecación en Next 16 | `priority` → `preload` en `FramedImage` | Sin cambio de rendimiento (HTML idéntico); deja de usar una API deprecada |

### 3.2 Accesibilidad

| Commit | Problema | Cambio | Impacto |
|--------|----------|--------|---------|
| `9c4b312` | P6 — `link-name` | El nombre del enlace de perfil del TopBar pasa de `hidden` a `sr-only` en móvil | Backoffice Accessibility **93/96 → 100** |
| `5787dbb` | P5 — `color-contrast` | Copyright del footer de `slate-500` a `slate-400` (4,23:1 → ≈7,5:1) | Website Accessibility **91/92 → 95/96** |
| `5067068` | P5 — `target-size` | Enlaces de teléfono y correo del footer de 18 a 28 px de alto | Website Accessibility **→ 100** |
| `f9c05af` | P5 — `label-content-name-mismatch` | Se quitan los `aria-label` que sustituían al texto visible y la prop `ariaLabel` de `ButtonLink` | Ya no falla ninguna auditoría de accesibilidad del website |

### 3.3 Refactorizaciones (código duplicado)

| Commit | Abstracción | Sustituye | Verificación |
|--------|-------------|-----------|--------------|
| `275e110` | Custom Hook [`useApiList`](../uis/backoffice/lib/use-api-list.ts) (backoffice) | La lógica de carga, cancelación, error legible y reintento copiada en `InventoryStockTable`, `InventoryOrderHistory`, `useSkuCatalog` y `SupplierDirectory` (unas 90 líneas repetidas menos) | 6 tests nuevos en jsdom (100 % de líneas del hook); en la app: datos, filtros, 503 con «Reintentar» y sin errores de consola |
| `f28de65` | Componente `ErrorFallback` (uno por app, `components/ui/`) | El contenido duplicado de `error.tsx` y `global-error.tsx` en website y backoffice | Ruta temporal que falla en cliente (no incluida): textos, `aria-labelledby`, log sin mensaje técnico y «Reintentar» |

Estado final: `npm run verify` sin errores (typecheck, lint y build de las dos apps) y Jest del backoffice 59/59.

---

## 4. Lo que las mediciones no respaldaron

**P1 — LCP de 2,7 s en la home móvil (descartado como problema).** El valor procede del modo simulado (Lantern). Con throttling real el
LCP es de 1,7 s, el mismo valor que el FCP. Se probó a quitar el preload de la imagen del hero: en móvil no cambió nada (1,7 → 1,7 s) y
en desktop, donde la imagen sí es el LCP, apareció `lcp-lazy-loaded`. Se revirtió. Evidencia: `experiments/p1-hero-preload/`.

**Puntuación simulada del website tras el CSS inline.** La medición final da 84 en la home móvil. Para saber si era un efecto del
cambio o ruido, se comparó de forma intercalada (5 rondas alternas en la misma máquina) el código original, el mismo sin el CSS inline y
el actual:

| Home móvil, mediana [rango] | Original | Sin CSS inline | Actual |
|-----------------------------|----------|----------------|--------|
| Throttling real — FCP = LCP | 1667 ms [1656–1753] | 1667 ms [1660–1711] | **936 ms** [922–1014] |
| Throttling real — Performance | 98 | 98 | 99 |
| Simulado — FCP | 773 ms [771–839] | 776 ms [771–821] | 811 ms [808–825] |
| Simulado — Performance | 92 [90–96] | 94 [86–95] | 91 [84–92] |

Conclusiones:

- El 96 de la línea base y el 84 de la final están dentro del rango del **mismo código**. En este Codespace de 2 núcleos, una misma
  variante (sin CSS inline) dio un TBT simulado de 133 a 529 ms según la carga del host. Una diferencia de pocos puntos en una sola
  sesión no es una conclusión.
- El CSS inline **sí** tiene un coste en el modelo simulado: +38 ms de FCP, porque cobra los ~19 KB extra de HTML sobre 4G lenta. Ese
  coste es real pero pequeño.
- Con throttling real (latencia de ~560 ms por petición), eliminar la petición bloqueante del CSS adelanta el primer pintado ~0,7 s,
  con rangos que no se solapan. Se mantiene porque refleja mejor lo que vive un usuario en una red móvil lenta. Hay que revisarlo cuando
  haya datos de campo.

---

## 5. Qué tuvo más impacto

1. **CSS inline en el website (−0,7 s de FCP/LCP en móvil real).** Es la mejora de rendimiento más grande para el usuario y la que más
   afecta al SEO: el contenido aparece 44 % antes en red lenta. Es un solo flag, pero experimental: puede cambiar al actualizar Next.
2. **Estabilidad del layout en el backoffice (CLS 0,18 → 0 en proveedores, 0,03 → 0 en inventario, sin desbordamiento).** Era el único
   Core Web Vital fuera de umbral que se reprodujo. Salió al buscar en otras vistas el mismo patrón que el inventario, lo que demuestra
   que auditar solo las vistas de la tarea se habría quedado corto.
3. **Accesibilidad a 100 en las dos apps.** Cuatro fallos WCAG reales (A y AA) corregidos. Uno de ellos, el contraste del `<thead>`, era
   un síntoma del desbordamiento, y la corrección de layout lo resolvió.

Lo que **no** movió los números, y así se documenta: la migración `priority` → `preload` y los dos refactors. Su valor es de
mantenimiento y consistencia, no de rendimiento.

---

## 6. Riesgos y trabajo pendiente

| Tema | Estado | Siguiente paso |
|------|--------|----------------|
| Autenticación solo en cliente (P2) | El backoffice no pinta nada hasta hidratar y resolver `/auth/me`. Cambiarlo es una reestructuración, fuera del alcance de esta tarea | Evaluar sesión por cookie + `proxy`/middleware de Next 16 en un hito propio |
| JavaScript del framework (P4) | 13–14 KiB de polyfills y ~29 KiB sin usar en chunks de Next/React | Revisar al actualizar Next; no es código de TrackFlow |
| `experimental.inlineCss` | Opción experimental de Next 16 | Comprobar tras cada actualización de Next que el HTML sigue llevando `<style>` y medir de nuevo |
| Datos de campo | No existen: ninguna cifra de este informe es de usuarios reales | Añadir RUM con `web-vitals` cuando el sitio tenga tráfico (skill `performance`, `references/RUM.md`) |
| Ruido de medición | Codespace de 2 núcleos | Para decidir, usar comparaciones intercaladas ([`ab-compare.mjs`](ab-compare.mjs)) y no sesiones sueltas |

---

## 7. Uso de la skill de agente

Se instaló `performance` (addyosmani/web-quality-skills) en `.agents/skills/performance/`, fijada en `skills-lock.json` (commit `da6ecf3`).
Guió el proceso en cuatro puntos concretos:

- **Medir antes de tocar código y cambiar solo lo ligado a un cuello de botella medido.** Por eso P4 (JS del framework) no se tocó, y
  la corrección del hero (P1) se revirtió al no mejorar la métrica.
- **Llamar hipótesis a lo que no está medido** y dar la medición que lo verifica. P1 se refutó y P3 se confirmó con throttling real.
- **Comparaciones repetibles** (`references/MEASUREMENT.md`): condiciones registradas, al menos 3 navegaciones con mediana y rango, y
  «usar los valores de las métricas como evidencia; la puntuación es un resumen diagnóstico». Esto llevó a descartar la bajada simulada
  del website como ruido, con datos.
- **Formato del informe:** tabla de evidencias al inicio, separando fallos medidos, causas respaldadas por trazas, hipótesis,
  correcciones y verificación pendiente (§1, §3, §4 y §6).
