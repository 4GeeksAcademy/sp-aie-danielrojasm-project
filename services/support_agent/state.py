"""Estado del grafo del agente: solo lo que un nodo necesita para decidir el siguiente paso.

No hay historial de conversación: cada pregunta se responde de forma independiente con la base de conocimiento,
el gestor de incidencias y la memoria aprobada. Lo único que une dos turnos de una conversación es la propuesta de
memoria pendiente, que vive en el almacén de memoria (`memory/store.py`), no en el estado.
"""

from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    # Pregunta del account manager, ya sin espacios sobrantes (la normaliza `receive_question`). Si el mensaje
    # respondía a una propuesta de memoria y además preguntaba algo, `resolve_proposal` deja aquí solo esa parte.
    question: str
    # Mensaje completo del usuario en este turno (normalizado).
    message: str
    # Conversación a la que pertenece el turno y usuario autenticado que decide sobre la memoria (sin usuario no se
    # proponen escrituras). `run_id` es el de la corrida, para la auditoría.
    conversation_id: str
    user_id: str | None
    run_id: str
    # Propuesta de memoria pendiente del usuario en esta conversación (`MemoryProposal` serializada), si la hay.
    pending_proposal: dict[str, Any] | None
    # Resultado de la decisión sobre la propuesta pendiente: `proposal_id`, `outcome`, `reason`, `fact`.
    memory_decision: dict[str, Any]
    # Entradas de memoria recuperadas para la pregunta, como fragmentos de contexto.
    memories: list[dict[str, Any]]
    # `propuesta_memoria` que devolvió el modelo (`MemoryDraft` serializado), antes de validarla.
    memory_candidate: dict[str, Any] | None
    # Propuesta validada y pendiente de la decisión del usuario (`MemoryProposal` serializada).
    memory_proposal: dict[str, Any] | None
    # Avisos sobre la memoria que preceden a la respuesta (decisión aplicada, memoria no disponible).
    memory_notices: list[str]
    # Fuentes que necesita la pregunta (`RoutePlan` serializado): `ticket_ids`, `needs_knowledge`, `decided_by`.
    route: dict[str, Any]
    # Resultado de la tool de tickets (`TicketLookup` serializado), uno por ticket consultado.
    tickets: list[dict[str, Any]]
    # Payloads que devolvió `retrieve()` por encima de `min_score`; vacío = no hay información.
    context: list[dict[str, Any]]
    # Respuesta final (generada, o el aviso honesto de que no hay información o no se pudo confirmar un ticket).
    answer: str
    # Motivo por el que la corrida terminó sin responder (pregunta vacía).
    error: str
