import csv
import io
import os

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from services.api.incidents_analyzer import InvalidCsvError, analyze_csv, result_rows


allowed_origins = {os.getenv("BACKOFFICE_ORIGIN", "http://localhost:3002")}
codespace_name = os.getenv("CODESPACE_NAME")
if codespace_name:
    forwarding_domain = os.getenv(
        "GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN", "app.github.dev"
    )
    allowed_origins.add(f"https://{codespace_name}-3002.{forwarding_domain}")

app = FastAPI(title="TrackFlow Incidents API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(allowed_origins),
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

latest_analysis: dict[str, object] | None = None


@app.get("/", include_in_schema=False)
def health_check() -> dict[str, str]:
    return {"service": "TrackFlow Incidents API", "status": "ok"}


@app.post("/api/incidents/analyze")
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


@app.get("/api/incidents/results/export")
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