"""Estado del grafo del agente: solo lo que un nodo necesita para decidir el siguiente paso.

No hay historial de conversación: cada pregunta se responde de forma independiente con la base de conocimiento,
igual que `POST /knowledge/query`, así que arrastrar mensajes anteriores solo añadiría ruido al prompt.
"""

from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    # Pregunta del account manager, ya sin espacios sobrantes (la normaliza `receive_question`).
    question: str
    # Payloads que devolvió `retrieve()` por encima de `min_score`; vacío = no hay información.
    context: list[dict[str, Any]]
    # Respuesta final (generada, o el aviso honesto de que no hay información).
    answer: str
    # Motivo por el que la corrida terminó sin responder (pregunta vacía).
    error: str
