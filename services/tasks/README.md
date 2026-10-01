# `services/tasks` — cola de tareas asíncronas (Celery + Redis)

Saca de la API las operaciones largas. La API **encola** la tarea y responde `202` con un `task_id`. Un worker de
Celery, que es **otro proceso**, la ejecuta. El cliente consulta el estado en `GET /tasks/{task_id}`.

```text
Cliente → API (productor) → Redis (broker) → worker (consumidor) → Redis (resultado) → GET /tasks/{task_id}
```

| Archivo | Qué hace |
|---|---|
| `celery_app.py` | Instancia de Celery (broker y result backend = `REDIS_URL`), configuración y log de cada intento |
| `pipeline.py` | Tarea `reporting.run_weekly_performance`: pipeline semanal con reintentos y backoff |
| `dead_letter.py` | DLQ: cola `dead_letter`, tarea `tasks.record_dead_letter` y tabla `task_dead_letters` |
| `migrations/001_create_task_dead_letters.sql` | DDL de la DLQ para aplicarlo a mano en Supabase |

Ni el worker ni estos módulos importan FastAPI ni `services/api` (lo comprueba un test).

## Operación convertida: `POST /reporting/pipeline-runs`

Era el endpoint más lento de la API. Antes ejecutaba el flow de Prefect dentro del proceso de Uvicorn con
`BackgroundTasks`: unos 10 s solo para levantar Prefect, más extracción, transformación y carga contra Supabase (entre 12
y 24 s medidos). Mientras tanto ocupaba un worker de la API, y si la API se reiniciaba la corrida se perdía.

Ahora el endpoint:

1. Valida la semana y reserva la corrida `pending` en `reporting.pipeline_runs` (lock: devuelve `409` si ya hay una activa).
2. Encola `reporting.run_weekly_performance` con **solo identificadores**: `[run_id, week_start | null, triggered_by]`
   (142 bytes).
3. Responde `202 {"run_id", "task_id", "status": "pending", "week_start"}`.

Si Redis no responde, devuelve `503` y cierra la corrida como `failed`, así el lock no se queda tomado. Cuando Redis
vuelve, la API se recupera sola, sin reiniciarse. El 503 tarda unos 6–8 s en Windows: cada conexión a un puerto cerrado
tarda ~2 s y kombu reintenta durante `broker_connection_timeout` (3 s). En Linux el rechazo es inmediato.

El backend de resultados es `PublishOnlyRedisBackend`: al encolar no suscribe al productor al resultado. La suscripción
pub/sub por defecto se reintentaba más de un minuto con Redis caído y acababa en `RuntimeError`.

## Estados (`GET /tasks/{task_id}`, con bearer)

| Celery | `status` | `result` / `error` |
|---|---|---|
| `PENDING` | `pending` | En cola. Un id desconocido también sale `pending`: Celery no distingue los dos casos |
| `STARTED` | `started` | En un worker (`task_track_started`) |
| `RETRY` | `retry` | Falló y espera el siguiente intento; `error` lleva el último fallo |
| `SUCCESS` | `success` | `result`: `{"run_id", "status": "completed", "week_start", "attempts"}` |
| `FAILURE` / `REVOKED` | `failure` | `error`: clase y mensaje, sin URLs ni credenciales |

Con Redis caído, `GET /tasks/{task_id}` responde `503`.

## Reintentos, backoff y DLQ

- `max_retries = 3`: 1 ejecución + 3 reintentos. La espera es `TASKS_RETRY_BACKOFF_SECONDS × 2^n`: 30, 60 y 120 s por
  defecto. Nunca se reintenta en el acto.
- Cada intento fallido cierra su corrida como `failed`. El reintento reserva una corrida nueva, con `retry_of` apuntando a
  la anterior. Así `pipeline_runs` conserva la cadena completa y ningún intento deja el lock tomado.
