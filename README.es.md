# Proyecto de Compañía - Ingeniería de IA — Plantilla para estudiantes

[![4Geeks Academy](https://img.shields.io/badge/4Geeks-Academy-blue)](https://4geeksacademy.com)
[![AI Engineering](https://img.shields.io/badge/track-AI%20Engineering-green)](https://4geeksacademy.com/es/programas-de-carrera/ingenieria-ia)

_Plantilla base para proyectos transversales del Programa de Carrera en Ingeniería de IA — 4Geeks Academy._

_Las instrucciones están [disponibles en inglés](./README.md)._

---

## Propósito

Este repositorio es la **plantilla de inicio** para los proyectos transversales. Trabajarás con escenarios de empresas reales (Brasaland, TrackFlow, Nexova) construyendo entregables que se corresponden con los hitos del curso (Web, Programación, Backend, Telemetría, RAG, Agentes, Workflows, Tiempo real).

- Crea una plantilla a partir de este repositorio.
- Reemplaza el `CONTEXT.md` placeholder por el contexto de tu empresa asignada.
- Usa `skills/` y los `README.md` por carpeta como guía de trabajo.

---

## Estado actual (TrackFlow, Hito 4)

Este fork contiene el proyecto de **TrackFlow**. `CONTEXT.md` recoge el briefing de la empresa.

- **Lógica de negocio (Hito 2)** en `src/`; `uis/backoffice` la importa (nunca la copia).
- **Interfaces** en `uis/`: `uis/website` (web pública, :3000), `uis/backoffice` (app interna, :3002) y `uis/talent-pipeline-tracker`
  (Hito 3). Ver [`uis/README.es.md`](./uis/README.es.md).
- **APIs** en `services/` (todavía ninguna).
- **Configuración de agentes de código**: [`AGENTS.md`](./AGENTS.md), `memory-bank/` y `.agents/` (reglas y skills).
- **Scripts de la raíz**: `npm run verify` (tipos + lint + build), `npm run dev:website`, `npm run dev:backoffice`. Cada app instala sus
  propias dependencias (sin runner de workspaces).

---

## Estructura del repositorio

```text
ai-engineering-company-project-monorepo/
├── README.md
├── README.es.md
├── CONTEXT.md                # Briefing de la empresa TrackFlow
├── AGENTS.md                 # Protocolo de agentes de código (+ CLAUDE.md)
├── .agents/                  # Reglas y skills de agentes de código
├── memory-bank/              # Contexto persistente para agentes de código
├── src/                      # Lógica de negocio del Hito 2 (TypeScript)
├── agents/                   # Patrones/plantillas de agentes y documentación de tools
├── data/                     # raw, process, pipelines, eval
├── docs/                     # Documentación de proyecto y arquitectura
├── infra/                    # Docker, Terraform, configuraciones de despliegue
├── internal/                 # CLIs, scripts de migración empaquetados, utilidades internas
├── mcps/                     # Servidores Model Context Protocol (MCP)
├── packages/
│   └── shared/               # Paquete compartido (@repo/shared-types)
├── scripts/                  # Convenciones/documentación de scripts
├── services/                 # APIs y workers en segundo plano
├── shared/                   # Recursos/convenciones compartidas a nivel repo
├── skills/                   # Skills reutilizables para agentes
├── uis/                      # Interfaces: website, backoffice, talent-pipeline-tracker
└── workflows/                # Documentación de automatizaciones/orquestación
```

---

## Cómo empezar

1. **Usa este repositorio como plantilla** y crea tu propio repo de proyecto.
2. **Clona** tu repositorio (o ábrelo en Codespaces).
3. **Reemplaza** `CONTEXT.md` con el contexto completo de tu empresa asignada.
4. **Revisa** los `README.md` de cada carpeta raíz para entender responsabilidades (`uis/`, `services/`, `data/`, `skills/`, etc.).
5. **Empieza a implementar** entregables por hito en `uis/` y `services/`, reutilizando `packages/shared/` y `data/` según corresponda.

---

## Worker en segundo plano (Celery + Redis)

Las operaciones largas no corren dentro de la API. `POST /reporting/pipeline-runs` encola el pipeline semanal y responde
`202` con un `task_id`. Un worker de Celery aparte lo ejecuta, y `GET /tasks/{task_id}` informa de su estado. Detalle:
[`services/tasks/README.md`](./services/tasks/README.md).

```bash
# Levantar (desde la raíz; variables en .env, ver .env.example)
docker compose up -d redis worker flower      # broker, worker y Flower en http://localhost:5555
docker compose logs -f worker                 # log de cada intento (task_id, intento, estado, duración)

# Detener
docker compose stop worker                    # warm shutdown: termina la tarea en curso; lo encolado sigue en Redis
docker compose down                           # todo (los datos de Redis se conservan en el volumen redis-data)

# Worker sin Docker (Redis tiene que estar arriba); en Windows, añadir --pool=solo
uv run --env-file .env celery -A services.tasks.celery_app worker --loglevel=INFO --queues=default,dead_letter
```

---

## Hitos (referencia)

| Hito | Enfoque       | Entregables típicos                              |
| ---- | ------------- | ------------------------------------------------ |
| 0    | Prework       | Configuración del entorno, primeros prompts      |
| 1    | Web           | Sitio corporativo, formularios, SEO              |
| 2    | Programación  | Lógica de negocio, puntuación, cálculos          |
| 3    | UI con IA     | Interfaces generadas con IA                      |
| 4    | Next.js       | Portales, app de fidelización, UI de operaciones |
| 5    | Backend       | API central (ubicaciones, menús, ventas, etc.)   |
| 6    | Telemetría    | Pipeline de datos, dashboards                    |
| 7    | RAG y memoria | Base de conocimiento semántica, búsqueda         |
| 8    | Agentes       | Agentes de soporte, onboarding, formación        |
| 9    | Workflows     | Automatizaciones con n8n                         |
| 10   | Tiempo real   | Dashboards en vivo, alertas, streaming           |

---

## Enlaces

- [4Geeks Academy — Ingeniería de IA](https://4geeksacademy.com/es/programas-de-carrera/ingenieria-ia)
- [Cómo empezar un proyecto de código](https://4geeks.com/lesson/how-to-start-a-project)

---

## Contribuidores

Esta plantilla fue creada como parte del Programa de Carrera de Ingeniería de IA de 4Geeks Academy por [@marcogonzalo](https://www.linkedin.com/in/marcogonzalo) y [@alezanchezr](https://x.com/alesanchezr), junto a otros muchos colaboradores. Descubre más sobre nuestro [Curso de Ingeniería de IA](https://4geeksacademy.com/es/programas-de-carrera/ingenieria-ia) y sobre [otros cursos](https://4geeksacademy.com/es/comparar-programas).

Puedes encontrar otras plantillas y recursos similares en la [página de GitHub de 4Geeks Academy](https://github.com/4geeksacademy).

_Esta plantilla la mantiene 4Geeks Academy para el track de Ingeniería de IA. Uso exclusivo del programa._
