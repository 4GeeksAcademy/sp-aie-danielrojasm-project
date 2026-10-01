"""Pipeline de análisis técnico de `telemetry_events` (reporte operacional).

Cada función de métrica responde una pregunta sobre la salud del sistema
(volumen, errores, latencia, autenticación), nunca de negocio, y sigue siempre
el mismo orden:

    cargar (SQL) → refinar (Pandas) → convertir tipos → agrupar → agregar → servir

- **Cargar:** solo las columnas y los `event_type` que la métrica necesita, y
  la ventana `[start, end)` aplicada una sola vez en SQL. Nunca la tabla entera.
- **Refinar:** los campos de `tags` se extraen en Pandas y las filas sin la
  dimensión se descartan antes de agrupar.
- **Convertir tipos:** `timestamp` pasa a `datetime` UTC antes de cualquier
  agrupación temporal; agrupar strings que parecen fechas da grupos erróneos
  sin ningún error visible.
- **Servir:** lista de dicts con tipos nativos de Python, serializable a JSON.

Las funciones no tienen efectos secundarios: solo leen, y con los mismos
parámetros (y los mismos datos) devuelven lo mismo. El período lo decide quien
llama (`GET /telemetry/report`); aquí no hay ventana por defecto. Los días se
agrupan en UTC.
"""

from collections.abc import Collection
from datetime import datetime
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.engine import Connection, Engine

from services.api.telemetry_storage import TelemetryEventRecord


Bind = Engine | Connection
Records = list[dict[str, Any]]

EVENTS = TelemetryEventRecord.__table__

# Fallos que mide `error_rate_by_type`, por tipo de fallo:
# - `system`: el sistema no pudo hacer su trabajo (5xx, caídas, excepciones).
# - `rejected`: el sistema rechazó una petición (credenciales, validación, reglas).
# `user_login_failed` tiene además su propia tasa en `auth_failure_rate`.
ERROR_EVENT_TYPES: dict[str, str] = {
    "api_error_occurred": "system",
    "api_call_failed": "system",
    "database_connection_failed": "system",
    "frontend_error_captured": "system",
    "password_reset_email_failed": "system",
    "user_login_failed": "rejected",
    "password_reset_failed": "rejected",
    "authorization_denied": "rejected",
    "inventory_validation_failed": "rejected",
    "product_creation_rejected": "rejected",
    "outbound_order_rejected": "rejected",
    "direct_stock_edit_rejected": "rejected",
}

LOGIN_ATTEMPT_TYPES = ("user_login_failed", "user_login_succeeded")

# Web Vitals de `page_load_recorded` (`tags`); el percentil 75 es el de referencia de Web Vitals.
PAGE_LOAD_VITALS = ("ttfb_ms", "fcp_ms", "lcp_ms", "inp_ms", "cls")


def _load(
    bind: Bind,
    start: datetime,
    end: datetime,
    columns: Collection[str],
    event_types: Collection[str] | None = None,
) -> pd.DataFrame:
    """Cargar: `timestamp >= start AND timestamp < end` (y `event_type IN (...)`) en SQL."""
    statement = select(*(EVENTS.c[name] for name in columns)).where(
        EVENTS.c.timestamp >= start, EVENTS.c.timestamp < end
    )
    if event_types is not None:
        statement = statement.where(EVENTS.c.event_type.in_(event_types))
    return pd.read_sql(statement, bind)


def _with_utc_date(frame: pd.DataFrame) -> pd.DataFrame:
    """Convertir tipos: `timestamp` a `datetime` UTC y `date` (día UTC) para agrupar."""
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame["date"] = frame["timestamp"].dt.date
    return frame


def _records(frame: pd.DataFrame) -> Records:
    """Servir: `date` como `AAAA-MM-DD` y `NaN` como `None` (JSON no admite `NaN`)."""
    if "date" in frame:
        frame["date"] = frame["date"].astype(str)
    frame = frame.astype(object).where(frame.notna(), None)
    return frame.to_dict(orient="records")


def _p75(series: pd.Series) -> float:
    return series.quantile(0.75)


def events_per_day(bind: Bind, start: datetime, end: datetime) -> Records:
    """¿Cuántos eventos llegan cada día y desde qué emisor?

    Volumen por día y `service` (`backoffice`, `api`, `job`) con las sesiones
    distintas. Un emisor que baja a cero mientras el otro sigue indica una
    instrumentación o una ingesta rota, no menos actividad.
    """
    frame = _load(bind, start, end, ("timestamp", "service", "session_id"))
    if frame.empty:
        return []
    frame = _with_utc_date(frame)
    result = (
        frame.groupby(["date", "service"])
        .agg(events=("timestamp", "count"), sessions=("session_id", "nunique"))
        .reset_index()
        .sort_values(["date", "service"])
    )
    return _records(result)


