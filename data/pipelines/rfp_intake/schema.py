"""Tablas de la recepción de RFPs en PostgreSQL (Supabase), con SQLModel.

- `rfp_tickets`: un ticket por PDF subido; su `status` es la verdad que consulta la UI. `handoff` es el contrato
  de enrutamiento hacia la Parte 2 (ver README): solo se rellena cuando el ticket llega a `analisis_completo`.
- `rfp_metadata`: metadatos extraídos, métricas de legibilidad y el Markdown convertido (la Parte 2 no vuelve a
  leer el PDF).
- `rfp_department_sections`: una fila por departamento activo con sus `key_aspects` (Parte 1) y, desde la Parte 2,
  el último borrador, su `EvaluationResult`, el estado del ciclo generador-evaluador y el historial de iteraciones.
  Las columnas de aprobación son de la Parte 3 (BRIEFING §2.3).

La API las crea con `SQLModel.metadata.create_all` al arrancar (importa este módulo). `create_all` no altera tablas
existentes: las columnas y estados de la Parte 2 los añade `migrations/001_response_generation.sql`, que
`ensure_response_schema` aplica en PostgreSQL al arrancar la API y al crear el engine del worker y de `scripts/`.
El pipeline no importa nada de `services/`.
"""

from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, CheckConstraint, Column, DateTime, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlmodel import Field, SQLModel

from data.pipelines.rfp_intake.departments import DEPARTMENTS, ClientCountry, Currency, SectionStatus, TicketStatus


logger = logging.getLogger("trackflow.rfp_intake")

RESPONSE_MIGRATION = Path(__file__).resolve().parent / "migrations" / "001_response_generation.sql"
_migrated: set[str] = set()
_migration_lock = threading.Lock()


def _one_of(column: str, values: list[str]) -> str:
    allowed = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({allowed})"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())


def _json_column(nullable: bool = True) -> Column:
    return Column(JSON().with_variant(JSONB(), "postgresql"), nullable=nullable)


def _timestamp_column(nullable: bool = False) -> Column:
    return Column(DateTime(timezone=True), nullable=nullable)


class RfpTicket(SQLModel, table=True):
    __tablename__ = "rfp_tickets"
    __table_args__ = (
        CheckConstraint(_one_of("status", [s.value for s in TicketStatus]), name="ck_rfp_tickets_status"),
    )

    ticket_id: str = Field(default_factory=new_id, primary_key=True, max_length=36)
    rfp_id: str | None = Field(default=None, max_length=36, index=True)
    status: str = Field(default=TicketStatus.ANALIZANDO.value, max_length=30, index=True)
    original_filename: str = Field(max_length=255)
    raw_pdf_path: str = Field(max_length=500)
    uploaded_by: str = Field(max_length=64)
    # Decisión del clasificador: un `descartado` siempre lleva su motivo.
    is_rfp: bool | None = None
    classification_confidence: float | None = None
    classification_reason: str | None = Field(default=None, sa_column=Column(Text))
    # Resumen del synthesizer para Ventas (qué pedir a quién) y contrato de handoff hacia la Parte 2.
    synthesis: dict[str, Any] | None = Field(default=None, sa_column=_json_column())
    handoff: dict[str, Any] | None = Field(default=None, sa_column=_json_column())
    # Contrato de la Parte 2 hacia la Parte 3: borradores + EvaluationResult por departamento.
    response_handoff: dict[str, Any] | None = Field(default=None, sa_column=_json_column())
    # Intentos del pipeline y último fallo (clase y primera línea, sin trazas ni datos de conexión).
    # `last_error` lo comparten las dos partes; `generation_attempts` cuenta los de la Parte 2.
    attempts: int = 0
    generation_attempts: int = 0
    last_error: str | None = Field(default=None, sa_column=Column(Text))
    created_at: datetime = Field(default_factory=utc_now, sa_column=_timestamp_column())
    updated_at: datetime = Field(default_factory=utc_now, sa_column=_timestamp_column())


