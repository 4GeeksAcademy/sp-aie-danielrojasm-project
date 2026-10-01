"""Reporte técnico de telemetría: `GET /telemetry/report`.

Sirve las métricas de `services/telemetry/analysis.py` para una ventana
`[start_date, end_date)` en UTC; sin parámetros, los últimos 7 días. El período
se resuelve una sola vez aquí y se pasa a cada métrica, que lo aplica en SQL.

El endpoint nunca calcula en cada petición: `report_cache` guarda el reporte
60 s por combinación de parámetros tal como llegan. Con los valores por
defecto la clave es `(None, None)`, así que el período (y `generated_at`) es
el del cálculo cacheado, no el del instante de la petición. No se invalida al
ingerir: un reporte técnico tolera 60 s de retraso y la ingesta escribe en
cada lote.
"""

import logging
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.exceptions import RequestValidationError
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from services.api.cache import TTLCache
from services.api.database import DatabaseNotConfiguredError, get_engine
from services.api.security import get_current_user
from services.api.telemetry_report_models import TelemetryReport
from services.telemetry.analysis import build_report


logger = logging.getLogger("trackflow.telemetry")

router = APIRouter(prefix="/telemetry", tags=["telemetry"], dependencies=[Depends(get_current_user)])

DEFAULT_WINDOW = timedelta(days=7)
# Tope de la ventana: el pipeline carga en memoria las filas del período.
MAX_WINDOW = timedelta(days=90)
REPORT_TTL_SECONDS = 60
REPORT_UNAVAILABLE_DETAIL = (
    "El almacén de telemetría no está disponible ahora mismo; vuelve a intentarlo en unos minutos."
)

report_cache: TTLCache[TelemetryReport] = TTLCache("telemetry_report_cache", ttl_seconds=REPORT_TTL_SECONDS)


def get_report_engine() -> Engine:
    try:
        return get_engine()
    except DatabaseNotConfiguredError as error:
        logger.error("Reporte de telemetría sin almacén: %s", error)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, REPORT_UNAVAILABLE_DETAIL) from error


def _as_utc(value: datetime | None) -> datetime | None:
    """Una fecha sin zona se interpreta en UTC."""
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _invalid_period(field: str, message: str) -> RequestValidationError:
    return RequestValidationError([{"type": "value_error", "loc": ("query", field), "msg": message}])


def resolve_period(
    start_date: datetime | None, end_date: datetime | None, now: datetime
) -> tuple[datetime, datetime]:
    """Por defecto `end = now` y `start = end − 7 días`; cada uno se puede fijar por separado."""
    end = end_date or now
    start = start_date or end - DEFAULT_WINDOW
    if start >= end:
        raise _invalid_period("start_date", "start_date debe ser anterior a end_date.")
    if end - start > MAX_WINDOW:
        raise _invalid_period("end_date", f"La ventana no puede superar {MAX_WINDOW.days} días.")
    return start, end


@router.get("/report", response_model=TelemetryReport)
def get_telemetry_report(
    start_date: datetime | None = Query(
        default=None, description="Inicio ISO 8601 (incluido). Sin zona = UTC. Por defecto, `end_date` − 7 días."
    ),
    end_date: datetime | None = Query(
        default=None, description="Fin ISO 8601 (excluido). Sin zona = UTC. Por defecto, ahora."
    ),
    engine: Engine = Depends(get_report_engine),
) -> TelemetryReport:
    start_date, end_date = _as_utc(start_date), _as_utc(end_date)
    # Se valida antes de la caché: una ventana inválida nunca ocupa una entrada.
    resolve_period(start_date, end_date, datetime.now(timezone.utc))

    def compute() -> TelemetryReport:
        now = datetime.now(timezone.utc)
        start, end = resolve_period(start_date, end_date, now)
        started = time.perf_counter()
        try:
            metrics = build_report(engine, start, end)
        except SQLAlchemyError as error:
            # La traza (con host y usuario de la conexión) solo va al log.
            logger.exception("No se pudo calcular el reporte de telemetría [%s, %s).", start, end)
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, REPORT_UNAVAILABLE_DETAIL) from error
        logger.info(
            "Reporte de telemetría [%s, %s) calculado en %.0f ms (%s).",
            start.isoformat(),
            end.isoformat(),
            (time.perf_counter() - started) * 1000,
            ", ".join(f"{name}={len(rows)}" for name, rows in metrics.items()),
        )
        return TelemetryReport.model_validate(
            {"period": {"from": start, "to": end}, "generated_at": now, "metrics": metrics}
        )

    return report_cache.get_or_compute((start_date, end_date), compute)
