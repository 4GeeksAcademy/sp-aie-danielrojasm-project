# Recepción y enrutamiento de RFPs (`rfp_intake`)

Parte 1 del flujo agéntico de propuestas. Ventas sube la RFP del cliente en PDF desde el backoffice y, sin leer el
documento original, ve qué le toca a cada departamento (Warehouse, Last Mile, Reverse Logistics) y a quién
pedírselo.

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
  `open_questions`. `draft_content`, `evaluation_results`, `approval_status`, `approver` y `approved_at` son de las
  Partes 2 y 3 y quedan vacías.

El grafo no escribe en la base de datos: `runner.py` guarda el resultado completo en una sola transacción.

## Estados del ticket (Parte 1)

| Estado | Cuándo |
| --- | --- |
| `analizando` | Subida aceptada; conversión y agentes en curso (o reintentando tras un fallo, con `last_error`). |
| `descartado` | El clasificador decidió que no es una RFP; `classification_reason` explica por qué. |
| `analisis_completo` | El synthesizer terminó; metadatos, secciones y handoff están guardados. |

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

# Pruebas (sin gateway ni Redis)
uv run pytest tests/pipelines/test_rfp_intake_agents.py tests/pipelines/test_rfp_intake_flow.py tests/http/test_rfp_api.py
```
