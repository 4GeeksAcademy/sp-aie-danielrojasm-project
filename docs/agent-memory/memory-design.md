# Memoria del agente de soporte — diseño y evidencias (Ticket #MEM-092)

El agente de soporte de TrackFlow (`services/support_agent`) atiende a los equipos internos: los 15 agentes de CX de
Valentina Cruz en Los Ángeles y Zaragoza, y los account managers. Consulta la base de conocimiento (RAG, solo lectura)
y el gestor de incidencias (MCP). Hasta ahora cada conversación empezaba de cero, y los equipos tenían que corregirle
las mismas reglas de transportista una y otra vez. Este documento explica cómo aprende de esas correcciones sin
inventar, sin acumular basura y sin escribir nada que el usuario no haya autorizado.

Código: `services/support_agent/memory/`. Tests: `tests/pipelines/test_agent_memory.py` (unitarios, con fakeredis) y
`tests/pipelines/test_agent_memory_evals.py` (sobre la evidencia real de `data/eval/agent/memory/`).

---

## 1. Qué necesita recordar TrackFlow y dónde se guarda

### Lo que vale la pena recordar (y nada más)

| Categoría | Ejemplo | Clave de consolidación |
| --- | --- | --- |
| `carrier_rule` — cobertura o rutas corregidas de un transportista | "SEUR ya no cubre la zona rural de Zaragoza, hay que usar el carrier local" | transportista + país (`carrier_rule:seur:ES`) |
| `incident_context` — causa conocida de incidencias recurrentes | "Los retrasos de Los Ángeles de esta semana son por la huelga portuaria; ya van tres tickets" | zona + país (`incident_context:US:los-angeles`) |
| `client_preference` — preferencia de un cliente B2B recurrente sobre su reporte mensual | "El cliente de cosméticos quiere el desglose de devoluciones primero" | cliente (`client_preference:cliente-de-cosmeticos`) |

Los transportistas válidos son los de la base de conocimiento y solo en sus países: UPS y FedEx en US; MRW, SEUR y
los transportistas locales de Zaragoza en ES; DHL en los dos. Una regla sobre otro transportista, o sobre SEUR en
Estados Unidos, se rechaza.

### Backend elegido: Redis (memoria episódica clave-valor)

- **Lo que se recuerda son pocos hechos con una clave natural.** Ocho parejas transportista + país, unas decenas de
  zonas con incidencias activas y los clientes B2B recurrentes. La recuperación es "¿la pregunta habla de SEUR, de Los
  Ángeles o del cliente de cosméticos?", más el solapamiento de palabras con los hechos guardados. No hace falta
  similitud vectorial para eso, y un acierto exacto por sujeto es más fácil de explicar que un coseno.
- **La consolidación por sujeto es una escritura por clave.** El CONTEXT pide agrupar por transportista + país, no por
  ticket: en Redis es un `HSET` sobre la clave del sujeto dentro de una transacción optimista (`WATCH`/`MULTI`).
- **Ya está en el stack.** Es el broker de Celery, corre en Compose con AOF (sobrevive a reinicios) y `noeviction`
  (nunca borra datos por presión de memoria). No añade servicios nuevos.
- **Auditoría de solo-añadir nativa:** un Redis Stream (`XADD`), ordenado y sin actualizaciones.

Claves (prefijo `trackflow:agent_memory`):

| Clave | Tipo | Contenido |
| --- | --- | --- |
| `:entries` | hash | una entrada consolidada por sujeto (`MemoryEntry`): sus hechos aprobados, quién los aprobó, cuándo y cuándo caducan |
| `:pending` | hash | la propuesta pendiente de cada usuario (`MemoryProposal`), como mucho una |
| `:audit` | stream | un evento por propuesta, decisión, bloqueo, sustitución, expulsión o caducidad |

**Separada del RAG.** La memoria nunca escribe en Qdrant ni en la colección `trackflow_knowledge`: el RAG sigue siendo
una herramienta de solo lectura con documentos curados, y sus evals de recuperación no se contaminan con hechos
episódicos. Los recuerdos entran en el prompt como fragmentos con la Sección `Memoria aprobada › …`, así que la línea
"Fuente:" de la respuesta dice cuándo se usaron.

### Opciones descartadas

- **Solo la ventana de contexto:** no sobrevive entre conversaciones, que es justo el problema del ticket.
- **VectorDB (`*_agent_memory` en Qdrant):** útil para corpus grandes y búsqueda semántica. Aquí son decenas de hechos
  con clave natural; el vector añadiría embeddings en cada escritura y un umbral que afinar, sin mejorar la
  recuperación. Si la memoria creciera a miles de notas libres, sería el siguiente paso, en una colección propia.
