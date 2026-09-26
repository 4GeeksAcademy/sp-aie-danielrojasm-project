---
description: Convenciones para las apps Next.js 16 + TypeScript + Tailwind v4 de uis/ (componentes, etiquetas, layouts, accesibilidad).
trigger: glob
globs: "uis/**/*.{ts,tsx,css}"
---

# Regla: apps Next.js en `uis/`

**Alcance: por patrón de archivo** (`trigger: glob`, `uis/**/*.{ts,tsx,css}`). Se activa al leer o editar código de cualquier app de
`uis/`. No aplica a `src/` ni a documentación.

## Antes de escribir código

- Next.js **16.2.10** tiene cambios incompatibles con versiones anteriores. Consulta `uis/<app>/node_modules/next/dist/docs/` antes de
  usar una API de Next (config, `Image`, metadata, caché, rutas). Si no hay `node_modules`, ejecuta `npm install` en esa app (pide
  permiso primero).

## Estructura de cada app

| Carpeta | Contenido |
| --- | --- |
| `app/` | Rutas (App Router): `layout.tsx`, `page.tsx`, `globals.css`. Sin lógica de negocio ni datos inline largos |
| `components/<área>/` | Componentes React en PascalCase, un componente exportado por archivo (`SiteHeader.tsx`) |
| `content/` | Textos y datos estáticos tipados (web pública) |
| `lib/` | Funciones puras, adaptadores, etiquetas y datos de ejemplo |
| `types/` | Interfaces y tipos propios de la app |

## Reglas de código

1. **Componentes reutilizables y tipados.** Props con `interface XProps`; nada de `any`. Si un bloque JSX se repite 2+ veces, extráelo
   a componente (ej. `FeatureCard`, `ButtonLink`, `Panel`, `KpiCard`).
2. **Server Components por defecto.** Añade `"use client"` solo si hay estado, efectos o eventos (ej. `ApplicationForm`,
   `CarrierSimulator`). Los cálculos con datos estáticos se hacen en el servidor.
3. **Imports con alias**: `@/…` para la propia app; `@trackflow/logic/…` para `src/` (solo en apps configuradas para ello).
4. **Nunca mostrar valores crudos de dominio.** `"In transit"`, `"Same-day"`, `"Low stock"`, `in_progress`, `personal_interview`…
   se muestran con un `Record<Tipo, string>` de etiquetas en español (`uis/backoffice/lib/labels.ts`,
   `uis/talent-pipeline-tracker/lib/domain.ts`). Un valor nuevo del tipo debe romper la compilación, no llegar a la UI.
5. **Idioma**: la UI es en español con tildes. Importes con `Intl.NumberFormat("es-ES", { currency: "USD" })` (el modelo es en USD).
6. **Layouts separados**: `uis/website` (marca pública: `bg-slate-950`, acento `cyan-300`, `emerald-300` para métricas) y
   `uis/backoffice` (interno: sidebar `slate-900`, contenido `slate-100`, `robots: noindex`). No importes componentes de una app en otra.
7. **Tailwind v4**: sin `tailwind.config.js`; tokens en `app/globals.css` con `@theme inline`. Evita CSS a mano salvo lo global.
8. **Accesibilidad mínima**: cada `input`/`select` con `<label>` asociado; errores con `role="alert"` y `aria-describedby`; `<section>`
   con `aria-labelledby`; imágenes con `alt` descriptivo usando `next/image` (hosts permitidos en `images.remotePatterns`).
9. **Puertos**: website 3000, backoffice 3002 (no uses 3001: es la API por defecto del tracker del Hito 3).

## Verificación

`npm run typecheck`, `npm run lint` y `npm run build` dentro de la app terminan con código 0, y `npm run dev` sirve la ruta tocada con
HTTP 200.
