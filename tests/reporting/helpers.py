"""Eventos de telemetría sintéticos para los tests del pipeline de desempeño de negocio."""

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from data.process.weekly_performance import last_closed_week, week_bounds


ZGZ = {"warehouse": "zaragoza", "client_id": "purestep-footwear"}
LA = {"warehouse": "los_angeles", "client_id": "fashion-co"}


def closed_week(weeks_ago: int = 0) -> date:
    return last_closed_week(datetime.now(timezone.utc)) - timedelta(weeks=weeks_ago)


def at(week: date, hours: float = 10) -> datetime:
    """Un instante dentro de la semana (por defecto, el lunes a las 10:00 UTC)."""
    return week_bounds(week)[0] + timedelta(hours=hours)


def make_event(
    event_type: str,
    timestamp: datetime,
    *,
    received_at: datetime | None = None,
    event_id: str | None = None,
    **tags: Any,
) -> dict[str, Any]:
    """Fila de `telemetry_events` como la que guarda la API."""
    return {
        "id": event_id or str(uuid.uuid4()),
        "event_type": event_type,
        "timestamp": timestamp,
        "received_at": received_at or timestamp + timedelta(seconds=1),
        "service": "api",
        "user_id": "user-1",
        "session_id": "session-1",
        "tags": tags,
    }
