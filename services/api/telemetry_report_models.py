"""Respuesta de `GET /telemetry/report`: métricas técnicas de `telemetry_events`.

Cada fila es lo que devuelve su función en `services/telemetry/analysis.py`;
los días (`date`) están en UTC y las tasas van de 0 a 1.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TelemetryReportPeriod(BaseModel):
    model_config = ConfigDict(validate_by_name=True, serialize_by_alias=True)

    from_: datetime = Field(alias="from", description="Inicio de la ventana (incluido), UTC.")
    to: datetime = Field(description="Fin de la ventana (excluido), UTC.")


class EventsPerDayRow(BaseModel):
    date: date
    service: Literal["backoffice", "api", "job"]
    events: int
    sessions: int = Field(description="Sesiones distintas que emitieron eventos ese día.")


class EventsByTypeRow(BaseModel):
    event_type: str
    events: int
    active_days: int = Field(description="Días del período con al menos un evento de este tipo.")
    last_seen: datetime
    share: float = Field(description="Fracción del volumen total del período.")


class ErrorRateRow(BaseModel):
    date: date
    event_type: str
    error_kind: Literal["system", "rejected"] = Field(
        description="`system`: el sistema falló; `rejected`: rechazó una petición."
    )
    errors: int
    total_events: int = Field(description="Eventos de cualquier tipo ese día (denominador).")
    error_rate: float


class PageLoadRow(BaseModel):
    date: date
    route: str
    samples: int
    ttfb_ms_p75: float | None
    fcp_ms_p75: float | None
    lcp_ms_p75: float | None
    inp_ms_p75: float | None = Field(description="`None` si no hubo interacciones medidas.")
    cls_p75: float | None


class AuthFailureRateRow(BaseModel):
    date: date
    attempts: int
    failed: int
    succeeded: int
    failure_rate: float


class TelemetryReportMetrics(BaseModel):
    events_per_day: list[EventsPerDayRow]
    events_by_type: list[EventsByTypeRow]
    error_rate_by_type: list[ErrorRateRow]
    page_load_by_route: list[PageLoadRow]
    auth_failure_rate: list[AuthFailureRateRow]


class TelemetryReport(BaseModel):
    period: TelemetryReportPeriod
    generated_at: datetime = Field(description="Cuándo se calculó; puede venir de la caché (TTL 60 s).")
    metrics: TelemetryReportMetrics
