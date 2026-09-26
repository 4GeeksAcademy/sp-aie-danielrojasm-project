# Carpeta `uis`

Esta carpeta contiene **todas las interfaces de usuario** relacionadas con la compañía para el proyecto transversal de AI Engineering (por ejemplo: aplicaciones web, dashboards internos, portales de clientes, apps de Streamlit/Gradio, etc.).

Cada subcarpeta dentro de `uis/` debe corresponder a **una interfaz de usuario concreta** (por ejemplo `website`, `backoffice`) e incluir su propia documentación técnica y funcional.

- **Propósito principal**: centralizar en un único lugar todas las aplicaciones frontend que dan soporte a los casos de uso de la compañía.
- **Recomendación**: documenta en este archivo (o en sub-READMEs) las aplicaciones que vayas añadiendo, su objetivo, tecnología usada y cómo ejecutarlas.

## Aplicaciones de este monorepo

| Carpeta | Propósito | Stack | Ejecutar |
| --- | --- | --- | --- |
| [`website/`](./website/README.md) | Web corporativa pública (Hito 1, migrada a Next.js) | Next.js 16 · TS · Tailwind 4 | `npm run dev` → :3000 |
| [`backoffice/`](./backoffice/README.md) | App interna; su inicio muestra la lógica del Hito 2 (`/src`) | Next.js 16 · TS · Tailwind 4 | `npm run dev` → :3002 |
| [`talent-pipeline-tracker/`](./talent-pipeline-tracker/README.md) | Pipeline de candidaturas (Hito 3) | Next.js 16 · TS · Tailwind 4 | `npm run dev -- --port 3003` |