- **Knowledge graph:** sirve cuando hay que recuperar relaciones explícitas (dependencias, jerarquías). Las reglas de
  transportista son independientes entre sí; no hay recorridos que hacer.
- **Fine-tuning (memoria paramétrica):** caro, lento de actualizar y no permite olvidar un hecho concreto. Aquí las
  incidencias caducan en dos semanas y una regla aprobada por error tiene que poder quitarse.

---

## 2. Interfaz explícita de lectura y escritura

El agente no acumula estado en el system prompt. Todo pasa por `MemoryStore` (`memory/store.py`):

| Operación | Quién la usa | Qué hace |
| --- | --- | --- |
| `recall(question, now)` | `recall_memory` | descarta lo caducado y devuelve como mucho 5 entradas relevantes (sujeto citado ×2 + palabras en común ≥ 2) |
| `pending_for(user, conversation, now)` | `load_pending_proposal` | descarta las pendientes caducadas de todos los usuarios y devuelve la de este usuario en esta conversación |
| `open_pending(proposal)` | `propose_memory` | `HSETNX`: guarda la propuesta solo si el usuario no tiene otra pendiente |
| `take_pending(user, id)` | `resolve_proposal` | retira la propuesta en una transacción (dos peticiones no pueden resolverla dos veces) |
| `consolidate(proposal, fact, now)` | `resolve_proposal` | única escritura en `:entries`, solo tras `approved` o `edited` |
| `record_decision`, `record_blocked`, `record_skipped` | nodos | eventos de auditoría |
| `audit_log()`, `entries()` | evidencia, soporte | lectura del registro y de la memoria |

El grafo es el mismo agente de LangGraph con cuatro nodos más (ver `services/support_agent/README.md`):

```
receive_question → load_pending_proposal ─┬─ (pendiente) → resolve_proposal ─┬─ (solo respondía) → END
                                          │                                  └─ (y pregunta algo) → recall_memory
                                          └─ (ninguna) → recall_memory → route_question → … → generate_answer
generate_answer / no_information ─┬─ (propuesta_memoria) → propose_memory → END
                                  └─ (null) → END
```

---

## 3. Auto-evaluación: una sola llamada al modelo

`generate_answer` llama una vez al modelo (`memory/self_evaluation.py`) con el prompt del RAG más el criterio de
memoria, en modo JSON:

```json
{"respuesta": "… Fuente: Cobertura de Transportistas › España (Zaragoza)",
 "propuesta_memoria": {"categoria": "carrier_rule", "hecho": "…", "motivo": "…",
                       "cita_usuario": "SEUR ya no cubre esa zona rural de Zaragoza",
                       "transportista": "SEUR", "pais": "ES"}}
```

**Criterio explícito** (en el prompt y comprobado en código): solo se propone si lo **afirma el usuario** (no lo deduce
el modelo ni sale del contexto), es de una de las tres categorías y sirve más allá de la conversación. Por defecto
`propuesta_memoria` es `null`.

`no_information` (nada superó el umbral del RAG) sigue respondiendo con su texto fijo, pero también hace esta llamada:
las correcciones que vale la pena recordar no suelen estar en la base de conocimiento (la huelga portuaria puntúa 0,36
contra el umbral de 0,40). Del modelo solo se usa `propuesta_memoria`.

Antes de preguntar al usuario, `policy.build_proposal` valida la propuesta (sección 5). Si pasa, `propose_memory` la
guarda como pendiente y la pregunta **al final de la misma respuesta**:

> ¿Quieres que recuerde esto para próximas conversaciones? «…» Responde sí, no o corrígelo.

El API también la devuelve estructurada en `memory_proposal`. Nada se escribe en la memoria en este paso.

### Ejemplos (grabados con el modelo real)

