# `uis` folder

This folder contains **all the user interfaces** related to the company for the cross-functional AI Engineering project (for example: web applications, internal dashboards, customer portals, Streamlit/Gradio apps, etc.).

Each subfolder inside `uis/` must correspond to **one specific user interface** (for example: `website`, `backoffice`) and include its own technical and functional documentation.

- **Main purpose**: to centralize in a single place all the frontend applications that support the company's use cases.
- **Recommendation**: document in this file (or in sub-READMEs) the applications you add, their objective, the technology used, and how to run them.

> _Spanish version: [README.es.md](./README.es.md)._

## Applications in this monorepo

| Folder | Purpose | Stack | Run |
| --- | --- | --- | --- |
| [`website/`](./website/README.md) | Public corporate website (Milestone 1, migrated to Next.js) | Next.js 16 · TS · Tailwind 4 | `npm run dev` → :3000 |
| [`backoffice/`](./backoffice/README.md) | Internal app; home shows Milestone 2 business logic (`/src`) | Next.js 16 · TS · Tailwind 4 | `npm run dev` → :3002 |
| [`talent-pipeline-tracker/`](./talent-pipeline-tracker/README.md) | Candidate pipeline (Milestone 3) | Next.js 16 · TS · Tailwind 4 | `npm run dev -- --port 3003` |
