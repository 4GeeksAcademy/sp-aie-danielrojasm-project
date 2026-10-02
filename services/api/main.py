import csv
import io
import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.background import BackgroundTask, BackgroundTasks
from sqlalchemy.exc import OperationalError
from sqlmodel import SQLModel

from services.api import inventory_telemetry, telemetry
from services.api import models  # noqa: F401  registra las tablas de inventario
from services.api.telemetry_storage import api_event_buffer  # registra telemetry_events
from services.api.common_models import HealthResponse
from services.api.database import DatabaseNotConfiguredError, get_engine
from services.api.errors import internal_error_response, unprocessable_response
from services.api.incident_models import IncidentAnalysisSummary
from services.api.incidents_analyzer import InvalidCsvError, analyze_csv, result_rows
from services.api.routes.auth import router as auth_router
from services.api.routes.incidents import (
    IncidentValidationError,
    handle_incident_validation_error,
    handle_request_validation_error,
    is_incidents_path,
)
from services.api.routes.incidents import router as incidents_router
from services.api.routes.inventory import router as inventory_router
from services.api.routes.knowledge import router as knowledge_router
from services.api.routes.profiles import router as profiles_router
from services.api.routes.suppliers import router as suppliers_router
from services.api.routes.telemetry import router as telemetry_router
from services.api.routes.telemetry_report import router as telemetry_report_router
from services.api.routes.tasks import router as tasks_router
from services.api.routes.users import router as users_router
from services.api.security import get_current_user
from services.reporting.router import router as reporting_router
from services.support_agent.router import router as agent_router


logger = logging.getLogger("trackflow.api")
timing_logger = logging.getLogger("trackflow.timing")


def _configure_logging() -> None:
    # Uvicorn solo configura sus propios loggers: sin esto, los INFO de
    # `trackflow.*` (timing, caché, inventario, incidencias) no llegan a la consola.
    app_logger = logging.getLogger("trackflow")
    if app_logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s %(message)s"))
    app_logger.addHandler(handler)
    app_logger.setLevel(logging.INFO)
    app_logger.propagate = False


_configure_logging()

allowed_origins = {os.getenv("BACKOFFICE_ORIGIN", "http://localhost:3002")}
codespace_name = os.getenv("CODESPACE_NAME")
if codespace_name:
    forwarding_domain = os.getenv(
        "GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN", "app.github.dev"
    )
    allowed_origins.add(f"https://{codespace_name}-3002.{forwarding_domain}")

INVENTORY_UNAVAILABLE_DETAIL = (
    "El inventario no está disponible ahora mismo. Inténtalo de nuevo en unos minutos."
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Crea en Supabase las tablas que falten. Si la base de datos no está
    # configurada o no responde, la API arranca igual: la autenticación y el
    # resto de módulos (TinyDB) siguen funcionando y el inventario responde 503.
    try:
        SQLModel.metadata.create_all(get_engine())
        logger.info("Esquema de inventario listo en PostgreSQL.")
    except DatabaseNotConfiguredError as error:
        logger.warning("Inventario desactivado: %s", error)
    except OperationalError:
        logger.exception("No se pudo conectar con PostgreSQL al arrancar; el inventario responderá 503.")
    endpoint = telemetry.telemetry_endpoint()
    if endpoint:
        logger.info("Telemetría: ingesta en %s (%s).", endpoint, telemetry.telemetry_environment())
    else:
        logger.warning("Falta TELEMETRY_ENDPOINT: el backoffice no tendrá a dónde enviar sus eventos.")
    yield
    # Lo emitido fuera de una respuesta (p. ej. por el manejador de 500) aún está en el búfer.
    api_event_buffer.flush()


app = FastAPI(title="TrackFlow API", version="1.0.0", lifespan=lifespan)
# Los eventos que emite la API se guardan en `telemetry_events` además de ir al log.
telemetry.SINKS.append(api_event_buffer)
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(allowed_origins),
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    # X-Request-Id / X-Session-Id: correlación entre backoffice, API y logs.
    allow_headers=["Authorization", "Content-Type", "X-Request-Id", "X-Session-Id"],
    expose_headers=["X-Request-Id"],
)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(profiles_router)
app.include_router(suppliers_router)
app.include_router(incidents_router)
app.include_router(inventory_router)
app.include_router(telemetry_router)
app.include_router(telemetry_report_router)
app.include_router(reporting_router)
app.include_router(tasks_router)
app.include_router(knowledge_router)
app.include_router(agent_router)
app.add_exception_handler(IncidentValidationError, handle_incident_validation_error)


