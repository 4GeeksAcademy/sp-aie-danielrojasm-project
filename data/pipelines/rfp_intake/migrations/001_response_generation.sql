-- Parte 2 del flujo de RFPs (generación y evaluación de respuestas) sobre las tablas de la Parte 1.
-- `create_all` crea las tablas nuevas con este esquema, pero no altera las que ya existen en Supabase.
-- Lo aplica `response_runner.ensure_response_schema` antes de la primera generación de cada proceso;
-- también se puede ejecutar a mano. Idempotente: se puede ejecutar varias veces.

-- Estados del ticket: los tres de la Parte 1 más los tres de la Parte 2 (BRIEFING §2.3).
do $$
begin
    if not exists (
        select 1 from pg_constraint
        -- strpos y no LIKE: el archivo pasa por psycopg2, que toma el signo de porcentaje como parámetro.
        where conname = 'ck_rfp_tickets_status' and strpos(pg_get_constraintdef(oid), 'needs_human_review') > 0
    ) then
        alter table rfp_tickets drop constraint if exists ck_rfp_tickets_status;
        alter table rfp_tickets add constraint ck_rfp_tickets_status check (
            status in ('analizando', 'descartado', 'analisis_completo',
                       'generando_borrador', 'en_evaluación', 'needs_human_review')
        );
    end if;
end $$;

alter table rfp_tickets add column if not exists response_handoff jsonb;           -- contrato hacia la Parte 3
alter table rfp_tickets add column if not exists generation_attempts integer not null default 0;

alter table rfp_department_sections add column if not exists draft_status varchar(30);
alter table rfp_department_sections add column if not exists iterations integer not null default 0;
alter table rfp_department_sections add column if not exists evaluation_history jsonb not null default '[]'::jsonb;

do $$
begin
    if not exists (select 1 from pg_constraint where conname = 'ck_rfp_department_sections_draft_status') then
        alter table rfp_department_sections add constraint ck_rfp_department_sections_draft_status check (
            draft_status is null
            or draft_status in ('generando_borrador', 'en_evaluación', 'evaluacion_superada', 'needs_human_review')
        );
    end if;
end $$;
