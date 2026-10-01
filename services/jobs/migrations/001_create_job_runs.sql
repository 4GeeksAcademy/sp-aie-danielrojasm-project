-- job_runs: una fila por ejecución de un job en segundo plano y fecha objetivo.
-- Equivale a `services.jobs.job_runner.ensure_job_runs_table`, que el script
-- nocturno ejecuta al arrancar; este SQL sirve para crearla a mano en Supabase.
-- Idempotente: se puede ejecutar varias veces.
--
-- Capa de orquestación (export CSV, disparo del pipeline, lock e idempotencia).
-- No sustituye a reporting.pipeline_runs, que registra las fases del ETL.

create table if not exists job_runs (
    id            uuid primary key default gen_random_uuid(),
    job_name      text not null,
    target_date   date not null,
    status        text not null check (status in ('pending', 'processing', 'completed', 'failed')),
    started_at    timestamptz,
    finished_at   timestamptz,
    error_message text,
    details       jsonb,
    created_at    timestamptz not null default now()
);

-- Idempotencia: ¿ya hay una ejecución completed de este job para esta fecha?
create index if not exists ix_job_runs_job_name_target_date on job_runs (job_name, target_date);

-- Lock: como mucho una ejecución pending/processing por job. Hace atómica la
-- toma del lock cuando dos instancias arrancan a la vez.
create unique index if not exists job_runs_one_active on job_runs (job_name)
    where status in ('pending', 'processing');

-- RLS sin políticas, como telemetry_events: solo el propietario (DATABASE_URL) lee y escribe.
alter table job_runs enable row level security;
