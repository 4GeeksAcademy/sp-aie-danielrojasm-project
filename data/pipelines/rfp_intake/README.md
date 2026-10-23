# Recepción, enrutamiento y generación de respuestas a RFPs (`rfp_intake`)

Flujo agéntico de propuestas. En la **Parte 1**, Ventas sube la RFP del cliente en PDF desde el backoffice y, sin
leer el documento original, ve qué le toca a cada departamento (Warehouse, Last Mile, Reverse Logistics) y a quién
pedírselo. En la **Parte 2** (ver [más abajo](#parte-2--generación-y-evaluación-de-respuestas)), ese análisis se
convierte en un primer borrador de la propuesta económica por departamento, revisado automáticamente antes de que
lo vea un humano.

## Recorrido

```
Backoffice /rfps ──POST /rfps──▶ API (services/rfp_intake/router.py)
                                  ├─ valida el PDF (firma %PDF-, ≤ 10 MB)
                                  ├─ guarda data/raw/rfp_intake/<ticket_id>.pdf
                                  ├─ crea el ticket en `analizando` (PostgreSQL)
                                  ├─ encola rfp_intake.process_ticket [ticket_id] (Celery + Redis)
                                  └─ 202 { ticket_id, status, task_id }
Worker de Celery (services/tasks/rfp_intake.py) ──▶ runner.process_ticket ──▶ grafo rfp_intake
Backoffice /rfps/<ticket_id> ──GET /rfps/<ticket_id> cada 4 s mientras está en `analizando`
```

El grafo es propio (`graph.py`) y no comparte nodos con el agente de CX de `services/support_agent`:

```
START → convert_document → classify_document ─┬─ (no es RFP) → discard → END
                                              └─ (RFP) → extract_metadata → orchestrate
orchestrate ─┬─ Send → warehouse_worker / lastmile_worker / reverse_worker (en paralelo, solo los activos)
             └─ (ningún departamento aplica) → synthesize
*_worker → synthesize → END
```

| Nodo | Agente | Qué decide el código encima del modelo |
| --- | --- | --- |
| `convert_document` | — | PDF → Markdown con el `PdfConverter` de MarkItDown. Un PDF corrupto falla (no pasa como texto). |
| `classify_document` | `classifier.py` | Solo descarta si el modelo dice "no es RFP" con confianza ≥ 0,6. |
| `extract_metadata` | `extraction.py` | Moneda por país (US → USD, ES → EUR); un volumen que no aparece en el texto se descarta. Métricas de legibilidad. |
| `orchestrate` | `orchestrator.py` | Solo crea workers para `warehouse`, `lastmile` y `reverse` (el id de servicio, p. ej. `last_mile`, es alias de su departamento); el resto va a `out_of_scope`. Todo servicio pedido en los metadatos activa su departamento. |
| `*_worker` | `workers.py` | Una frase con una cifra que no está en sus extractos ni en los metadatos se descarta y pasa a pregunta abierta. Sin volumen mensual, `warehouse` y `lastmile` siempre preguntan por él. |
| `synthesize` | `synthesizer.py` | La estructura de workstreams (departamento, responsable, listas) se arma en código; el modelo solo redacta resumen, pasos y contradicciones. |

Los agentes usan el modelo de generación del gateway (`LLM_GENERATION_MODEL`) en modo JSON con esquema Pydantic.
El documento va siempre entre `<documento>` y `</documento>` como contenido externo. Log: `trackflow.rfp_intake`
(una línea por nodo con el `ticket_id` y una por llamada al modelo con su duración).

## Persistencia (PostgreSQL / Supabase)

Tablas en `schema.py`, creadas por `create_all` al arrancar la API:

- `rfp_tickets`: `ticket_id`, `rfp_id`, `status`, `raw_pdf_path`, decisión del clasificador (`is_rfp`,
  `classification_confidence`, `classification_reason`), `synthesis`, `handoff`, `attempts`, `last_error`,
  `created_at`, `updated_at`.
- `rfp_metadata`: `client_name`, `client_country`, `currency`, `client_reference`, `services_requested`,
  `monthly_volume`, `deadline`, `budget_range`, `departments_needed`, métricas de legibilidad (`word_count`,
  `estimated_tokens`, `flesch_kincaid_grade`, `gunning_fog`, `flesch_reading_ease`) y `document_markdown`.
- `rfp_department_sections`: una fila por departamento activo con `key_aspects`, `requested_inputs` y
  `open_questions`. La Parte 2 rellena `draft_status`, `iterations`, `draft_content`, `evaluation_results` y
  `evaluation_history`; `approval_status`, `approver` y `approved_at` son de la Parte 3.

El grafo no escribe en la base de datos: `runner.py` guarda el resultado completo en una sola transacción.

`create_all` no altera tablas existentes: las columnas y estados de la Parte 2 están en
`migrations/001_response_generation.sql` (idempotente, sin borrar datos), que `schema.ensure_response_schema` aplica
en PostgreSQL al arrancar la API y al crear el engine del worker y de `scripts/`.

## Estados del ticket

| Estado | Parte | Cuándo |
| --- | --- | --- |
| `analizando` | 1 | Subida aceptada; conversión y agentes en curso (o reintentando tras un fallo, con `last_error`). |
| `descartado` | 1 | El clasificador decidió que no es una RFP; `classification_reason` explica por qué. |
| `analisis_completo` | 1 | El synthesizer terminó; metadatos, secciones y handoff están guardados. |
| `generando_borrador` | 2 | Los generadores escriben la primera versión de cada sección. |
| `en_evaluación` | 2 | El primer borrador entró en evaluación; sigue aquí durante el ciclo generador-evaluador. Con `response_handoff` guardado, todas las secciones pasaron y esperan a la Parte 3. |
| `needs_human_review` | 2 | Alguna sección agotó el límite de iteraciones; su último borrador y su `EvaluationResult` pasan igualmente a la Parte 3. |

## Contrato de handoff hacia la Parte 2 (`rfp_intake.handoff.v1`)

El enrutamiento es un campo en la base de datos, sin segundo API: la Parte 2 toma los tickets con
`status = 'analisis_completo'` y lee `rfp_tickets.handoff`:

```json
{
  "version": "rfp_intake.handoff.v1",
  "ticket_id": "…",
  "rfp_id": "…",
  "next_stage": "generando_borrador",
  "currency": "EUR",
  "client_country": "ES",
  "departments": ["warehouse", "reverse"],
  "workstreams": [
    {
      "department_id": "warehouse",
      "department_name": "Warehouse Operations",
      "responsible": "Ana Whitfield",
      "key_aspects": ["…"],
      "requested_inputs": ["…"],
      "open_questions": ["…"]
    }
  ],
  "summary": "…",
  "conflicts": []
}
```

El texto completo del documento está en `rfp_metadata.document_markdown` (se une por `rfp_id`): la Parte 2 no
vuelve a convertir el PDF.

## Decisiones de diseño

- **Departamento que no existe en el BRIEFING.** El orquestador puede proponerlo, pero `validate_plan` no crea un
  worker: lo deja en `out_of_scope` ("Departamento no reconocido …") y la UI lo muestra en "Fuera del alcance".
  Lo que pide el cliente y no cubre nadie (p. ej. la integración con su ERP) va al mismo sitio.
- **Qué recibe cada worker.** Metadatos compartidos, la tarea del orquestador y los párrafos literales que le
  asignó (por número); nunca el documento entero ni la salida de otro worker. Si falta una cifra (volumen
  mensual), no se estima: queda como pregunta abierta para el cliente.
- **Cuándo un documento "no es una RFP".** Cuando no es una petición de propuesta de un cliente a TrackFlow (el
  pitch de tarifas de un transportista, una factura, un CV). Un falso negativo pierde una venta sin que nadie lo
  vea, así que un "no" con confianza baja se acepta y se analiza; el motivo y la confianza quedan en el ticket y,
  si un descarte fue un error, se reabre con `scripts/rfp_intake.py reprocess <ticket_id> --force`.
- **Workers contradictorios.** Los datos compartidos (país, moneda, volumen, plazos) salen de los metadatos, no de
  los workers, y una cifra que no está en la RFP se descarta. Si aun así dos secciones chocan, el synthesizer las
  señala en `conflicts` sin resolverlas; el arbitraje es un nodo de la Parte 3.
- **Dónde corre el trabajo async.** En el worker de Celery (el mismo de la cola existente), nunca en la API. Si un
  intento falla, el ticket sigue en `analizando` con `attempts` y `last_error` y sin resultados a medias; la tarea
  se reintenta dos veces con backoff y, al agotarlas, va a la DLQ (`task_dead_letters`). Un ticket que ya no está en
  `analizando` no se vuelve a procesar. Si la cola no está disponible al subir, la API borra el ticket y el PDF y
  responde `503`: no queda un ticket que nadie va a procesar.

## Parte 2 — Generación y evaluación de respuestas

Cuando la tarea de la Parte 1 deja el ticket en `analisis_completo`, encola `rfp_intake.generate_responses`
(`services/tasks/rfp_intake.py`), que ejecuta `response_runner.generate_responses` en el worker de Celery.

### Entrada: el handoff de la Parte 1

Solo se procesan tickets en `analisis_completo` (o en `generando_borrador` / `en_evaluación` sin
`response_handoff`, para los reintentos) con un `handoff` `rfp_intake.handoff.v1`. Cada generador recibe los
metadatos compartidos (cliente, país, moneda, servicios, volumen, fecha límite, presupuesto, resumen y
contradicciones del synthesizer) y **solo el workstream de su departamento**. Nunca el PDF ni `document_markdown`.

### Grafo (`response_graph.py`)

```
START ─ Send por workstream ─▶ warehouse_section / lastmile_section / reverse_section (en paralelo) → END

<dept>_section (subgrafo por departamento):
START → retrieve_knowledge → <dept>_generator ─┬─▶ readability_evaluator ─┐
                                               ├─▶ relevance_evaluator  ──┼─▶ judge ─┬─ pasa → END (evaluacion_superada)
                                               └─▶ compliance_evaluator ─┘           ├─ falla y quedan iteraciones → <dept>_generator
                                                                                     └─ falla en la última → END (needs_human_review)
```

| Nodo | Módulo | Qué recibe | Qué decide el código |
| --- | --- | --- | --- |
| `retrieve_knowledge` | `generators.py` | Id del departamento | Busca en el RAG de la empresa sus tarifas/políticas y el SLA (opcional: si Qdrant no responde, sigue sin contexto y lo registra). |
| `<dept>_generator` | `generators.py` | Brief del handoff, fragmentos del RAG y, al reintentar, su borrador anterior + `feedback_for_generator` | Un generador por departamento con su propio alcance. Formato fijo de la sección y lineamientos del BRIEFING §5 en el prompt. |
| `readability_evaluator` | `evaluators.py` | Solo el borrador | `py-readability-metrics` sobre la prosa (sin tablas ni Markdown): 100-600 palabras y Flesch-Kincaid ≤ 14. |
| `relevance_evaluator` | `evaluators.py` | Borrador + `key_aspects` de su departamento | El modelo señala aspectos no respondidos por número; la lista sale del handoff, no del modelo. |
| `compliance_evaluator` | `evaluators.py` + `compliance.py` | Borrador + moneda | Las 5 reglas del BRIEFING §5 se comprueban en código; el revisor con modelo solo añade violaciones de `returns-min-48h` y `no-carrier-rates` citando texto literal del borrador. |
| `judge` | `evaluators.py` | Las tres claves de evaluación | `overall_pass`, `feedback_for_generator` concreto y siguiente paso según `max_iterations`. |

Los tres evaluadores corren en paralelo y cada uno escribe solo su clave del estado (`readability`, `relevance`,
`compliance`); `judge` es el único que las combina, así que no hay escrituras en conflicto. Cada departamento es una
rama independiente: uno que reintenta no retrasa a otro.

### Lineamientos del evaluador de cumplimiento (BRIEFING §5)

| `rule_id` | Regla | Comprobación |
| --- | --- | --- |
| `currency-by-country` | USD para EE. UU. y EUR para España, según `client_country`. | Hay importes en la moneda del país y ninguno en la otra. Sin país, falla: Ventas tiene que confirmarlo. |
| `on-time-sla` | Indicar el SLA de entrega a tiempo (%). | Una línea con `SLA`/`a tiempo` y un porcentaje. |
| `returns-min-48h` | Nunca prometer devoluciones en menos de 48 h. | En frases sobre devoluciones: plazos < 48 h (`24 horas`, `1 día`, `mismo día`, `menos de 48 horas`), salvo negados. Más el revisor con modelo. |
| `volume-discount-table` | Incluir una tabla de descuentos por volumen. | Tabla Markdown (cabecera, separador, ≥ 2 filas) que mencione descuento. |
| `no-carrier-rates` | No revelar tarifas negociadas con transportistas. | Un transportista (UPS, FedEx, DHL, MRW, SEUR…) en la misma línea que un importe o una "tarifa negociada". Más el revisor con modelo. |

### `EvaluationResult`

Se guarda en `rfp_department_sections.evaluation_results` (el último) y en `evaluation_history` (uno por
iteración, con su borrador):

```json
{
  "section_id": "<ticket_id>:reverse",
  "department_id": "reverse",
  "iteration": 1,
  "readability": {"pass": true, "score": 12.79, "details": "Legible: 242 palabras, Flesch-Kincaid 12.79.", "metrics": {}},
  "relevance": {"pass": true, "missing_aspects": [], "checked_aspects": 3},
  "compliance": {"pass": false, "rule_ids": ["returns-min-48h"], "violations": [{"rule_id": "returns-min-48h", "detail": "…", "evidence": "…", "source": "regla"}], "checked_rule_ids": ["currency-by-country", "on-time-sla", "returns-min-48h", "volume-discount-table", "no-carrier-rates"]},
  "overall_pass": false,
  "feedback_for_generator": "- Cumplimiento [returns-min-48h]: … Texto: \"…\". Cómo corregirlo: …"
}
```

### Límite de iteraciones y `needs_human_review`

`RFP_MAX_GENERATION_ITERATIONS` (por defecto 3; la meta del BRIEFING §3 es < 2 de media). Una sección que llega al
límite sin pasar conserva su último borrador y su `EvaluationResult`, queda en `needs_human_review` y va igualmente
en el handoff; el ticket pasa a `needs_human_review`. El resto de secciones no se ve afectado y nunca se descarta el
ticket. En el backoffice, la sección aparece como "Borrador provisional · requiere revisión humana" con los fallos de
su última evaluación.

### Progreso en tiempo real

El grafo no conoce la base de datos: informa por el `ProgressSink` de `config["configurable"]["progress"]`.
`DatabaseProgress` escribe en la fila de cada sección su estado (`generando_borrador`, `en_evaluación`,
`evaluacion_superada`, `needs_human_review`), iteración, borrador y evaluación en cuanto cambian, y adelanta el
ticket de `generando_borrador` a `en_evaluación`. La UI de `/rfps/<ticket_id>` lo consulta cada 4 s.

### Contrato de handoff hacia la Parte 3 (`rfp_intake.response_handoff.v1`)

En `rfp_tickets.response_handoff`:

```json
{
  "version": "rfp_intake.response_handoff.v1",
  "ticket_id": "…",
  "rfp_id": "…",
  "status": "en_evaluación | needs_human_review",
  "next_stage": "esperando_aprobación",
  "currency": "EUR",
  "client_country": "ES",
  "max_iterations": 3,
  "needs_human_review": ["reverse"],
  "sections": [
    {
      "department_id": "reverse",
      "department_name": "Reverse Logistics",
      "responsible": "Sofía Ramos",
      "draft_status": "needs_human_review",
      "needs_human_review": true,
      "iterations": 3,
      "draft_content": "## Reverse Logistics — Propuesta económica …",
      "evaluation_result": {"…": "EvaluationResult"}
    }
  ]
}
```

La Parte 2 no escribe estados de la Parte 3: `next_stage` solo indica a dónde va el ticket.

### Fallos

Como en la Parte 1: cualquier fallo de un agente deja `last_error` en el ticket, que no cambia de estado; la tarea
se reintenta dos veces con backoff (cada reintento vuelve a empezar la generación) y después va a la DLQ. Se reanuda
con `scripts/rfp_intake.py generate <ticket_id>`.

## Comandos

```bash
# Redis y worker (o `docker compose up -d redis worker`)
docker compose up -d redis
uv run --env-file .env celery -A services.tasks.celery_app worker --loglevel=INFO --queues=default,dead_letter --pool=solo
uv run --env-file .env uvicorn services.api.main:app --reload --port 8000
npm run dev:backoffice   # http://localhost:3002/rfps

# Grafo sobre un PDF local, sin base de datos
uv run --env-file .env python scripts/rfp_intake.py smoke <ruta.pdf>
# Reprocesar un ticket (p. ej. tras agotar los reintentos)
uv run --env-file .env python scripts/rfp_intake.py reprocess <ticket_id> [--force]
# Parte 2 de un ticket en analisis_completo (o que agotó los reintentos de la generación)
uv run --env-file .env python scripts/rfp_intake.py generate <ticket_id> [--max-iterations N]

# Pruebas (sin gateway ni Redis)
uv run pytest tests/pipelines/test_rfp_intake_agents.py tests/pipelines/test_rfp_intake_flow.py \
  tests/pipelines/test_rfp_response_agents.py tests/pipelines/test_rfp_response_flow.py tests/http/test_rfp_api.py
```
