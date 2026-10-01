"""Endpoints del pipeline de desempeño de negocio: `/reporting/*`.

Módulo separado de `services/telemetry/` (el reporte técnico no cambia). Aquí
no hay lógica de ETL: cada handler valida parámetros, llama a una función de
`data/pipelines/` y construye su `response_model`.

- `GET /reporting/weekly-warehouse-client-performance`: KPIs publicados de una semana.
- `GET /reporting/pipeline-runs/latest`: estado y metadata de la última corrida.
- `POST /reporting/pipeline-runs`: disparo manual (solo `admin`). Reserva la
  corrida (`pending`, con el lock de una corrida activa), encola la tarea de
  Celery `reporting.run_weekly_performance` y responde `202` con su `task_id`.
  El flow corre en un worker aparte (`services/tasks/`), nunca en la API; el
  estado se consulta en `GET /tasks/{task_id}` y en `latest`.
"""

import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from kombu.exceptions import OperationalError as BrokerError
from redis.exceptions import RedisError
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from data.pipelines.pipeline import (
    InvalidWeekError,
    PipelineConfig,
    trigger_weekly_performance_run,
)
from data.pipelines.weekly_warehouse_client_performance import queries, runs
from data.pipelines.weekly_warehouse_client_performance.schema import has_schema
from services.api.auth_models import User, UserRole
from services.api.database import DatabaseNotConfiguredError, get_engine
from services.api.security import get_current_user
from services.reporting.models import (
    PipelineRunRead,
    PipelineRunTriggered,
    PipelineRunTriggerRequest,
    WeeklyPerformanceReport,
)
from services.tasks.pipeline import run_weekly_performance_task


logger = logging.getLogger("trackflow.reporting")

router = APIRouter(prefix="/reporting", tags=["reporting"], dependencies=[Depends(get_current_user)])

REPORTING_UNAVAILABLE_DETAIL = (
    "El reporte semanal no está disponible ahora mismo; vuelve a intentarlo en unos minutos."
)
QUEUE_UNAVAILABLE_DETAIL = (
    "La cola de tareas no está disponible; la corrida no se ha lanzado. Vuelve a intentarlo en unos minutos."
)
# Umbral del diseño. No se lee el block de Prefect aquí: en la API, sin servidor de Prefect,
# cada lectura levantaría uno temporal.
STALE_AFTER = timedelta(days=PipelineConfig().stale_after_days)


def get_reporting_engine() -> Engine:
    try:
        return get_engine()
    except DatabaseNotConfiguredError as error:
        logger.error("Reporting sin base de datos: %s", error)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, REPORTING_UNAVAILABLE_DETAIL) from error


def _unavailable(error: SQLAlchemyError, action: str) -> HTTPException:
    # La traza (con host y usuario de la conexión) solo va al log.
    logger.error("No se pudo %s: %s", action, type(error).__name__, exc_info=error)
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, REPORTING_UNAVAILABLE_DETAIL)


def _invalid(location: tuple[str, ...], message: str) -> RequestValidationError:
    return RequestValidationError([{"type": "value_error", "loc": location, "msg": message}])


@router.get(
    "/weekly-warehouse-client-performance",
    response_model=WeeklyPerformanceReport,
    responses={404: {"description": "La semana no se ha calculado."}},
)
def get_weekly_warehouse_client_performance(
    week_start: date | None = Query(
        default=None, description="Lunes (YYYY-MM-DD) de la semana. Por defecto, la última semana calculada."
    ),
    engine: Engine = Depends(get_reporting_engine),
) -> WeeklyPerformanceReport:
    if week_start is not None and week_start.weekday() != 0:
        raise _invalid(("query", "week_start"), "week_start debe ser un lunes (inicio de semana ISO).")
    try:
        report = queries.get_weekly_performance(engine, week_start)
    except SQLAlchemyError as error:
        raise _unavailable(error, "leer el reporte semanal") from error
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Esa semana todavía no se ha calculado.")
    return WeeklyPerformanceReport.model_validate(report)


@router.get(
    "/pipeline-runs/latest",
    response_model=PipelineRunRead,
    responses={404: {"description": "El pipeline nunca ha corrido."}},
)
def get_latest_pipeline_run(
    pipeline: str = Query(default=runs.PIPELINE_NAME, description="Nombre del pipeline."),
    engine: Engine = Depends(get_reporting_engine),
) -> PipelineRunRead:
    try:
        latest = (
            runs.get_latest_run(engine, pipeline, stale_after=STALE_AFTER)
            if has_schema(engine)
            else None
        )
    except SQLAlchemyError as error:
        raise _unavailable(error, "leer la última corrida") from error
    if latest is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "El pipeline todavía no ha corrido nunca.")
    return PipelineRunRead.model_validate(latest)


@router.post(
    "/pipeline-runs",
    response_model=PipelineRunTriggered,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        403: {"description": "Solo un admin puede lanzar el pipeline."},
        409: {"description": "Ya hay una corrida en curso; devuelve su `active_run_id`."},
        503: {"description": "Sin base de datos o sin cola de tareas (Redis)."},
    },
)
def trigger_pipeline_run(
    payload: PipelineRunTriggerRequest | None = None,
    current_user: User = Depends(get_current_user),
    engine: Engine = Depends(get_reporting_engine),
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo un admin puede lanzar el pipeline.")
    week_start = payload.week_start if payload is not None else None
    triggered_by = f"user:{current_user.id}"
    try:
        run_id = trigger_weekly_performance_run(engine, week_start, triggered_by)
    except InvalidWeekError as error:
        raise _invalid(("body", "week_start"), str(error)) from error
    except runs.PipelineAlreadyRunningError as error:
        logger.info("Disparo rechazado: corrida %s en curso (%s).", error.active_run_id, triggered_by)
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "detail": "Ya hay una corrida del pipeline en curso; espera a que termine.",
                "active_run_id": str(error.active_run_id) if error.active_run_id else None,
            },
        )
    except SQLAlchemyError as error:
        raise _unavailable(error, "reservar la corrida") from error
    # Mensaje ligero: solo identificadores; el worker lee los eventos de la base de datos.
    try:
        task = run_weekly_performance_task.apply_async(
            args=[str(run_id), week_start.isoformat() if week_start else None, triggered_by], retry=False
        )
    except (BrokerError, RedisError, OSError) as error:
        # Sin cola la corrida nunca se ejecutaría: se cierra para no bloquear el siguiente disparo.
        logger.error("No se pudo encolar la corrida %s: %s", run_id, type(error).__name__, exc_info=error)
        try:
            runs.fail_run(engine, run_id, error)
        except SQLAlchemyError:
            logger.exception("No se pudo cerrar la corrida %s; caducará por heartbeat.", run_id)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, QUEUE_UNAVAILABLE_DETAIL) from error
    logger.info(
        "Corrida %s del pipeline semanal encolada como tarea %s por %s (semana %s).",
        run_id,
        task.id,
        triggered_by,
        week_start,
    )
    return PipelineRunTriggered(run_id=run_id, task_id=task.id, status="pending", week_start=week_start)
