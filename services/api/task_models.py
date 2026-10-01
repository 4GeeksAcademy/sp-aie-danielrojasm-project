"""Respuestas de `GET /tasks/{task_id}` (cola de tareas asíncronas de Celery)."""

from typing import Any, Literal

from pydantic import BaseModel, Field


TaskStatus = Literal["pending", "started", "retry", "success", "failure"]


class TaskStatusRead(BaseModel):
    task_id: str
    status: TaskStatus = Field(
        description=(
            "`pending`: en cola (o id desconocido: Celery no los distingue); `started`: en un worker; "
            "`retry`: falló y espera su reintento; `success` / `failure`: estado final."
        )
    )
    result: dict[str, Any] | None = Field(description="Resultado de la tarea cuando termina en `success`.")
    error: str | None = Field(description="Clase y mensaje del último error (`retry` o `failure`).")