class RfpMetadata(SQLModel, table=True):
    __tablename__ = "rfp_metadata"
    __table_args__ = (
        CheckConstraint(
            f"client_country IS NULL OR {_one_of('client_country', [c.value for c in ClientCountry])}",
            name="ck_rfp_metadata_client_country",
        ),
        CheckConstraint(
            f"currency IS NULL OR {_one_of('currency', [c.value for c in Currency])}",
            name="ck_rfp_metadata_currency",
        ),
        CheckConstraint("monthly_volume IS NULL OR monthly_volume > 0", name="ck_rfp_metadata_monthly_volume"),
    )

    rfp_id: str = Field(default_factory=new_id, primary_key=True, max_length=36)
    ticket_id: str = Field(foreign_key="rfp_tickets.ticket_id", unique=True, max_length=36, ondelete="CASCADE")
    client_name: str | None = Field(default=None, max_length=200)
    client_country: str | None = Field(default=None, max_length=2)
    currency: str | None = Field(default=None, max_length=3)
    client_reference: str | None = Field(default=None, max_length=120)
    services_requested: list[str] = Field(default_factory=list, sa_column=_json_column(nullable=False))
    monthly_volume: int | None = None
    deadline: date | None = None
    budget_range: str | None = Field(default=None, max_length=200)
    departments_needed: list[str] = Field(default_factory=list, sa_column=_json_column(nullable=False))
    # Métricas de legibilidad sobre el Markdown: anticipan el costo de procesar el documento.
    word_count: int = 0
    estimated_tokens: int = 0
    flesch_kincaid_grade: float | None = None
    gunning_fog: float | None = None
    flesch_reading_ease: float | None = None
    document_markdown: str = Field(sa_column=Column(Text, nullable=False))
    created_at: datetime = Field(default_factory=utc_now, sa_column=_timestamp_column())


class RfpDepartmentSection(SQLModel, table=True):
    __tablename__ = "rfp_department_sections"
    __table_args__ = (
        UniqueConstraint("ticket_id", "department_id", name="uq_rfp_department_sections_ticket_department"),
        CheckConstraint(_one_of("department_id", list(DEPARTMENTS)), name="ck_rfp_department_sections_department"),
        CheckConstraint(
            f"draft_status IS NULL OR {_one_of('draft_status', [s.value for s in SectionStatus])}",
            name="ck_rfp_department_sections_draft_status",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    ticket_id: str = Field(foreign_key="rfp_tickets.ticket_id", index=True, max_length=36, ondelete="CASCADE")
    department_id: str = Field(max_length=20)
    responsible: str = Field(max_length=120)
    key_aspects: list[str] = Field(default_factory=list, sa_column=_json_column(nullable=False))
    requested_inputs: list[str] = Field(default_factory=list, sa_column=_json_column(nullable=False))
    open_questions: list[str] = Field(default_factory=list, sa_column=_json_column(nullable=False))
    # Parte 2: último borrador y su EvaluationResult; el historial guarda cada iteración (borrador + evaluación).
    draft_status: str | None = Field(default=None, max_length=30)
    iterations: int = 0
    draft_content: str | None = Field(default=None, sa_column=Column(Text))
    evaluation_results: dict[str, Any] | None = Field(default=None, sa_column=_json_column())
    evaluation_history: list[dict[str, Any]] = Field(default_factory=list, sa_column=_json_column(nullable=False))
    # Parte 3.
    approval_status: str | None = Field(default=None, max_length=30)
    approver: str | None = Field(default=None, max_length=120)
    approved_at: datetime | None = Field(default=None, sa_column=_timestamp_column(nullable=True))
    created_at: datetime = Field(default_factory=utc_now, sa_column=_timestamp_column())


def ensure_response_schema(engine: Engine) -> None:
    """Aplica la migración de la Parte 2 en PostgreSQL, una vez por proceso. SQLite (tests) usa `create_all`.

    Sin ella, una base creada por la Parte 1 no tiene las columnas nuevas y cualquier lectura de `rfp_tickets`
    falla. La migración es idempotente y no borra datos.
    """
    if engine.dialect.name != "postgresql":
        return
    key = engine.url.render_as_string(hide_password=True)
    with _migration_lock:
        if key in _migrated:
            return
        with engine.begin() as connection:
            connection.exec_driver_sql(RESPONSE_MIGRATION.read_text(encoding="utf-8"))
        _migrated.add(key)
    logger.info("Esquema de la Parte 2 de RFPs listo en PostgreSQL.")