- Al agotar los reintentos, la tarea publica un mensaje en la cola **`dead_letter`** y termina en `FAILURE`. El consumidor
  `tasks.record_dead_letter` guarda el fallo en **`task_dead_letters`**:

| Columna | Uso |
|---|---|
| `task_id` | id de Celery (único: una entrega doble no duplica) |
| `task_name` | `reporting.run_weekly_performance` |
| `attempts` | intentos ejecutados (4) |
| `error_type` / `error_message` | clase y primera línea, sin URLs ni SQL (la traza completa va al log) |
| `task_args` | `run_id` original, `week_start`, `triggered_by` y `last_run_id` |
| `failed_at` | momento del último fallo (UTC) |

Si la base de datos no responde, `record_dead_letter` se reintenta (hasta 5 veces). Si ni siquiera se puede publicar en la
cola, el fallo se escribe directamente; si tampoco se puede, queda un log `CRITICAL`.

Reglas de la configuración: ACK solo tras éxito (`task_acks_late` + `task_reject_on_worker_lost`), `prefetch = 1`, límite
blando de 20 min y duro de 25 min en el pipeline, y `visibility_timeout` de 2 h, mayor que el límite duro y que el backoff.

## Logs

Logger `trackflow.tasks`, una línea al empezar y otra al terminar cada intento:

```text
task_id=46d9… task=reporting.run_weekly_performance attempt=1 status=started
task_id=46d9… task=reporting.run_weekly_performance attempt=1 status=retry duration_ms=123 error=SimulatedFailureError(…)
task_id=46d9… task=reporting.run_weekly_performance attempt=4 status=failure duration_ms=38 error=… + traza
task_id=46d9… task=reporting.run_weekly_performance attempt=4 status=dead_letter registrada en task_dead_letters error=…
```

## Variables

| Variable | Uso |
|---|---|
| `REDIS_URL` | Broker y result backend. En local `redis://127.0.0.1:6379/0` (en Windows, `localhost` tarda ~2 s más) |
| `DOCKER_REDIS_URL` | La que usan la API, el worker y Flower dentro de Compose (`redis://redis:6379/0`) |
| `DATABASE_URL` | El worker ejecuta el pipeline y escribe la DLQ |
| `TASKS_RETRY_BACKOFF_SECONDS` | Base del backoff (30) |
| `TASKS_SIMULATE_FAILURE` | **Solo para demos.** Con `1`, el pipeline falla siempre antes del flow (para ver reintentos y DLQ). El worker lo avisa al arrancar |

## Cómo levantarlo y detenerlo

Con Docker Compose (desde la raíz):

```bash
docker compose up -d redis worker flower      # broker, worker y Flower (http://localhost:5555)
docker compose logs -f worker                 # logs de cada intento
docker compose stop worker                    # warm shutdown: termina la tarea en curso (hasta 2 min)
docker compose down                           # todo; los mensajes en cola persisten en el volumen redis-data
```

Sin Docker para el worker (Redis sí tiene que estar arriba):

```bash
uv run --env-file .env celery -A services.tasks.celery_app worker --loglevel=INFO --queues=default,dead_letter
# Windows: añadir --pool=solo (prefork no funciona en Windows). Ctrl+C = warm shutdown; dos veces = cold.
uv run --env-file .env celery -A services.tasks.celery_app flower --port=5555
```

Para demostrar un fallo: `TASKS_SIMULATE_FAILURE=1` (y, para no esperar 3,5 min, `TASKS_RETRY_BACKOFF_SECONDS=5`) en el
worker. Después, `POST /reporting/pipeline-runs` como admin: la tarea pasa por `retry` tres veces y acaba en `failure`, y
en Flower aparece también `tasks.record_dead_letter`.

Detener la API no detiene el worker. Detener el worker tampoco pierde mensajes: siguen en Redis (AOF activado y
`noeviction`) hasta que vuelve a arrancar. Si el worker muere a mitad de una tarea, el mensaje sin ACK vuelve a la cola.
