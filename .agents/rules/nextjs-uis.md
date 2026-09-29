---
description: Convenciones para las apps Next.js 16 + TypeScript + Tailwind v4 de uis/ (componentes, etiquetas, layouts, accesibilidad).
trigger: glob
globs: "uis/**/*.{ts,tsx,css}"
---

# Regla: apps Next.js en `uis/`

## AI Engineering · 4Geeks Academy — Regla de agente de código

---

**Alcance:** por patrón de archivo (`trigger: glob`, `uis/**/*.{ts,tsx,css}`). Se activa al leer o editar código de cualquier app de `uis/`. No
aplica a `src/` ni a la documentación.

Las interfaces de TrackFlow las usan marcas, operarios y directores en dos países. Esta regla asegura que todas las apps sigan la misma
estructura, muestren siempre etiquetas legibles en español y no rompan la integración con la lógica del Hito 2.

## Antes de escribir código

### 📖 Leer la documentación de Next 16

Next.js **16.2.10** tiene cambios incompatibles con versiones anteriores. Antes de usar una API de Next (configuración, `Image`, metadata,
caché, rutas) hay que consultar `uis/<app>/node_modules/next/dist/docs/`. Si no hay `node_modules`, se ejecuta `npm install` en esa app,
pidiendo permiso primero.

---

## Estructura de cada app

- **`app/`** — rutas del App Router: `layout.tsx`, `page.tsx` y `globals.css`. Sin lógica de negocio ni datos largos escritos a mano.
- **`components/<área>/`** — componentes React en PascalCase, uno exportado por archivo (por ejemplo, `SiteHeader.tsx`).
- **`content/`** — textos y datos estáticos tipados (en la web pública).
- **`lib/`** — funciones puras, adaptadores, etiquetas y datos de ejemplo.
- **`types/`** — interfaces y tipos propios de la app.

---

## Reglas de código

### 🧩 Componentes reutilizables y tipados

Las props se declaran con `interface XProps` y nunca con `any`. Si un bloque de JSX se repite dos o más veces, se extrae a un componente
(como `FeatureCard`, `ButtonLink`, `Panel` o `KpiCard`).

---

### ⚡ Server Components por defecto

Solo se añade `"use client"` cuando hay estado, efectos o eventos (como en `ApplicationForm` o `CarrierSimulator`). Los cálculos con datos
estáticos se hacen en el servidor.

---

### 🔗 Imports con alias

`@/…` para la propia app y `@trackflow/logic/…` para `src/`, solo en las apps configuradas para ello.

---

### 🏷️ Nunca valores crudos de dominio

`"In transit"`, `"Same-day"`, `"Low stock"`, `in_progress`, `personal_interview` y similares se muestran siempre con un
`Record<Tipo, string>` de etiquetas en español (`uis/backoffice/lib/labels.ts`, `uis/talent-pipeline-tracker/lib/domain.ts`). Un valor
nuevo del tipo tiene que romper la compilación, no llegar a la pantalla.

---

### 🌍 Idioma y moneda

La UI está en español y con tildes. Los importes se formatean con `Intl.NumberFormat("es-ES", { currency: "USD" })`, porque el modelo está en
USD.

---

### 🎨 Layouts separados

La web pública (`uis/website`) usa la marca: fondo `bg-slate-950`, acento `cyan-300` y `emerald-300` para métricas. El backoffice
(`uis/backoffice`) es interno: sidebar `slate-900`, contenido `slate-100` y `robots: noindex`. No se importan componentes de una app en otra.

---

### 💨 Tailwind v4

Sin `tailwind.config.js`: los tokens van en `app/globals.css` con `@theme inline`. Se evita el CSS a mano salvo el global.

---

### ♿ Accesibilidad mínima

Cada `input` y `select` tiene su `<label>`. Los errores llevan `role="alert"` y `aria-describedby`. Cada `<section>` lleva
`aria-labelledby`. Las imágenes usan `next/image` con un `alt` descriptivo y solo desde hosts permitidos en `images.remotePatterns`.

---

### 🔢 Puertos

La web usa el 3000 y el backoffice el 3002. No se usa el 3001, que es la API por defecto del tracker del Hito 3.

---

## Cómo comprobarla

`npm run typecheck`, `npm run lint` y `npm run build` dentro de la app terminan con código 0, y `npm run dev` sirve la ruta tocada con HTTP
200.

---

_Documento interno — 4Geeks Academy · AI Engineering Track_
_Regla por patrón de archivo para las interfaces de TrackFlow_
