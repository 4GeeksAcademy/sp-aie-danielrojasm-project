import csv
import io
import logging
import os

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from services.api.incidents_analyzer import InvalidCsvError, analyze_csv, result_rows
from services.api.routes.auth import router as auth_router
from services.api.routes.incidents import (
    IncidentValidationError,
    handle_incident_validation_error,
    handle_request_validation_error,
    is_incidents_path,
)
from services.api.routes.incidents import router as incidents_router
from services.api.routes.profiles import router as profiles_router
from services.api.routes.suppliers import router as suppliers_router
from services.api.routes.users import router as users_router
from services.api.security import get_current_user


logger = logging.getLogger("trackflow.api")

allowed_origins = {os.getenv("BACKOFFICE_ORIGIN", "http://localhost:3002")}
codespace_name = os.getenv("CODESPACE_NAME")
if codespace_name:
    forwarding_domain = os.getenv(
        "GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN", "app.github.dev"
    )
    allowed_origins.add(f"https://{codespace_name}-3002.{forwarding_domain}")

app = FastAPI(title="TrackFlow API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(allowed_origins),
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(profiles_router)
app.include_router(suppliers_router)
app.include_router(incidents_router)
app.add_exception_handler(IncidentValidationError, handle_incident_validation_error)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request, error: RequestValidationError
) -> JSONResponse:
    # Las rutas de incidencias responden 400 con el campo afectado; el resto
    # de la API conserva el 422 estándar de FastAPI que ya consumen sus clientes.
    if is_incidents_path(request):
        return await handle_request_validation_error(request, error)
    return await request_validation_exception_handler(request, error)


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, error: Exception) -> JSONResponse:
    logger.exception("Error no controlado en %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Se produjo un error interno. Inténtalo de nuevo en unos minutos."
        },
    )


latest_analysis: dict[str, object] | None = None


@app.get("/", include_in_schema=False)
def health_check() -> dict[str, str]:
    return {"service": "TrackFlow Incidents API", "status": "ok"}


@app.post("/api/incidents/analyze", dependencies=[Depends(get_current_user)])
def analyze_incidents(file: UploadFile = File(...)) -> dict[str, object]:
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
    return summary


@app.get(
    "/api/incidents/results/export",
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