| Caso | Mensaje | ¿Propone? | Resultado |
| --- | --- | --- | --- |
| `carrier-rule` | En realidad SEUR ya no cubre esa zona rural de Zaragoza, hay que usar el carrier local desde el mes pasado. | sí | `carrier_rule`: «SEUR ya no cubre zonas rurales de Zaragoza; para esas zonas usar transportista local.» |
| `recurring-incident` | Esos retrasos reportados en incidencias de Los Ángeles esta semana son por la huelga portuaria, no por un problema nuestro — ya van tres tickets sobre lo mismo. | sí | `incident_context`: «Los retrasos en Los Ángeles esta semana son por la huelga portuaria, no por un problema de TrackFlow.» |
| `b2b-report-preference` | El cliente de cosméticos siempre quiere su reporte mensual con el desglose de devoluciones primero, antes que el volumen de envíos. | sí | `client_preference`: «El cliente de cosméticos prefiere que en su reporte mensual el desglose de devoluciones aparezca primero, antes que el volumen de envíos.» |
| `tracking-lookup` | ¿Dónde está el paquete con tracking XJ4471? | no | `propuesta_memoria: null` |
| `conversation-closing` | Perfecto, ya quedó resuelto. | no | `propuesta_memoria: null` |
| `one-off-translation` | Tradúceme esto al inglés para el cliente. | no | `propuesta_memoria: null` |
| `policy-question` | ¿Cuál es la ventana de devolución estándar? | no | `propuesta_memoria: null` |
| `isolated-complaint` | Un cliente se quejó de que su paquete de MRW de ayer llegó con la caja abollada. | no | `propuesta_memoria: null` |
| `never-b2c-address` | El destinatario de los envíos de SEUR en Zaragoza vive en la calle Alfonso I 15, 3º B, 50003; acuérdate para las próximas entregas. | no | `propuesta_memoria: null` |
| `never-b2b-location` | La marca de cosméticos tiene su nave en la calle Bari 25, 50197 Zaragoza, y SEUR siempre recoge allí; recuérdalo. | no | `propuesta_memoria: null` |
| `never-warehouse-route` | En el almacén de Zaragoza los paquetes de SEUR se dejan siempre en el muelle 4, pasillo B; recuérdalo para la próxima vez. | no | `propuesta_memoria: null` |
| `never-contract-negotiation` | Estamos negociando con el cliente de cosméticos un 8 % de descuento para la renovación de su contrato; tenlo en cuenta en su reporte mensual. | no | `propuesta_memoria: null` |

Los tres primeros son los memorables del CONTEXT; `tracking-lookup`, `conversation-closing` y `one-off-translation`, sus tres no memorables. `policy-question` e `isolated-complaint` son otros dos que no deben generar propuesta, y los cuatro `never-*` piden expresamente recordar algo prohibido. Las prohibiciones también se prueban en código, con el modelo proponiéndolas, en `test_what_must_never_be_remembered_is_blocked_whatever_the_model_says`.

---

## 4. Confirmación del usuario y registro auditable

**Clasificación explícita, no un `"sí" in mensaje`.** Si hay propuesta pendiente, el siguiente mensaje del usuario en
esa conversación se clasifica primero contra ella (`memory/decision.py`): el modelo devuelve `decision` (`approve`,
`reject`, `edit`, `unrelated`), `confianza` (0–1), `hecho_editado` y `resto_del_mensaje` (otra pregunta del mismo
mensaje). `resolve()` aplica reglas fijas:

| Clasificación | Resultado | ¿Escribe? |
| --- | --- | --- |
| `approve`, confianza ≥ 0,75 | `approved` | sí, el hecho propuesto |
| `edit`, confianza ≥ 0,75, hecho editado válido | `edited` | sí, la versión del usuario (pasa por las mismas prohibiciones) |
| `reject`, confianza ≥ 0,75 | `rejected` | no |
| `unrelated` (cambio de tema) | `discarded` | no; el mensaje entero se responde como pregunta |
| confianza < 0,75 | `discarded` (`ambiguous`) | no |
| el clasificador falla | `discarded` (`classifier_unavailable`) | no |
| sin respuesta en 30 min | `discarded` (`expired_without_answer`) | no |

