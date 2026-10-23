"""Contrato de la aprobación humana de la Parte 3: qué ve el responsable y qué decisión puede devolver.

- `ReviewRequest` es el valor del `interrupt` de cada departamento: lo mínimo para decidir sin releer la propuesta
  entera (estado de la evaluación, reglas incumplidas, arbitrajes que afectan a la sección y decisiones permitidas).
- `ApprovalDecision` es lo único que entra de vuelta al grafo. Se valida dos veces: en la API (o el script) antes de
  encolar el `resume`, y en `approval_runner.submit_decision` contra la revisión que está pendiente de verdad en el
  checkpoint (departamento, ronda y límite de revisiones). Una decisión que no encaja nunca llega a `Command(resume)`.

Decisiones:

- `approve`: la sección queda `aprobada` con el responsable nombrado del BRIEFING §2.1 como `approver`.
- `request_changes` (comentario obligatorio): vuelve al generador de la Parte 2 de ese departamento con el comentario
  como feedback, pasa otra vez por los evaluadores y vuelve a revisión humana, en la misma ejecución. Solo mientras la
  sección no haya agotado `max_rounds` revisiones.
- `reject` (motivo obligatorio): la sección queda `rechazada` y no se genera documento final; hace falta una nueva
  ejecución (`scripts/rfp_intake.py reprocess <ticket_id> --force`).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


Decision = Literal["approve", "request_changes", "reject"]
MIN_COMMENT_CHARS = 10


class InvalidDecisionError(ValueError):
    """La decisión no se puede aplicar a la revisión pendiente; el mensaje se muestra tal cual al usuario."""


class ReviewRequest(BaseModel):
    """Valor del `interrupt` de un departamento (se guarda en el checkpoint)."""

    kind: Literal["department_approval"] = "department_approval"
    ticket_id: str
    department_id: str
    approver: str
    review_round: int
    revisions: int
    max_rounds: int
    draft_status: str | None
    evaluation_pass: bool | None
    failed_rules: list[str]
    arbitration_notes: list[str]
    allowed_decisions: list[Decision]


class DecisionInput(BaseModel):
    """Lo que envía el backoffice (`POST /rfps/{ticket_id}/sections/{department_id}/decision`)."""

    model_config = ConfigDict(extra="forbid")

    decision: Decision
    review_round: int = Field(ge=1, description="Ronda de revisión a la que responde; evita aplicar un clic repetido.")
    comment: str = Field(default="", max_length=2000)
    committed_monthly_capacity: int | None = Field(
        default=None, gt=0, le=10_000_000, description="Solo Warehouse: capacidad que compromete (pedidos/mes)."
    )

    @field_validator("comment")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def _comment_when_not_approving(self) -> "DecisionInput":
        if self.decision != "approve" and len(self.comment) < MIN_COMMENT_CHARS:
            raise ValueError(
                "Para pedir cambios o rechazar hay que explicar el motivo (al menos 10 caracteres): el generador y "
                "Ventas lo usan."
            )
        return self


class ApprovalDecision(DecisionInput):
    """La decisión que entra al grafo: la del backoffice más quién la registró (lo pone el servidor)."""

    decided_by: str = Field(min_length=1, max_length=120, description="Quién registra la decisión en el backoffice.")


def allowed_decisions(revisions: int, max_rounds: int) -> list[Decision]:
    """`request_changes` solo mientras quedan revisiones; después, aprobar o rechazar."""
    return ["approve", "request_changes", "reject"] if revisions < max_rounds else ["approve", "reject"]


def check_against(decision: ApprovalDecision, review: dict[str, Any]) -> None:
    """Valida la decisión contra la revisión pendiente en el checkpoint (`ReviewRequest` como dict)."""
    if decision.review_round != review["review_round"]:
        raise InvalidDecisionError(
            f"La sección está en la revisión {review['review_round']} y la decisión es de la revisión "
            f"{decision.review_round}: recarga el ticket."
        )
    if decision.decision not in review["allowed_decisions"]:
        raise InvalidDecisionError(
            f"La sección ya agotó las {review['max_rounds']} revisiones permitidas: solo se puede aprobar o rechazar."
        )
    if decision.committed_monthly_capacity is not None and review["department_id"] != "warehouse":
        raise InvalidDecisionError("Solo Warehouse Operations compromete capacidad mensual.")
