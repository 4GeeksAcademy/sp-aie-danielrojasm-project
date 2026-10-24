"""Respuestas de `/rfps/*`.

El Markdown de la RFP y el payload completo de los handoffs no salen por la API: los leen las Partes 2 y 3 de la
base de datos. La UI necesita el estado, los metadatos, qué pedir a quién, desde la Parte 2 el borrador y el
`EvaluationResult` de cada sección y, desde la Parte 3, la revisión pendiente de cada responsable, los arbitrajes,
la traza de la ejecución y el documento final.
"""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from data.pipelines.rfp_intake.approval import Decision
from data.pipelines.rfp_intake.evaluators import EvaluationResult


TicketStatus = Literal[
    "analizando",
    "descartado",
    "analisis_completo",
    "generando_borrador",
    "en_evaluación",
    "needs_human_review",
    "esperando_aprobación",
    "terminado",
]
DepartmentId = Literal["warehouse", "lastmile", "reverse"]
SectionStatus = Literal["generando_borrador", "en_evaluación", "evaluacion_superada", "needs_human_review"]
ApprovalStatus = Literal["pendiente", "cambios_solicitados", "aprobada", "rechazada"]


class RfpTicketCreated(BaseModel):
    ticket_id: str
    status: TicketStatus
    task_id: str = Field(description="Tarea de Celery que ejecuta el análisis (`GET /tasks/{task_id}`).")


class RfpTicketCreatedEvent(BaseModel):
    """`data:` del evento SSE `rfp_ticket_created` (BRIEFING de tiempo real, §3): solo campos del ticket.

    Se emite cuando el documento ya está clasificado como una RFP válida y el ticket sigue en `analizando`. Los
    nombres y valores son los del sistema de RFPs; `original_filename` permite pintar la fila sin otra petición.
    """

    ticket_id: str
    rfp_id: str
    client_name: str | None
    client_country: Literal["US", "ES"] | None
    services_requested: list[Literal["warehousing", "last_mile", "reverse_logistics"]]
    status: Literal["analizando"]
    original_filename: str
    created_at: datetime


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
    approval_status: ApprovalStatus | None = Field(description="Aprobación del responsable; `None` antes de la Parte 3.")
    approver: str | None = Field(description="Responsable que aprobó la sección (BRIEFING §2.1).")
    approved_at: datetime | None
    review_round: int = Field(description="Ronda de revisión humana actual (0 antes de la Parte 3).")
    revisions: int = Field(description="Reescrituras pedidas en la Parte 3 por el responsable o el árbitro.")
    approval_history: list["ApprovalDecisionRead"]
    pending_review: "PendingReviewRead | None" = Field(
        description="Revisión esperando la decisión del responsable, tal como la guarda el checkpoint."
    )


class ApprovalDecisionRead(BaseModel):
    decision: Decision
    review_round: int
    comment: str
    decided_by: str
    approver: str
    decided_at: datetime
    committed_monthly_capacity: int | None = None


class PendingReviewRead(BaseModel):
    """Lo mínimo para decidir sin releer la propuesta: es el valor del `interrupt` de la rama."""

    approver: str
    review_round: int
    revisions: int
    max_rounds: int
    evaluation_pass: bool | None
    failed_rules: list[str]
    arbitration_notes: list[str]
    allowed_decisions: list[Decision]


class ArbitrationRead(BaseModel):
    round: int
    trigger_id: Literal["volume-vs-capacity", "returns-sla-breach", "currency-mismatch"]
    arbiter: str
    rule: str
    department_id: DepartmentId
    action: Literal["request_changes", "reject"]
    instruction: str | None
    evidence: str
    decided_at: datetime


class TraceEntryRead(BaseModel):
    part: Literal["parte_1", "parte_2", "parte_3"]
    node: str
    agent: str
    department_id: str | None
    input: Any
    output: Any
    timestamp: datetime
    duration_ms: int | None


class ApprovalDecisionAccepted(BaseModel):
    ticket_id: str
    department_id: DepartmentId
    task_id: str = Field(description="Tarea de Celery que reanuda la rama del departamento.")


class FinalDocumentSectionRead(BaseModel):
    department_id: DepartmentId
    department_name: str
    approver: str
    approved_at: datetime
    review_round: int


class FinalDocumentRead(BaseModel):
    ticket_id: str
    rfp_id: str | None
    currency: Literal["USD", "EUR"]
    generated_at: datetime
    sections: list[FinalDocumentSectionRead]
    content: str = Field(description="Documento final en Markdown: las secciones aprobadas, sin reescribir.")


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
    approval_attempts: int = Field(description="Intentos de abrir la Parte 3 (aprobación).")
    arbitrations: list[ArbitrationRead] = Field(description="Decisiones del árbitro fijo (BRIEFING §7), en orden.")
    trace: list[TraceEntryRead] = Field(description="Qué agente hizo qué y en qué orden, en las tres partes.")
    final_document_ready: bool = Field(description="El documento final está guardado (`GET /rfps/{id}/document`).")
