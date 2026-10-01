"""Dead Letter Queue: tareas que agotaron sus reintentos.

Cuando una tarea supera `max_retries`, su último intento publica un mensaje en la cola
`dead_letter` de Celery (visible en Flower) y termina en `FAILURE`. El consumidor de esa
cola, `record_dead_letter`, guarda el fallo en la tabla `task_dead_letters`:
`task_id`, nombre de la tarea, número de intentos, error, argumentos (solo
identificadores) y `failed_at`.

- Idempotente: `task_id` es único; si el mensaje se entrega dos veces, la segunda no inserta.
- Si la base de datos no responde, `record_dead_letter` se reintenta con backoff; si ni
  siquiera se puede publicar en la cola, el fallo se escribe directamente.
- La tabla se crea al escribir si falta (con RLS sin políticas en PostgreSQL); el SQL
  equivalente está en `services/tasks/migrations/001_create_task_dead_letters.sql`.

No importa FastAPI ni `services/api`: lo usa el worker.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import Column, DateTime, Index, Integer, MetaData, Table, Text, Uuid, func, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.types import JSON

from data.pipelines.weekly_warehouse_client_performance.database import DatabaseNotConfiguredError, engine_for
from services.jobs.job_runner import describe_error
from services.tasks.celery_app import DEAD_LETTER_QUEUE, celery_app


logger = logging.getLogger("trackflow.tasks")

metadata = MetaData()

task_dead_letters = Table(
    "task_dead_letters",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("task_id", Text, nullable=False, unique=True),
    Column("task_name", Text, nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("error_type", Text, nullable=False),
    Column("error_message", Text, nullable=False),
    # Solo identificadores (los mensajes de la cola nunca llevan datos voluminosos).
    Column("task_args", JSON().with_variant(JSONB(), "postgresql")),
    Column("failed_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Index("ix_task_dead_letters_task_name_failed_at", "task_name", text("failed_at desc")),
)


def tasks_engine() -> Engine:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise DatabaseNotConfiguredError("Falta DATABASE_URL: no se puede registrar la tarea en la DLQ.")
    return engine_for(url)


def ensure_dead_letters_table(engine: Engine) -> None:
    """Crea `task_dead_letters` y su índice si faltan (idempotente). Equivale a la migración 001."""
    with engine.begin() as connection:
        metadata.create_all(connection, checkfirst=True)
        if connection.dialect.name == "postgresql":
            connection.execute(text("alter table task_dead_letters alter column id set default gen_random_uuid()"))
            # RLS sin políticas, como `job_runs`: solo el propietario (`DATABASE_URL`) lee y escribe.
            connection.execute(text("alter table task_dead_letters enable row level security"))


def save_dead_letter(
    engine: Engine,
    *,
    task_id: str,
    task_name: str,
    attempts: int,
    error_type: str,
    error_message: str,
    task_args: dict[str, Any] | None,
    failed_at: datetime,
) -> bool:
    """Inserta el fallo; `False` si ese `task_id` ya estaba en la DLQ."""
    ensure_dead_letters_table(engine)
    try:
        with engine.begin() as connection:
            connection.execute(
                task_dead_letters.insert().values(
                    id=uuid4(),
                    task_id=task_id,
                    task_name=task_name,
                    attempts=attempts,
                    error_type=error_type,
                    error_message=error_message,
                    task_args=task_args,
                    failed_at=failed_at,
                )
            )
    except IntegrityError:
        return False
    return True


def list_dead_letters(engine: Engine, task_name: str | None = None) -> list[dict[str, Any]]:
    ensure_dead_letters_table(engine)
    query = select(task_dead_letters).order_by(task_dead_letters.c.failed_at.desc())
    if task_name is not None:
        query = query.where(task_dead_letters.c.task_name == task_name)
    with engine.connect() as connection:
        return [dict(row._mapping) for row in connection.execute(query)]


@celery_app.task(
    name="tasks.record_dead_letter",
    autoretry_for=(SQLAlchemyError, DatabaseNotConfiguredError),
    max_retries=5,
    retry_backoff=10,
    retry_backoff_max=300,
    retry_jitter=False,
    soft_time_limit=60,
    time_limit=90,
)
def record_dead_letter(
    task_id: str,
    task_name: str,
    attempts: int,
    error_type: str,
    error_message: str,
    task_args: dict[str, Any] | None,
    failed_at: str,
) -> dict[str, Any]:
    inserted = save_dead_letter(
        tasks_engine(),
        task_id=task_id,
        task_name=task_name,
        attempts=attempts,
        error_type=error_type,
        error_message=error_message,
        task_args=task_args,
        failed_at=datetime.fromisoformat(failed_at),
    )
    logger.error(
        "task_id=%s task=%s attempt=%s status=dead_letter %s error=%s",
        task_id,
        task_name,
        attempts,
        "registrada en task_dead_letters" if inserted else "ya estaba en task_dead_letters",
        error_message,
    )
    return {"task_id": task_id, "recorded": inserted}


def send_to_dead_letter(
    task_id: str, task_name: str, attempts: int, error: BaseException, task_args: dict[str, Any] | None
) -> None:
    """Publica el fallo definitivo en la cola `dead_letter`. Nunca lanza: el error original manda."""
    description = describe_error(error)
    error_type = type(error).__name__
    failed_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "task_id": task_id,
        "task_name": task_name,
        "attempts": attempts,
        "error_type": error_type,
        "error_message": description,
        "task_args": task_args,
        "failed_at": failed_at,
    }
    try:
        record_dead_letter.apply_async(kwargs=payload, queue=DEAD_LETTER_QUEUE)
        return
    except Exception:
        logger.exception("task_id=%s task=%s No se pudo publicar en la cola %s; se escribe directamente.", task_id, task_name, DEAD_LETTER_QUEUE)
    try:
        save_dead_letter(
            tasks_engine(),
            **{**payload, "failed_at": datetime.fromisoformat(failed_at)},
        )
    except Exception:
        logger.critical(
            "task_id=%s task=%s attempt=%s status=dead_letter Fallo definitivo SIN registrar en BD: %s",
            task_id,
            task_name,
            attempts,
            description,
            exc_info=True,
        )
