"""Respuestas de `services/reporting` (pipeline `weekly_warehouse_client_performance`).

`WeeklyPerformanceReport` sigue el contrato de `CONTEXT-company.md`
(`week_start` + `entries`), que consumirá el dashboard ejecutivo; los campos
añadidos (`computed_at`, `run_id`, `reconciliation_status`) solo dan trazabilidad.
"""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


Warehouse = Literal["los_angeles", "zaragoza"]
RunStatus = Literal["pending", "running", "completed", "failed", "crashed", "cancelled"]


class WeeklyPerformanceEntry(BaseModel):
    warehouse: Warehouse
    client_id: str
    inbound_units_count: int = Field(description="Volumen de entrada: unidades recibidas en la semana.")
    outbound_orders_count: int = Field(description="Throughput de salida: pedidos despachados (`dispatch`).")
    stockout_events_count: int = Field(description="Frecuencia de quiebre de stock: cruces del mínimo del SKU.")
    discrepancy_events_count: int = Field(description="Discrepancias de inventario detectadas en la semana.")
    discrepancy_rate: float = Field(
        description="Tasa de discrepancia: discrepancias / pedidos despachados (0 sin pedidos; puede superar 1)."
    )


class WeeklyPerformanceReport(BaseModel):
    week_start: date = Field(description="Lunes (UTC) de la semana ISO.")
    computed_at: datetime | None = Field(description="Último cambio de un número de la semana; `None` sin filas.")
    run_id: UUID | None = Field(description="Última corrida que cargó la semana.")
    reconciliation_status: Literal["ok", "gap", "unavailable"] | None = Field(
        description="`gap`: los eventos no cuadran con los movimientos reales (posible pérdida de captura)."
    )
    entries: list[WeeklyPerformanceEntry]


class PipelineRunRead(BaseModel):
    run_id: UUID
    pipeline_name: str
    status: RunStatus
    phase: Literal["extract", "transform", "validate", "load", "done"] | None = Field(
        description="Última etapa alcanzada: dónde se detuvo una corrida fallida."
    )
    trigger: Literal["schedule", "manual", "backfill"]
    triggered_by: str
    weeks_requested: list[date]
    window_start: datetime | None
    window_end: datetime | None
    events_extracted: int
    duplicates_dropped: int
    rows_rejected: int
    rows_upserted: int
    rows_changed: int = Field(description="Filas publicadas cuyo valor cambió en esta corrida.")
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    error_type: str | None
    error_message: str | None
    retry_of: UUID | None
    last_completed_at: datetime | None = Field(description="Fin de la última corrida completada.")
    stale: bool = Field(description="`True` si la última corrida completada tiene más de 8 días (o no hay).")


class PipelineRunTriggerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    week_start: date | None = Field(
        default=None, description="Lunes de una semana cerrada; por defecto, la última semana cerrada."
    )


class PipelineRunTriggered(BaseModel):
    run_id: UUID
    task_id: str = Field(description="Tarea de Celery que ejecuta la corrida; estado en `GET /tasks/{task_id}`.")
    status: Literal["pending"]
    week_start: date | None
