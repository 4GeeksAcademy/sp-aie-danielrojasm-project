# AI Engineering Company Project — Student Template

[![4Geeks Academy](https://img.shields.io/badge/4Geeks-Academy-blue)](https://4geeksacademy.com)
[![AI Engineering](https://img.shields.io/badge/track-AI%20Engineering-green)](https://4geeksacademy.com/es/programas-de-carrera/ingenieria-ia)

_Base template for transversal projects in the AI Engineering Career Program — 4Geeks Academy._

> _Instrucciones disponibles en español en [README.es.md](./README.es.md)._

---

## Purpose

This repository is the **starter template** for transversal projects. You will work on real company scenarios (Brasaland, TrackFlow, Nexova), building deliverables that map to course milestones (Web, Programming, Backend, Telemetry, RAG, Agents, Workflows, Real-time).

- Create a template from this repository.
- Replace the placeholder `CONTEXT.md` with your assigned company context.
- Use `skills/` and the directory-level `README.md` files as working guidance.

---

## Current status (TrackFlow, Milestone 4)

This fork holds the **TrackFlow** project. `CONTEXT.md` contains the company briefing.

- **Business logic (Milestone 2)** lives in `src/` and is imported (never copied) by `uis/backoffice`.
- **User interfaces** live in `uis/`: `uis/website` (public site, :3000), `uis/backoffice` (internal app, :3002) and
  `uis/talent-pipeline-tracker` (Milestone 3). See [`uis/README.md`](./uis/README.md).
- **APIs** go in `services/` (none yet).
- **Coding-agent setup**: [`AGENTS.md`](./AGENTS.md), `memory-bank/` and `.agents/` (rules and skills).
- **Root scripts**: `npm run verify` (types + lint + build), `npm run dev:website`, `npm run dev:backoffice`. Each app installs its own
  dependencies (no workspace runner).

---

## Repository structure

```text
ai-engineering-company-project-monorepo/
├── README.md
├── README.es.md
├── CONTEXT.md                # TrackFlow company briefing
├── AGENTS.md                 # Coding-agent protocol (+ CLAUDE.md)
├── .agents/                  # Coding-agent rules and skills
├── memory-bank/              # Persistent context for coding agents
├── src/                      # Milestone 2 business logic (TypeScript)
├── agents/                   # Agent patterns/templates and tools docs
├── data/                     # raw, process, pipelines, eval
├── docs/                     # Project and architecture documentation
├── infra/                    # Docker, Terraform, deployment configs
├── internal/                 # CLIs, packaged migration scripts, internal utilities
├── mcps/                     # Model Context Protocol (MCP) Servers
├── packages/
│   └── shared/               # Shared package (@repo/shared-types)
├── scripts/                  # Script conventions/documentation
├── services/                 # APIs and background workers
├── shared/                   # Shared assets/conventions at repo level
├── skills/                   # Reusable agent skills
├── uis/                      # User interfaces: website, backoffice, talent-pipeline-tracker
└── workflows/                # Automation/orchestration documentation
```

---

## How to start

1. **Use this repository as a template** and create your own project repo.
2. **Clone** your repository (or open it in Codespaces).
3. **Replace** `CONTEXT.md` with the full context for your assigned company.
4. **Review** each top-level folder `README.md` to understand intended responsibilities (`uis/`, `services/`, `data/`, `skills/`, etc.).
5. **Start implementing** milestone deliverables in `uis/` and `services/`, reusing `packages/shared/` and `data/` as needed.

---

## Background worker (Celery + Redis)

Long operations do not run inside the API. `POST /reporting/pipeline-runs` enqueues the weekly pipeline and returns
`202` with a `task_id`. A separate Celery worker runs it, and `GET /tasks/{task_id}` reports its state. Details:
[`services/tasks/README.md`](./services/tasks/README.md).

```bash
# Start (from the repo root; variables in .env, see .env.example)
docker compose up -d redis worker flower      # broker, worker and Flower at http://localhost:5555
docker compose logs -f worker                 # per-attempt logs (task_id, attempt, status, duration)

# Stop
docker compose stop worker                    # warm shutdown: finishes the running task; queued messages stay in Redis
docker compose down                           # everything (Redis data survives in the redis-data volume)

# Worker without Docker (Redis must be running); on Windows add --pool=solo
uv run --env-file .env celery -A services.tasks.celery_app worker --loglevel=INFO --queues=default,dead_letter
```

---

## Milestones (reference)

| Milestone | Focus        | Typical deliverables                        |
| --------- | ------------ | ------------------------------------------- |
| 0         | Prework      | Environment setup, first prompts            |
| 1         | Web          | Corporate website, forms, SEO               |
| 2         | Programming  | Business logic, scoring, calculations       |
| 3         | AI-driven UI | AI-generated interfaces                     |
| 4         | Next.js      | Portals, loyalty app, operations UI         |
| 5         | Backend      | Central API (locations, menus, sales, etc.) |
| 6         | Telemetry    | Data pipeline, dashboards                   |
| 7         | RAG & Memory | Semantic knowledge base, search             |
| 8         | Agents       | Support, onboarding, training agents        |
| 9         | Workflows    | n8n automations                             |
| 10        | Real-time    | Live dashboards, alerts, streaming          |

---

## Links

- [4Geeks Academy — AI Engineering](https://4geeksacademy.com/es/programas-de-carrera/ingenieria-ia)
- [How to start a coding project](https://4geeks.com/lesson/how-to-start-a-project)

---

## Contributors

This template was built as part of the 4Geeks Academy AI Engineering Career Program by [@marcogonzalo](https://www.linkedin.com/in/marcogonzalo) and [@alezanchezr](https://x.com/alesanchezr) and many other contributors. Find out more about our [AI Engineering Course](https://4geeksacademy.com/en/career-programs/ai-engineering), and [other courses](https://4geeksacademy.com/en/program-comparison).

You can find other templates and resources like this at the [4Geeks Academy GitHub page](https://github.com/4geeksacademy).

_This template is maintained by 4Geeks Academy for the AI Engineering track. For exclusive use in the programme._