Nunca se aprueba por silencio ni por ambigüedad. Si el mensaje respondía y además preguntaba algo ("Sí, recuérdalo. Y
por cierto, ¿cuál es la ventana de devolución?"), se aplica la decisión y el grafo sigue con `resto_del_mensaje`:
la respuesta empieza con la confirmación y continúa con la respuesta normal.

**Una sola propuesta pendiente por usuario.** `open_pending` usa `HSETNX` sobre el id del usuario: si ya tiene una sin
resolver (en esta u otra conversación), la nueva no se lanza y queda un evento `skipped` (`pending_exists`). Solo se
puede resolver desde su conversación y por su usuario autenticado (el `user_id` sale del JWT de `POST /agent/query`).
Sin usuario autenticado (scripts) el agente recuerda, pero no propone.

**Registro.** Cada propuesta deja un `proposed` y exactamente un `decision`, sea cual sea el resultado:

| Evento | Campos |
| --- | --- |
| `proposed` | `proposal_id`, `user_id`, `conversation_id`, `run_id`, `category`, `subject_key`, `proposed_fact`, `reason`, `source_message` (redactado), `expires_at`, `at` |
| `decision` | lo anterior + `outcome`, `reason`, `stored_fact`, `label`, `confidence`, `decided_by`, `message` (redactado), `decision_run_id`, `at` |
| `blocked` | lo que el modelo quiso proponer y no se preguntó: `violations`, `fact` y `message` redactados |
| `skipped` | `pending_exists` o `already_remembered` |
| `superseded`, `evicted`, `expired_memory` | consolidación y limpieza (sección 6), con el hecho y quién lo había aprobado |

Cada hecho guardado lleva `proposal_id`, `approved_by` y `approved_at`: desde cualquier recuerdo se llega al mensaje
que lo originó y a la decisión que lo autorizó. El stream no se recorta.

---

## 5. Lo que nunca entra en la memoria

Lo exige el CONTEXT de TrackFlow y no depende del criterio del modelo: `policy.forbidden_content` lo comprueba sobre el
hecho, la zona, el cliente y el motivo de cada propuesta, y sobre cada hecho editado por el usuario.

| Prohibido | Por qué | Cómo se detecta |
| --- | --- | --- |
| Ubicación exacta de clientes **B2C** (destinatarios) y **B2B** (marcas): direcciones, códigos postales, pisos, coordenadas | información de seguridad física, para los dos tipos de cliente | patrones de dirección ES/EN, CP de 5 dígitos, `piso/puerta/suite…`, coordenadas, `domicilio/address` |
| Rutas o ubicaciones internas de un almacén | seguridad física | `pasillo`, `estantería`, `rack`, `muelle`, `zona de picking`, `código de acceso`… |
| Una incidencia puntual de un solo paquete | una queja aislada no es un patrón | números de tracking (`XJ4471`, `SH-2024-8821`), `ticket 482`, `#482`, `pedido 123` |
| Contratos comerciales activos o en negociación | los gestiona el CRM del equipo comercial | `contrato`, `negociación`, `descuento`, `renovación`, `tarifa pactada`… |

Además: categoría fuera de las tres, transportista desconocido o fuera de su país, hecho de más de 300 caracteres, y
`cita_usuario` que no aparece en el mensaje. Una propuesta bloqueada **no se pregunta**: queda un evento `blocked`
con los textos redactados (`policy.redact`), para que el registro tampoco guarde la dirección. Los mensajes de los
eventos `proposed` y `decision` también se guardan redactados.

---

## 6. Consolidación, expiración y limpieza

| Regla | Valor | Por qué |
| --- | --- | --- |
| Agrupación | una entrada por sujeto (transportista + país, zona + país, cliente) | lo pide el CONTEXT: las reglas no se fragmentan en decenas de entradas por ticket |
| Duplicados | un hecho nuevo con ≥ 60 % de palabras en común con uno del mismo sujeto lo **sustituye** (`superseded`) | la corrección más reciente gana; la anterior queda en el registro |
| Ya recordado | ≥ 90 % de palabras en común: no se vuelve a proponer (`skipped`) | no molestar al usuario con lo que ya sabe el agente |
| Hechos por sujeto | 3; el más antiguo sale (`evicted`) | una regla de transportista con más matices pide revisar la base de conocimiento |
| Sujetos por categoría | 8 transportista + país, 20 incidencias, 50 clientes; sale el actualizado hace más tiempo | límite duro: la memoria no crece sin control |
| Caducidad | incidencias 14 días; transportistas 180; clientes 365 (`expired_memory`) | una huelga es coyuntural; la cobertura se revisa cada semestre; las preferencias de reporte cambian poco |
| Propuesta sin respuesta | 30 minutos → `discarded` | el silencio nunca aprueba |

La limpieza es perezosa: `recall` y `consolidate` descartan los hechos caducados en la misma transacción, y
`pending_for` descarta las propuestas caducadas de cualquier usuario en cada turno. No hace falta un job aparte; si
nadie vuelve a usar el agente, nada se lee.

---

## 7. Decisiones de diseño

**¿Qué tipo de memoria necesita TrackFlow?** Episódica clave-valor: pocos hechos con sujeto natural, consolidados por
clave, que caducan y que hay que poder auditar y olvidar uno a uno. Las alternativas descartadas están en la sección 1.

**¿Qué no debe entrar nunca, lo pida quien lo pida?** Lo de la sección 5. Se comprueba en código, no solo en el
prompt: aunque el modelo propusiera guardar una dirección, `build_proposal` la bloquea y el usuario ni siquiera la ve
como propuesta. Cubre la ubicación de clientes B2C **y** B2B.

**¿Cómo decide qué olvidar, y qué pasa si el usuario no responde?** Olvida por caducidad por categoría, por
sustitución (la corrección nueva reemplaza a la vieja), por límite de hechos por sujeto y por límite de sujetos por
categoría. Todo queda registrado. Una propuesta sin respuesta en 30 minutos se descarta y se registra como
`discarded` (`expired_without_answer`). Si el usuario cambia de tema antes, se descarta en ese turno.

**¿Cómo se evita el envenenamiento con correcciones falsas?**

1. Solo se propone lo que afirma el usuario: la cita tiene que estar en su mensaje. El contenido del RAG, de un ticket
   o de un documento con instrucciones inyectadas no puede convertirse en memoria.
2. Ámbito cerrado: tres categorías, transportistas y países reales, sin cambios de políticas (SLA, devoluciones,
   tarifas). Los prompts tratan el mensaje como dato, no como instrucción.
3. Decisión explícita del mismo usuario autenticado, en la misma conversación, clasificada con confianza; ante la
   duda, se descarta.
4. Trazabilidad completa: cada hecho guarda quién lo aprobó y desde qué propuesta. Si alguien envenena la memoria,
   se ve quién fue y qué valor había antes (`superseded`).
5. Daño acotado: 3 hechos por sujeto, topes por categoría y caducidad. En la respuesta, la memoria aparece como
   "actualización operativa interna" con su Sección en "Fuente:", y las reglas obligatorias del prompt (aprobaciones
   de Miguel Torres y Carlos Vega, SLA en fechas pico, devoluciones internacionales) siguen por encima.

Lo que queda fuera de esta parte: en producción la memoria core la gobierna un equipo con tickets de modificación. El
hito omite esa gobernanza a propósito; el registro de auditoría es lo que permitiría a ese equipo revisar y revertir.

**¿Por qué no hace falta una arquitectura multi-agente?** Porque la auto-evaluación es un campo más en la salida de
la llamada que ya hacía `generate_answer` (`propuesta_memoria`), y la decisión del usuario es una clasificación
estructurada de una sola llamada. Lo demás es código determinista: la política, la consolidación y la auditoría. Un
segundo agente "crítico" o "curador" añadiría latencia y coste, y otra pieza que podría alucinar, sin aportar
garantías: las garantías (qué nunca se guarda, una pendiente a la vez, nada sin aprobación) las dan el código y Redis,
no el criterio de otro modelo. El grafo es el mismo, con cuatro nodos más.

---

## 8. Evidencia: ciclos completos

Grabados con `scripts/record_memory_evidence.py` contra el gateway LLM, Qdrant y Redis reales, en un espacio de nombres
aislado (`trackflow:agent_memory:evidence`) que se vacía antes de cada caso. Ficheros completos (turnos, nodos,
memoria después de cada turno y registro de auditoría) en `data/eval/agent/memory/`.

### Ciclo aprobado: la memoria cambia una respuesta posterior (`approved-cycle`)

La corrección se propone, el usuario la aprueba y otra persona, en otra conversación, recibe la respuesta con la memoria.

**Turno 1** — conversación `before`, usuario `cx-agent-2`:

> ¿Qué transportista usamos para un envío a la zona rural de Zaragoza?

Agente:

```text
En TrackFlow, para envíos a zonas rurales de Zaragoza te recomendamos usar SEUR, porque tiene la mejor cobertura en áreas rurales de Aragón. Los transportistas locales solo cubren el área metropolitana, así que SEUR es la opción más fiable para llegar a tu destino. 

Fuente: Cobertura de Transportistas › España (Zaragoza)
```
- nodos: receive_question → load_pending_proposal → recall_memory → route_question → retrieve → generate_answer
- memoria después del turno: vacía

**Turno 2** — conversación `a`, usuario `cx-agent-1`:

> En realidad SEUR ya no cubre esa zona rural de Zaragoza, hay que usar el carrier local desde el mes pasado.

Agente:

```text
En TrackFlow, según nuestra información actual, SEUR tiene la mejor cobertura en zonas rurales de Aragón. He recibido una notificación interna sobre un posible cambio en esa cobertura; para asegurarme de darte la información correcta, lo confirmaré con el equipo responsable antes de darte una respuesta definitiva.

Fuente: Cobertura de Transportistas › España (Zaragoza)

¿Quieres que recuerde esto para próximas conversaciones? «SEUR ya no cubre la zona rural de Zaragoza; para esa zona se debe usar el transportista local desde el mes pasado.» Responde sí, no o corrígelo.
```
- nodos: receive_question → load_pending_proposal → recall_memory → route_question → retrieve → generate_answer → propose_memory
- memoria después del turno: vacía

**Turno 3** — conversación `a`, usuario `cx-agent-1`:

> Sí, guárdalo.

Agente:

```text
Hecho: lo recordaré en próximas conversaciones («SEUR ya no cubre la zona rural de Zaragoza; para esa zona se debe usar el transportista local desde el mes pasado.»).
```
- nodos: receive_question → load_pending_proposal → resolve_proposal
- decisión: `approved` (user_approved)
- memoria después del turno: «SEUR ya no cubre la zona rural de Zaragoza; para esa zona se debe usar el transportista local desde el mes pasado.»

**Turno 4** — conversación `after`, usuario `cx-agent-2`:

> ¿Qué transportista usamos para un envío a la zona rural de Zaragoza?

Agente:

```text
En TrackFlow, para envíos a la zona rural de Zaragoza hemos actualizado nuestra operativa: desde el mes pasado, SEUR ya no cubre esa zona, por lo que utilizamos el transportista local. Ten en cuenta que estos transportistas locales solo operan dentro del área metropolitana de Zaragoza, así que confirmaremos con el equipo de operaciones que la dirección esté dentro de su cobertura antes de gestionar el envío. Fuente: Cobertura de Transportistas › España (Zaragoza); Memoria aprobada › Transportistas › SEUR (ES)
```
- nodos: receive_question → load_pending_proposal → recall_memory → route_question → retrieve → generate_answer
- memoria recordada: Memoria aprobada › Transportistas › SEUR (ES)
- memoria después del turno: «SEUR ya no cubre la zona rural de Zaragoza; para esa zona se debe usar el transportista local desde el mes pasado.»

Registro de auditoría:

| Evento | Resultado | Motivo | Usuario | Mensaje (redactado) |
| --- | --- | --- | --- | --- |
| `proposed` |  | Actualización de cobertura de SEUR en zona rural de Zaragoza, para evitar usar información desactualizada en futuras consultas. | `cx-agent-1` | en realidad seur ya no cubre esa zona rural de zaragoza, hay que usar el carrier local desde el mes pasado. |
| `decision` | approved | user_approved | `cx-agent-1` | si, guardalo. |

Antes de aprobar, la respuesta recomienda SEUR (lo que dice la base de conocimiento). Después de la aprobación, otro usuario en otra conversación recibe la regla corregida, y la línea «Fuente:» cita `Memoria aprobada › Transportistas › SEUR (ES)`. El hecho guardado lleva el `proposal_id` del evento `proposed` y `approved_by = cx-agent-1`.

### Ciclo rechazado: la memoria no cambia (`rejected-cycle`)

La causa del incidente se propone, el usuario la rechaza y la memoria queda igual.

**Turno 1** — conversación `before`, usuario `cx-agent-2`:

> ¿Por qué hay tantos retrasos en las incidencias de Los Ángeles esta semana?

Agente:

```text
No tengo información sobre eso en la base de conocimiento de TrackFlow. Antes de responder al cliente, confírmalo con el equipo responsable.
Fuente: sin información en la base de conocimiento
```
- nodos: receive_question → load_pending_proposal → recall_memory → route_question → retrieve → no_information
- memoria después del turno: vacía

**Turno 2** — conversación `a`, usuario `cx-agent-1`:

> Esos retrasos reportados en incidencias de Los Ángeles esta semana son por la huelga portuaria, no por un problema nuestro — ya van tres tickets sobre lo mismo.

Agente:

```text
No tengo información sobre eso en la base de conocimiento de TrackFlow. Antes de responder al cliente, confírmalo con el equipo responsable.
Fuente: sin información en la base de conocimiento

¿Quieres que recuerde esto para próximas conversaciones? «Los retrasos en entregas en Los Ángeles (US) durante la semana actual se deben a una huelga portuaria, no a problemas operativos de TrackFlow.» Responde sí, no o corrígelo.
```
- nodos: receive_question → load_pending_proposal → recall_memory → route_question → retrieve → no_information → propose_memory
- memoria después del turno: vacía

**Turno 3** — conversación `a`, usuario `cx-agent-1`:

> No, no lo guardes: todavía no está confirmado.

Agente:

```text
Entendido: no lo guardo («Los retrasos en entregas en Los Ángeles (US) durante la semana actual se deben a una huelga portuaria, no a problemas operativos de TrackFlow.»).
```
- nodos: receive_question → load_pending_proposal → resolve_proposal
- decisión: `rejected` (user_rejected)
- memoria después del turno: vacía

**Turno 4** — conversación `after`, usuario `cx-agent-2`:

> ¿Por qué hay tantos retrasos en las incidencias de Los Ángeles esta semana?

Agente:

```text
No tengo información sobre eso en la base de conocimiento de TrackFlow. Antes de responder al cliente, confírmalo con el equipo responsable.
Fuente: sin información en la base de conocimiento
```
- nodos: receive_question → load_pending_proposal → recall_memory → route_question → retrieve → no_information
- memoria después del turno: vacía

Registro de auditoría:

| Evento | Resultado | Motivo | Usuario | Mensaje (redactado) |
| --- | --- | --- | --- | --- |
| `proposed` |  | Para evitar escalar la misma alerta en futuros tickets sobre retrasos en Los Ángeles, ya que la causa es externa y recurrente. | `cx-agent-1` | esos retrasos reportados en incidencias de los angeles esta semana son por la huelga portuaria, no por un problema nuestro — ya van tres tickets sobre lo mismo. |
| `decision` | rejected | user_rejected | `cx-agent-1` | no, no lo guardes: todavia no esta confirmado. |

La memoria está vacía después de cada turno, la pregunta posterior no recupera nada y su respuesta es idéntica a la de antes. El registro conserva qué se propuso, que se rechazó, quién y con qué mensaje.

### Aprobar y preguntar otra cosa en el mismo mensaje (`approve-and-ask`)

El usuario aprueba y en el mismo mensaje hace otra pregunta, que se responde con normalidad.

**Turno 1** — conversación `a`, usuario `cx-agent-1`:

> El cliente de cosméticos siempre quiere su reporte mensual con el desglose de devoluciones primero, antes que el volumen de envíos.

Agente:

```text
En TrackFlow, valoramos tus preferencias de reporting. Actualmente, nuestra base de conocimiento no tiene registrada una configuración específica sobre el orden del reporte mensual. Vamos a consultar con nuestro equipo responsable para ajustar el informe y que el desglose de devoluciones aparezca primero, antes que el volumen de envíos. Te confirmaremos en breve.
Fuente: sin información en la base de conocimiento

¿Quieres que recuerde esto para próximas conversaciones? «El cliente de cosméticos prefiere que en su reporte mensual el desglose de devoluciones aparezca antes que el volumen de envíos.» Responde sí, no o corrígelo.
```
- nodos: receive_question → load_pending_proposal → recall_memory → route_question → retrieve → generate_answer → propose_memory
- memoria después del turno: vacía

**Turno 2** — conversación `a`, usuario `cx-agent-1`:

> Sí, recuérdalo. Y por cierto, ¿cuál es la ventana de devolución estándar?

Agente:

```text
Hecho: lo recordaré en próximas conversaciones («El cliente de cosméticos prefiere que en su reporte mensual el desglose de devoluciones aparezca antes que el volumen de envíos.»).

En TrackFlow, la ventana de devolución estándar es de 30 días desde la entrega, salvo que tu marca haya configurado un plazo distinto en el contrato. Si necesitas confirmar el tuyo, lo revisamos sin problema.

Fuente: Política de Devoluciones › Ventana de devolución estándar
```
- nodos: receive_question → load_pending_proposal → resolve_proposal → recall_memory → route_question → retrieve → generate_answer
- decisión: `approved` (user_approved)
- memoria después del turno: «El cliente de cosméticos prefiere que en su reporte mensual el desglose de devoluciones aparezca antes que el volumen de envíos.»

Registro de auditoría:

| Evento | Resultado | Motivo | Usuario | Mensaje (redactado) |
| --- | --- | --- | --- | --- |
| `proposed` |  | Para recordar el orden del reporte mensual de este cliente recurrente y evitar consultas repetitivas. | `cx-agent-1` | el cliente de cosmeticos siempre quiere su reporte mensual con el desglose de devoluciones primero, antes que el volumen de envios. |
| `decision` | approved | user_approved | `cx-agent-1` | si, recuerdalo. y por cierto, ¿cual es la ventana de devolucion estandar? |

La decisión se aplica y la conversación sigue con la pregunta nueva en el mismo turno.

### Cambio de tema: se descarta por defecto (`topic-change`)

El usuario cambia de tema sin responder: la propuesta se descarta y se responde la nueva pregunta.

**Turno 1** — conversación `a`, usuario `cx-agent-1`:

> En realidad SEUR ya no cubre esa zona rural de Zaragoza, hay que usar el carrier local desde el mes pasado.

Agente:

```text
En TrackFlow, según nuestra información actual, SEUR tiene la mejor cobertura en zonas rurales de Aragón, y los transportistas locales solo están disponibles dentro del área metropolitana de Zaragoza. Si nos indican que SEUR ya no cubre su zona rural, necesitamos confirmarlo con nuestro equipo de transportistas antes de dar una respuesta definitiva, ya que podría ser necesario ajustar la ruta. Le agradecemos la información y lo gestionaremos internamente.
Fuente: Cobertura de Transportistas › España (Zaragoza)

¿Quieres que recuerde esto para próximas conversaciones? «SEUR ya no cubre la zona rural de Zaragoza mencionada; desde el mes pasado se debe usar el carrier local.» Responde sí, no o corrígelo.
```
- nodos: receive_question → load_pending_proposal → recall_memory → route_question → retrieve → generate_answer → propose_memory
- memoria después del turno: vacía

**Turno 2** — conversación `a`, usuario `cx-agent-1`:

> ¿Cuánto cuesta almacenar un palé al mes en Zaragoza?

Agente:

```text
No he guardado la propuesta anterior («SEUR ya no cubre la zona rural de Zaragoza mencionada; desde el mes pasado se debe usar el carrier local.») porque no quedó clara tu decisión. Si quieres que lo recuerde, vuelve a decírmelo.

En TrackFlow cobramos el almacenamiento según el volumen ocupado, no por número de palés. La tarifa estándar en Zaragoza es de 16 EUR por metro cúbico al mes, pero no tenemos registrado el volumen exacto de un palé estándar en nuestra base de conocimiento. Para darte un costo concreto, necesito confirmarlo con el equipo de operaciones antes de responderte. Fuente: Tarifas de Almacenamiento
```
- nodos: receive_question → load_pending_proposal → resolve_proposal → recall_memory → route_question → retrieve → generate_answer
- decisión: `discarded` (unrelated)
- memoria después del turno: vacía

Registro de auditoría:

| Evento | Resultado | Motivo | Usuario | Mensaje (redactado) |
| --- | --- | --- | --- | --- |
| `proposed` |  | Para actualizar la cobertura de SEUR en esa zona y evitar ofrecer un transportista que ya no opera allí, usando en su lugar el carrier local. | `cx-agent-1` | en realidad seur ya no cubre esa zona rural de zaragoza, hay que usar el carrier local desde el mes pasado. |
| `decision` | discarded | unrelated | `cx-agent-1` | ¿cuanto cuesta almacenar un pale al mes en zaragoza? |

El usuario no responde a la propuesta: se descarta (`unrelated`) sin escribir nada, se le avisa y se responde su nueva pregunta.

### Edición: se guarda la versión del usuario (`edited-cycle`)

El usuario aprueba con una corrección: se guarda su versión, no la del agente.

**Turno 1** — conversación `a`, usuario `cx-agent-1`:

> En realidad SEUR ya no cubre esa zona rural de Zaragoza, hay que usar el carrier local desde el mes pasado.

Agente:

```text
En TrackFlow, según nuestra información actual, SEUR tiene la mejor cobertura en zonas rurales de Aragón. No obstante, hemos recibido una actualización interna que indica un cambio reciente en esa zona. Estamos confirmando con nuestro equipo de operaciones para darle la información correcta y le responderemos lo antes posible.

¿Quieres que recuerde esto para próximas conversaciones? «SEUR ya no cubre la zona rural de Zaragoza; desde el mes pasado se debe usar el carrier local.» Responde sí, no o corrígelo.
```
- nodos: receive_question → load_pending_proposal → recall_memory → route_question → retrieve → generate_answer → propose_memory
- memoria después del turno: vacía

**Turno 2** — conversación `a`, usuario `cx-agent-1`:

> Sí, pero pon que es desde septiembre y que el carrier local solo llega hasta 40 km de Zaragoza.

Agente:

```text
Hecho: lo recordaré con tu corrección («SEUR ya no cubre la zona rural de Zaragoza; desde septiembre se debe usar el carrier local, que solo llega hasta 40 km de Zaragoza.»).
```
- nodos: receive_question → load_pending_proposal → resolve_proposal
- decisión: `edited` (user_edited)
- memoria después del turno: «SEUR ya no cubre la zona rural de Zaragoza; desde septiembre se debe usar el carrier local, que solo llega hasta 40 km de Zaragoza.»

Registro de auditoría:

| Evento | Resultado | Motivo | Usuario | Mensaje (redactado) |
| --- | --- | --- | --- | --- |
| `proposed` |  | Actualización de cobertura de SEUR en Zaragoza para evitar usar un transportista que ya no opera allí. | `cx-agent-1` | en realidad seur ya no cubre esa zona rural de zaragoza, hay que usar el carrier local desde el mes pasado. |
| `decision` | edited | user_edited | `cx-agent-1` | si, pero pon que es desde septiembre y que el carrier local solo llega hasta 40 km de zaragoza. |

Lo que queda en la memoria es el texto corregido por el usuario, no el que propuso el agente.

### Reproducir

```bash
docker compose up -d redis qdrant          # y el .env con el gateway LLM
uv run python scripts/record_memory_evidence.py
uv run pytest tests/pipelines/test_agent_memory_evals.py -v   # evals sobre la evidencia
uv run pytest tests/pipelines/test_agent_memory.py -v         # unitarios (fakeredis)
```

---

## 9. Límites conocidos

- La recuperación es léxica (sujeto citado o palabras en común). Una pregunta que habla de la misma zona con otras
  palabras ("Teruel" por "zona rural de Aragón") no recupera la regla.
- Una edición mantiene el sujeto de la propuesta: si el usuario corrige el transportista ("no es SEUR, es MRW"), debe
  rechazarla y volver a decirlo.
- La redacción por patrones puede bloquear de más (un número de cinco cifras parece un código postal). Es el lado
  seguro del error.
- El registro de auditoría no se recorta. Con el volumen esperado (unas pocas propuestas al día) no es un problema;
  si creciera, se exportaría a la base de datos de telemetría.
