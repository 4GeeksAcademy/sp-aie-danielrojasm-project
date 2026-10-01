-- task_dead_letters: Dead Letter Queue de Celery, una fila por tarea que agotó sus reintentos.
-- Equivale a `services.tasks.dead_letter.ensure_dead_letters_table`, que el worker ejecuta
-- antes de escribir; este SQL sirve para crearla a mano en Supabase.
-- Idempotente: se puede ejecutar varias veces.

create table if not exists task_dead_letters (
    id            uuid primary key default gen_random_uuid(),
    task_id       text not null unique,      -- id de Celery; único para que una entrega doble no duplique
    task_name     text not null,
    attempts      integer not null,          -- intentos ejecutados (1 + max_retries)
    error_type    text not null,
    error_message text not null,             -- clase y primera línea, sin URLs ni SQL (la traza va al log)
    task_args     jsonb,                     -- solo identificadores (run_id, week_start, triggered_by…)
    failed_at     timestamptz not null,
    created_at    timestamptz not null default now()
);

create index if not exists ix_task_dead_letters_task_name_failed_at on task_dead_letters (task_name, failed_at desc);

-- RLS sin políticas, como job_runs: solo el propietario (DATABASE_URL) lee y escribe.
alter table task_dead_letters enable row level security;
