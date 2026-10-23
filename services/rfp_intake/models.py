"""Respuestas de `/rfps/*`.

El Markdown del documento y el payload completo de los handoffs no salen por la API: los leen las Partes 2 y 3 de
la base de datos. La UI necesita el estado, los metadatos, qué pedir a quién y, desde la Parte 2, el borrador y el
`EvaluationResult` de cada sección.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from data.pipelines.rfp_intake.evaluators import EvaluationResult


TicketStatus = Literal[
    "analizando", "descartado", "analisis_completo", "generando_borrador", "en_evaluación", "needs_human_review"
]
DepartmentId = Literal["warehouse", "lastmile", "reverse"]
SectionStatus = Literal["generando_borrador", "en_evaluación", "evaluacion_superada", "needs_human_review"]


class RfpTicketCreated(BaseModel):
    ticket_id: str
    status: TicketStatus
    task_id: str = Field(description="Tarea de Celery que ejecuta el análisis (`GET /tasks/{task_id}`).")


class RfpTicketListItem(BaseModel):
    ticket_id: str
    status: TicketStatus
    original_filename: str
    client_name: str | None
    client_country: Literal["US", "ES"] | None
    departments_needed: list[DepartmentId]
    attempts: int
    last_error: str | None
    response_handoff_ready: bool
    created_at: datetime
    updated_at: datetime


class RfpClassificationRead(BaseModel):
    is_rfp: bool
    confidence: float
    reason: str


class RfpReadabilityRead(BaseModel):
    word_count: int
    estimated_tokens: int = Field(description="Aproximación de ~4 caracteres por token del Markdown.")
    flesch_kincaid_grade: float | None = Field(description="`None` si el documento tiene menos de 100 palabras.")
    gunning_fog: float | None
    flesch_reading_ease: float | None


class RfpMetadataRead(BaseModel):
    rfp_id: str
    client_name: str | None
    client_country: Literal["US", "ES"] | None
    currency: Literal["USD", "EUR"] | None
    client_reference: str | None
    services_requested: list[Literal["warehousing", "last_mile", "reverse_logistics"]]
    monthly_volume: int | None
    deadline: date | None
    budget_range: str | None
    departments_needed: list[DepartmentId]
    readability: RfpReadabilityRead


class DepartmentSectionRead(BaseModel):
    department_id: DepartmentId
    department_name: str
    responsible: str
    key_aspects: list[str]
    requested_inputs: list[str] = Field(description="Qué tiene que pedirle Ventas al responsable.")
    open_questions: list[str] = Field(description="Datos que faltan en la RFP y hay que preguntar al cliente.")
    draft_status: SectionStatus | None = Field(
        description="Etapa del ciclo generador-evaluador; `None` antes de la Parte 2."
    )
    iterations: int = Field(description="Iteraciones del ciclo generador-evaluador hasta ahora.")
    draft_content: str | None = Field(description="Último borrador de la sección (Markdown).")
    evaluation: EvaluationResult | None = Field(description="Evaluación del último borrador.")


class RfpSynthesisRead(BaseModel):
    summary: str
    next_steps: list[str]
    conflicts: list[str]
    out_of_scope: list[str]


class RfpTicketRead(BaseModel):
    ticket_id: str
    status: TicketStatus
    original_filename: str
    attempts: int
    last_error: str | None
    created_at: datetime
    updated_at: datetime
    classification: RfpClassificationRead | None
    metadata: RfpMetadataRead | None
    sections: list[DepartmentSectionRead]
    synthesis: RfpSynthesisRead | None
    handoff_ready: bool = Field(description="El handoff hacia la Parte 2 está guardado con el ticket.")
    generation_attempts: int = Field(description="Intentos de la Parte 2 (generación y evaluación).")
    max_iterations: int | None = Field(description="Límite de iteraciones por sección de la última generación.")
    response_handoff_ready: bool = Field(description="El handoff hacia la Parte 3 está guardado con el ticket.")
