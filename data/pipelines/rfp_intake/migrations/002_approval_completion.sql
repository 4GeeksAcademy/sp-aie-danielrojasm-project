-- Parte 3 del flujo de RFPs (aprobación humana y cierre del documento) sobre las tablas de las Partes 1 y 2.
-- `create_all` crea las tablas nuevas, pero no altera las que ya existen en Supabase. Lo aplica
-- `schema.ensure_response_schema` (después de 001) al arrancar la API y al crear el engine del worker y de
-- `scripts/`. Idempotente: se puede ejecutar varias veces. Sin el signo de porcentaje (pasa por psycopg2).

-- Estados del ticket: los de las Partes 1 y 2 más los dos de la Parte 3 (BRIEFING §2.3).
do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conname = 'ck_rfp_tickets_status' and strpos(pg_get_constraintdef(oid), 'terminado') > 0
    ) then
        alter table rfp_tickets drop constraint if exists ck_rfp_tickets_status;
        alter table rfp_tickets add constraint ck_rfp_tickets_status check (
            status in ('analizando', 'descartado', 'analisis_completo',
                       'generando_borrador', 'en_evaluación', 'needs_human_review',
                       'esperando_aprobación', 'terminado')
        );
    end if;
end $$;

alter table rfp_tickets add column if not exists approval_attempts integer not null default 0;
alter table rfp_tickets add column if not exists trace jsonb not null default '[]'::jsonb;
alter table rfp_tickets add column if not exists arbitrations jsonb not null default '[]'::jsonb;

alter table rfp_department_sections add column if not exists review_round integer not null default 0;
alter table rfp_department_sections add column if not exists revisions integer not null default 0;
alter table rfp_department_sections add column if not exists approval_history jsonb not null default '[]'::jsonb;

do $$
begin
    if not exists (select 1 from pg_constraint where conname = 'ck_rfp_department_sections_approval_status') then
        alter table rfp_department_sections add constraint ck_rfp_department_sections_approval_status check (
            approval_status is null
            or approval_status in ('pendiente', 'cambios_solicitados', 'aprobada', 'rechazada')
        );
    end if;
end $$;

-- Documento final (BRIEFING §2.3, FinalDocument). Mismo esquema que `RfpFinalDocument` en `schema.py`.
create table if not exists rfp_final_documents (
    id serial primary key,
    ticket_id varchar(36) not null unique references rfp_tickets (ticket_id) on delete cascade,
    rfp_id varchar(36),
    currency varchar(3) not null,
    sections jsonb not null default '[]'::jsonb,
    content text not null,
    generated_at timestamp with time zone not null,
    constraint ck_rfp_final_documents_currency check (currency in ('USD', 'EUR'))
);