@app.middleware("http")
async def timing_middleware(request: Request, call_next):
    # Una línea por petición: la base para decidir qué cachear con datos y no por intuición.
    # El `requestId` une esa línea con los eventos de telemetría de la misma petición.
    request_id = telemetry.accept_request_id(request.headers.get("x-request-id"))
    telemetry.bind_request(request_id, telemetry.accept_session_id(request.headers.get("x-session-id")))
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    timing_logger.info(
        "%s %s -> %s | %.1fms | req=%s",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
        request_id,
    )
    response.headers["Server-Timing"] = f"app;dur={duration_ms:.1f}"
    response.headers["X-Request-Id"] = request_id
    if api_event_buffer.has_pending():
        # Un bulk insert con lo que emitió la petición, después de enviar la respuesta.
        response.background = _after(response.background, BackgroundTask(api_event_buffer.flush))
    return response


def _after(existing: BackgroundTask | None, task: BackgroundTask) -> BackgroundTask:
    if existing is None:
        return task
    tasks = BackgroundTasks()
    tasks.tasks.extend([existing, task])
    return tasks


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request, error: RequestValidationError
) -> JSONResponse:
    # Las rutas de incidencias responden 400 con el campo afectado; el resto
    # de la API conserva el formato 422 de FastAPI que ya consumen sus clientes,
    # pero sin el valor recibido (`input`), que podía incluir contraseñas.
    if is_incidents_path(request):
        return await handle_request_validation_error(request, error)
    inventory_telemetry.report_validation_error(request, error)
    return unprocessable_response(error)


@app.exception_handler(DatabaseNotConfiguredError)
async def database_not_configured_handler(
    request: Request, error: DatabaseNotConfiguredError
) -> JSONResponse:
    logger.error("%s %s: %s", request.method, request.url.path, error)
    return JSONResponse(status_code=503, content={"detail": INVENTORY_UNAVAILABLE_DETAIL})


@app.exception_handler(OperationalError)
async def database_unavailable_handler(request: Request, error: OperationalError) -> JSONResponse:
    # La traza (con host y usuario de la conexión) solo va al log.
    logger.exception("PostgreSQL no disponible en %s %s", request.method, request.url.path)
    return JSONResponse(status_code=503, content={"detail": INVENTORY_UNAVAILABLE_DETAIL})


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, error: Exception) -> JSONResponse:
    logger.exception(
        "Error no controlado en %s %s (req=%s)",
        request.method,
        request.url.path,
        telemetry.current_request_id(),
    )
    route = request.scope.get("route")
    telemetry.emit(
        "api_error_occurred",
        {
            # Plantilla de la ruta, nunca la URL con ids; sin mensaje ni traza.
            "route": getattr(route, "path", "/unmatched"),
            "http_method": request.method,
            "error_class": type(error).__name__,
        },
    )
    return internal_error_response()


latest_analysis: dict[str, object] | None = None


@app.get("/", response_model=HealthResponse, include_in_schema=False)
def health_check() -> HealthResponse:
    return HealthResponse(service="TrackFlow Incidents API", status="ok")


@app.post(
    "/api/incidents/analyze",
    response_model=IncidentAnalysisSummary,
    dependencies=[Depends(get_current_user)],
)
def analyze_incidents(file: UploadFile = File(...)) -> IncidentAnalysisSummary:
    global latest_analysis
    try:
        text_stream = io.TextIOWrapper(file.file, encoding="utf-8-sig", newline="")
        summary = analyze_csv(text_stream)
    except InvalidCsvError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except (OSError, UnicodeError) as error:
        raise HTTPException(
            status_code=400,
            detail="No se pudo leer el fichero como CSV UTF-8 válido.",
        ) from error
    finally:
        file.file.close()

    latest_analysis = summary
    return IncidentAnalysisSummary.model_validate(summary)


# Descarga CSV, no JSON: no hay modelo que serializar. Se declara el tipo de
# contenido para que `/docs` documente la respuesta real.
@app.get(
    "/api/incidents/results/export",
    response_model=None,
    response_class=StreamingResponse,
    responses={200: {"content": {"text/csv": {}}, "description": "Métricas agregadas en CSV."}},
    dependencies=[Depends(get_current_user)],
)
async def export_latest_results() -> StreamingResponse:
    if latest_analysis is None:
        raise HTTPException(status_code=404, detail="Todavía no hay resultados para exportar.")

    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(("metric", "value"))
    writer.writerows(result_rows(latest_analysis))
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="incidents-results.csv"'},
    )