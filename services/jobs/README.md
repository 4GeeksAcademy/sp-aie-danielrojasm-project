# `services/jobs` — jobs en segundo plano

Control de estado de los jobs que corren fuera de la API (cron), en la tabla `job_runs`. Hoy hay un job:
`nightly_export` (`scripts/nightly_export.py`).

## `job_runs`

| Columna | Uso |
|---|---|
| `id` | UUID de la ejecución |
| `job_name` | `nightly_export` |
| `target_date` | Día (UTC) que procesa la ejecución; clave de la idempotencia |
| `status` | `pending` → `processing` → `completed` \| `failed` |
| `started_at` / `finished_at` | Paso a `processing` y estado final |
| `error_message` | Clase y mensaje de la excepción, sin SQL ni credenciales (la traza va al log) |
| `details` | JSON para soporte: `csv_path`, `csv_created`, `rows_exported`, `pipeline_exit_code`, `pipeline_duration_ms` |
| `created_at` | Creación de la fila (`pending`) |

- **Lock:** una fila `processing` bloquea el job. El índice único parcial `job_runs_one_active` (una fila
  `pending`/`processing` por job) resuelve la carrera cuando dos instancias arrancan a la vez. No hay otra tabla ni columna de lock.
- **Idempotencia:** una fila `completed` para `(job_name, target_date)` hace que la siguiente ejecución de ese día se omita.
- **Sin zombis:** `run_job` cierra la fila como `failed` en un `finally` ante cualquier excepción, incluidos `SIGTERM` y Ctrl+C.
  Si el proceso muere con `SIGKILL`, la fila activa caduca a `failed` tras 6 h en la siguiente ejecución.
- **Migración:** `ensure_job_runs_table` la crea al arrancar el script; `migrations/001_create_job_runs.sql` es el mismo DDL para
  aplicarlo a mano en Supabase.

`job_runs` es la capa de orquestación. Las fases del ETL siguen en `reporting.pipeline_runs`, que escribe el pipeline.

## `nightly_export`

1. Exporta `telemetry_events` del día objetivo (por `timestamp`, UTC) a `data/raw/telemetry_YYYY-MM-DD.csv`, solo si el archivo
   no existe. Es un backup para auditoría: el pipeline lee de la base de datos, no del CSV.
2. Lanza `python -m data.pipelines.pipeline --triggered-by job:nightly_export` como subproceso (1 h como máximo).
3. Registra el resultado en `job_runs`.

```bash
uv run python scripts/nightly_export.py                         # ayer (UTC)
TARGET_DATE=2026-09-28 uv run python scripts/nightly_export.py   # otra fecha ya cerrada
```

Salida: `0` completado u omitido, `1` fallido, `2` configuración inválida (`TARGET_DATE`, `DATABASE_URL`).

**Disparador:** el contenedor `scheduler` de `docker-compose.yml` (supercronic, `infra/scheduler/crontab`):
`15 1 * * *` (01:15 UTC cada día). Sin Docker, la misma línea vale en el crontab del sistema:

```cron
15 1 * * * cd /ruta/al/monorepo && uv run python scripts/nightly_export.py >> /var/log/trackflow/nightly_export.log 2>&1
```

**Recuperación:** si una noche falla, la fila queda `failed` con su error. Se relanza ese día con `TARGET_DATE=<día>`; el CSV ya
exportado se reutiliza y solo se repite el pipeline.
