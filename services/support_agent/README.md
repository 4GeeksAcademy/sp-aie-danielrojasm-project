# `services/support_agent` — Agente de primera línea de CX (LangGraph)

Agente de LangGraph con dos fuentes: la base de conocimiento comercial (RAG de `data/pipelines/rag.py`, políticas
estables) y el gestor de incidencias (tool de solo lectura del servidor MCP `mcps/trackflow_tools`, datos operativos en
tiempo real). El propio agente decide
qué fuente necesita cada pregunta. Se monta en la API principal (`services/api/main.py`) y convive con
`/knowledge/query`.

Además tiene **memoria aprobada** (`memory/`, sobre Redis): propone recordar correcciones dentro de su respuesta y solo
las guarda si el usuario lo decide explícitamente en el turno siguiente. Diseño, política de lo que nunca se recuerda
y evidencias en [`docs/agent-memory/memory-design.md`](../../docs/agent-memory/memory-design.md).

Y un **harness de protección** (`guardrails/`, ver [Guardrails](#guardrails)): rechaza los cambios de instrucciones y el
uso como chatbot personal, reconduce el small talk, aísla el contenido de las fuentes externas y valida cada respuesta
antes de devolverla.

## Grafo

```mermaid
flowchart LR
  S((START)) --> RQ[receive_question]
  RQ -- pregunta vacía --> RJ[reject_question] --> E((END))
  RQ -- hay pregunta --> IG[input_guard]
  IG -- cambio de instrucciones, uso personal, pedido ajeno --> GR[guardrail_refusal] --> E
  IG -- se responde --> LP[load_pending_proposal]
  LP -- propuesta pendiente --> RP[resolve_proposal]
  LP -- small talk --> ST[small_talk_reply]
  LP -- ninguna --> M[recall_memory]
  RP -- el mensaje también pregunta algo --> M
  RP -- y es small talk --> ST
  RP -- solo respondía a la propuesta --> E
  M --> RT[route_question]
  RT -- cita tickets --> LT[lookup_tickets]
  RT -- sin tickets --> R[retrieve]
  LT -- también necesita la base de conocimiento --> R
  LT -- algún ticket confirmado --> G[generate_answer]
  LT -- ningún ticket confirmado --> TF[ticket_fallback]
  R -- hay contexto, tickets confirmados o memoria --> G
  R -- sin contexto, tickets sin confirmar --> TF
  R -- sin contexto, tickets ni memoria --> N[no_information]
  G --> OG[output_guard]
  N --> OG
  TF --> OG
  ST --> OG
  OG -- propuesta de memoria --> PM[propose_memory] --> E
  OG -- nada que recordar --> E
```

| Nodo | Responsabilidad | Escribe en el estado |
| --- | --- | --- |
| `receive_question` | Normaliza la pregunta | `question` |
| `reject_question` | Termina sin consultar nada si la pregunta está vacía | `error` |
| `input_guard` | Clasifica el mensaje (`guardrails/input_guard.py`) y registra la activación | `guardrail`, `guardrail_events` |
| `guardrail_refusal` | Rechazo fijo, sin memoria, tools ni modelo | `answer` |
| `small_talk_reply` | Una o dos frases del modelo, sin RAG ni tools (`small_talk.py`) | `answer` |
| `load_pending_proposal` | Propuesta de memoria del usuario pendiente en esta conversación (antes descarta las caducadas) | `pending_proposal` |
| `resolve_proposal` | Clasifica el mensaje frente a la propuesta (`approve`, `reject`, `edit`, `unrelated`), consolida si se aprueba y lo audita | `memory_decision`, `answer` o `question` |
| `recall_memory` | Entradas de la memoria aprobada relevantes para la pregunta (como mucho 5) | `memories` |
| `route_question` | Decide las fuentes (`routing.plan_route`) | `route` |
| `lookup_tickets` | Tool `get_ticket` (cliente MCP) por cada ticket de la pregunta | `tickets` |
| `retrieve` | `data.pipelines.rag.retrieve(question)` | `context` |
| `generate_answer` | Aísla el contenido externo y llama a `memory.self_evaluation.generate_reply(question, context)`: una sola llamada que devuelve la respuesta y `propuesta_memoria`, con el contexto recuperado, los tickets confirmados y la memoria recordada | `answer`, `memory_candidate`, `guardrail_events` |
| `ticket_fallback` | Respuesta honesta sin llamar al modelo: ningún ticket se pudo confirmar | `answer` |
| `no_information` | Respuesta fija sin contexto; el modelo solo auto-evalúa el mensaje (su texto no se usa) | `answer`, `memory_candidate` |
| `output_guard` | Valida la respuesta antes de devolverla (`guardrails/output_guard.py`) | `answer`, `guardrail_events` |
| `propose_memory` | Valida la propuesta (`memory.policy`), la deja pendiente y la pregunta al final de la respuesta | `memory_proposal`, `answer` |

Ningún nodo llama a `query()`: cada fuente se consulta una sola vez y queda en el trace. Un ticket que no se pudo
confirmar nunca llega al modelo; el agente lo avisa con un texto fijo y no inventa un estado.

**Estado (`state.py`):** `question`, `message`, `conversation_id`, `user_id`, `run_id`, `authorized_orders`,
`guardrail`, `guardrail_events` (se acumulan nodo a nodo), los campos de memoria
(`pending_proposal`, `memory_decision`, `memories`, `memory_candidate`, `memory_proposal`, `memory_notices`), `route`,
`tickets`, `context`, `answer`, `error`. Sin historial de conversación: lo único que une dos turnos es la propuesta
pendiente, que vive en Redis.

**Enrutado (`routing.py`):** el modelo de generación devuelve un JSON `{ticket_ids, needs_knowledge}`. Solo se aceptan
los números de ticket que aparecen en la pregunta, y sin tickets la pregunta va al RAG. Si el modelo falla o su JSON no
es válido, deciden las reglas (`route_by_rules`: referencias explícitas como "ticket 482" o "incidencia nº 17"). El
trace guarda quién decidió (`decided_by`).

**Compilación (`graph.py`):** el grafo se compila al importar el módulo, antes de cualquier corrida. Además de la
validación de LangGraph (aristas hacia nodos que no existen, falta de entrada), comprueba que cada nodo es alcanzable
desde START y llega a END. Cualquier fallo es un `AgentGraphError` con el motivo.

**Checkpointing:** `InMemorySaver`, un checkpoint por transición, con `thread_id` = `run_id`. Si un nodo falla, el hilo
se conserva y `runner.resume_run(run_id)` continúa desde el último checkpoint sin repetir los nodos terminados. Las
corridas completadas liberan su hilo; su historial queda en el trace.

## Tool de tickets (`tools/incidents.py`): cliente del servidor MCP

El agente no llama a la API de incidencias. `lookup_tickets` usa la tool `get_ticket_status` del servidor MCP
(`mcps/trackflow_tools`), cargada con `langchain-mcp-adapters` (`MultiServerMCPClient`, Streamable HTTP). Es el único
camino del agente hacia el gestor: la llamada HTTP directa que usaba antes se eliminó.

| | |
| --- | --- |
| Entrada | `TicketQuery(ticket_id: int > 0)` |
| Salida | `TicketLookup(ticket_id, outcome, ticket)`; `outcome` = `found`, `not_found`, `timeout` o `unavailable`; `ticket` = `id`, `title`, `description`, `status`, `category`, `origin`, `branch`, `created_at`, `updated_at` |
| Servidor | `MCP_SERVER_URL` (por defecto `http://127.0.0.1:8001/mcp`; en el contenedor `api`, `DOCKER_MCP_SERVER_URL` = `http://mcp:8001/mcp`); el agente solo carga `get_ticket_status` |
| Auth | Token OAuth `client_credentials` del cliente `support-agent` (`AGENT_OAUTH_CLIENT_ID`, `KEYCLOAK_AGENT_CLIENT_SECRET`), pedido al issuer `MCP_OAUTH_ISSUER` (en el contenedor `api`, `DOCKER_MCP_OAUTH_ISSUER` = `http://keycloak:8080/realms/trackflow`; el `iss` del token sigue siendo `KEYCLOAK_URL`). Solo tiene el scope `incidents:read`: el servidor le rechaza crear tickets, cambiar su estado o leer inventario (`INSUFFICIENT_SCOPE`) |
| Timeout | `INCIDENTS_TIMEOUT_SECONDS` = 4 s (token y llamada MCP) |
| Fallback | `NOT_FOUND` → `not_found`; timeout → `timeout`; servidor MCP o Keycloak caídos, sin credenciales, otro código de error o respuesta inválida → `unavailable`. Nunca lanza excepciones al grafo |

El enrutado entre RAG y tools no cambia: el nodo y su contrato son los mismos, solo cambia el camino hasta el gestor.

## Guardrails

El agente atiende consultas de CX de marcas (B2B) y destinatarios (B2C) en Estados Unidos y España. Su dominio es el
tracking de un envío, las políticas de devolución y SLAs de cada país y los procedimientos de incidencias. Cada tipo de
fallo tiene su propia capa; ninguna llama al modelo, así que los tests las prueban de forma determinista.

| Capa | Dónde | Qué hace | Tipo de fallo |
| --- | --- | --- | --- |
| System prompt seguro | `prompt.py` | Solo el mensaje de sistema da instrucciones. La consulta va en `<mensaje_usuario>` y las fuentes en `<contenido_externo>`, ambos en el mensaje del usuario. Declara dominio, small talk con redirección, lo prohibido y los datos que nunca se revelan | — |
| Guard de entrada | `guardrails/input_guard.py`, nodo `input_guard` | Rechaza cambios de instrucciones (también ofuscados o en inglés), uso como chatbot personal y pedidos que no son de la sesión; reconduce el small talk; avisa cuando se pide aplicar la política de otro país | `security` / `content` |
| Aislamiento del contenido externo | `guardrails/isolation.py`, nodo `generate_answer` | Quita etiquetas del prompt y frases con órdenes de los fragmentos del RAG, los tickets y la memoria | `security` |
| Guard de salida | `guardrails/output_guard.py`, nodo `output_guard` | Fuga de instrucciones (marca `PROMPT_CANARY`, etiquetas, trozos literales) → rechazo; correos, direcciones, coordenadas, ubicaciones internas de almacén, tarifas con transportistas y pedidos ajenos → frase retirada; falta la línea "Fuente:" o el small talk se alarga → se corrige | `security` / `content` / `structural` |
| Memoria | `memory/policy.py` (Parte 1) | Lo prohibido por el CONTEXT nunca se propone; un mensaje rechazado no llega a resolver una propuesta pendiente | `content` |

| Entrada | Comportamiento | Recorrido |
| --- | --- | --- |
| Pregunta de dominio | RAG / tools | `input_guard` → … → `generate_answer` → `output_guard` |
| Small talk o trivia | Respuesta breve + reconducción fija | `input_guard` → `load_pending_proposal` → `small_talk_reply` → `output_guard` |
| Tarea personal ajena al negocio | Rechazo + propósito del agente | `input_guard` → `guardrail_refusal` |
| Cambio de instrucciones / jailbreak | Rechazo firme, sin cumplir nada | `input_guard` → `guardrail_refusal` |
| Pedido que no es de la sesión | Rechazo por autorización | `input_guard` → `guardrail_refusal` |
| Política de otro país | Aviso fijo + respuesta con la del país real | `input_guard` → … → `output_guard` |

**Pedidos de la sesión:** `run_agent(authorized_orders=…)` recibe los pedidos de la sesión autenticada. Hoy ningún
modelo vincula pedidos con usuarios, así que `POST /agent/query` no pasa ninguno y toda consulta de un número de
pedido o tracking se rechaza por falta de autorización.

**Observabilidad:** cada activación escribe una línea en el log `trackflow.guardrails` (`guardrail`, `failure_type`,
`action`, `reason`, `run_id`, `conversation_id`; nunca el mensaje) y queda en `guardrail_events` del trace.
`GET /agent/guardrails/summary` (bearer) devuelve los contadores por capa, tipo de fallo y acción desde que arrancó la
API.

**Cómo se prueba:** `tests/pipelines/test_agent_guardrails.py` (determinista: capas como funciones y grafo con dobles
que fallan si un abuso llega a una fuente o al modelo) y los casos `context-*` y `small-talk-redirect` de
`data/eval/agent/eval-cases.json`, grabados contra el agente real.

## Traces

Cada corrida escribe `AGENT_TRACE_DIR/<run_id>.json` (por defecto `data/raw/agent_traces/`, ignorado por git), también
si falla: `sources_used` (fuentes consultadas en orden: `incidents_tool`, `rag`), nodos en orden con su salida y
duración, estado final, checkpoints y, si aplica, el nodo y el tipo de error. El formato está en `tracing.py`. El log
`trackflow.agent` deja una línea por corrida con las fuentes, el recorrido y la ruta del trace.

## Endpoint

`POST /agent/query` (bearer) con `{ "question": "..." }` → `{ "answer", "run_id" }`.

| Situación | Respuesta |
| --- | --- |
| Respuesta generada, sin información o ticket sin confirmar | 200 |
| Rechazo o reconducción de un guardrail | 200 con el texto del guardrail |
| Pregunta vacía (la decide el grafo) | 422 con el motivo |
| Qdrant, la colección o el gateway LLM no disponibles | 503 con la referencia `run_id` |
| Cualquier otro fallo de un nodo | 500 con la referencia `run_id`, sin traza |

## Evals

`data/eval/agent/eval-cases.json` define los casos (RAG, tool, ambos, ticket inexistente y gestor caído);
`scripts/record_agent_traces.py` graba sus traces reales en `data/eval/agent/traces/` (necesita Qdrant indexado, el
`.env`, Keycloak, la API y el servidor MCP en `MCP_SERVER_URL`), y los evals se ejecutan contra esos traces:

```bash
uv run python scripts/record_agent_traces.py
uv run pytest tests/pipelines/test_agent_evals.py -v
```

Tests unitarios: `tests/pipelines/test_agent_graph.py` (grafo y fallback), `tests/pipelines/test_agent_routing.py`
(enrutado), `tests/pipelines/test_incidents_tool.py` (tool), `tests/pipelines/test_agent_guardrails.py` (guardrails) y `tests/http/test_agent_api.py` (endpoint, con un caso de
extremo a extremo: agente → servidor MCP → gestor de incidencias).