def events_by_type(bind: Bind, start: datetime, end: datetime) -> Records:
    """¿Qué tipos de evento dominan el tráfico del período y cuándo se vio cada uno por última vez?

    Un tipo que concentra el volumen marca dónde ajustar muestreo o throttle; un
    `last_seen` antiguo delata un evento que dejó de emitirse.
    """
    frame = _load(bind, start, end, ("timestamp", "event_type"))
    if frame.empty:
        return []
    frame = _with_utc_date(frame)
    result = (
        frame.groupby("event_type")
        .agg(events=("timestamp", "count"), active_days=("date", "nunique"), last_seen=("timestamp", "max"))
        .reset_index()
        .sort_values(["events", "event_type"], ascending=[False, True])
    )
    result["share"] = (result["events"] / result["events"].sum()).round(4)
    result["last_seen"] = result["last_seen"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return _records(result)


def error_rate_by_type(bind: Bind, start: datetime, end: datetime) -> Records:
    """¿Qué parte del tráfico diario son fallos y de qué tipo?

    Una fila por día y `event_type` de fallo: cuántos hubo, el total de
    eventos de ese día y su tasa. El denominador necesita todos los tipos, así
    que se cargan juntos en una sola consulta (solo dos columnas).
    """
    frame = _load(bind, start, end, ("timestamp", "event_type"))
    if frame.empty:
        return []
    frame = _with_utc_date(frame)
    frame["total_events"] = frame.groupby("date")["event_type"].transform("count")
    frame["error_kind"] = frame["event_type"].map(ERROR_EVENT_TYPES)
    errors = frame.dropna(subset=["error_kind"])
    result = (
        errors.groupby(["date", "event_type", "error_kind"])
        .agg(errors=("timestamp", "count"), total_events=("total_events", "first"))
        .reset_index()
        .sort_values(["date", "errors", "event_type"], ascending=[True, False, True])
    )
    result["error_rate"] = (result["errors"] / result["total_events"]).round(4)
    return _records(result)


def page_load_by_route(bind: Bind, start: datetime, end: datetime) -> Records:
    """¿Qué tan rápido cargan las vistas del backoffice para los usuarios reales?

    p75 diario de las Web Vitals (`page_load_recorded`) por ruta. Las métricas
    que el navegador no midió (`inp_ms` sin interacción) quedan en `None`.
    """
    frame = _load(bind, start, end, ("timestamp", "tags"), event_types=("page_load_recorded",))
    if frame.empty:
        return []
    tags = frame.pop("tags")
    frame["route"] = tags.str.get("route")
    for vital in PAGE_LOAD_VITALS:
        frame[vital] = pd.to_numeric(tags.str.get(vital), errors="coerce")
    frame = frame.dropna(subset=["route"])
    if frame.empty:
        return []
    frame = _with_utc_date(frame)
    result = (
        frame.groupby(["date", "route"])
        .agg(samples=("timestamp", "count"), **{f"{vital}_p75": (vital, _p75) for vital in PAGE_LOAD_VITALS})
        .reset_index()
        .sort_values(["date", "route"])
    )
    milliseconds = [f"{vital}_p75" for vital in PAGE_LOAD_VITALS if vital.endswith("_ms")]
    result[milliseconds] = result[milliseconds].round(1)
    result["cls_p75"] = result["cls_p75"].round(4)
    return _records(result)


def auth_failure_rate(bind: Bind, start: datetime, end: datetime) -> Records:
    """¿Qué proporción de los intentos de login falla cada día?

    `user_login_failed / (user_login_failed + user_login_succeeded)` por día.
    Un salto sostenido apunta a un ataque de fuerza bruta o a un problema con
    las credenciales de un almacén.
    """
    frame = _load(bind, start, end, ("timestamp", "event_type"), event_types=LOGIN_ATTEMPT_TYPES)
    if frame.empty:
        return []
    frame = _with_utc_date(frame)
    frame["failed"] = frame["event_type"].eq("user_login_failed")
    result = (
        frame.groupby("date")
        .agg(attempts=("failed", "count"), failed=("failed", "sum"))
        .reset_index()
        .sort_values("date")
    )
    result["succeeded"] = result["attempts"] - result["failed"]
    result["failure_rate"] = (result["failed"] / result["attempts"]).round(4)
    return _records(result)


METRICS = {
    "events_per_day": events_per_day,
    "events_by_type": events_by_type,
    "error_rate_by_type": error_rate_by_type,
    "page_load_by_route": page_load_by_route,
    "auth_failure_rate": auth_failure_rate,
}


def build_report(engine: Engine, start: datetime, end: datetime) -> dict[str, Records]:
    """Todas las métricas para la misma ventana `[start, end)`, en una sola conexión."""
    with engine.connect() as connection:
        return {name: metric(connection, start, end) for name, metric in METRICS.items()}
