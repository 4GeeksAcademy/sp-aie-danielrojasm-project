"""`scripts/nightly_export.py`: fecha objetivo, backup CSV, subproceso del pipeline y extremo a extremo.

El pipeline real se sustituye por un subproceso de Python que deja constancia
de cada lanzamiento en un archivo: sin Prefect ni Supabase.
"""

import csv
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from scripts import nightly_export
from services.jobs import job_runner


DAY = date(2026, 9, 30)
NOW = datetime(2026, 10, 1, 1, 15, tzinfo=timezone.utc)


def fake_pipeline(directory: Path, exit_code: int = 0) -> tuple[list[str], Path]:
    """Comando que sustituye al pipeline y el archivo donde apunta cada lanzamiento."""
    calls = directory / f"pipeline-calls-exit-{exit_code}.txt"
    code = (
        f"import sys; open({str(calls)!r}, 'a').write('run\\n'); "
        f"print('Corrida fallida: PipelineAlreadyRunningError', file=sys.stderr) if {exit_code} else None; "
        f"sys.exit({exit_code})"
    )
    return [sys.executable, "-c", code], calls


def launches(calls: Path) -> int:
    return len(calls.read_text().splitlines()) if calls.exists() else 0


# ---------------------------------------------------------------------------
# Fecha objetivo
# ---------------------------------------------------------------------------

def test_target_date_defaults_to_yesterday_in_utc(monkeypatch):
    monkeypatch.delenv("TARGET_DATE", raising=False)

    assert nightly_export.resolve_target_date(NOW) == DAY
    # 23:30 en Los Ángeles ya es el día siguiente en UTC.
    late_la = datetime(2026, 10, 1, 6, 30, tzinfo=timezone.utc)
    assert nightly_export.resolve_target_date(late_la) == DAY


def test_target_date_env_overrides_the_default(monkeypatch):
    monkeypatch.setenv("TARGET_DATE", "2026-09-15")

    assert nightly_export.resolve_target_date(NOW) == date(2026, 9, 15)


@pytest.mark.parametrize("value", ["30/09/2026", "2026-13-01", "ayer"])
def test_target_date_rejects_bad_formats(monkeypatch, value):
    monkeypatch.setenv("TARGET_DATE", value)

    with pytest.raises(nightly_export.InvalidTargetDateError):
        nightly_export.resolve_target_date(NOW)


@pytest.mark.parametrize("value", ["2026-10-01", "2026-10-02"])
def test_target_date_rejects_days_not_closed(monkeypatch, value):
    monkeypatch.setenv("TARGET_DATE", value)

    with pytest.raises(nightly_export.InvalidTargetDateError, match="aún no ha cerrado"):
        nightly_export.resolve_target_date(NOW)


# ---------------------------------------------------------------------------
# Backup CSV
# ---------------------------------------------------------------------------

def test_csv_contains_only_the_target_day_in_utc(engine, insert_events, tmp_path):
    insert_events(
        datetime(2026, 9, 29, 23, 59, 59, tzinfo=timezone.utc),
        datetime(2026, 9, 30, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 9, 30, 23, 59, 59, tzinfo=timezone.utc),
        datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc),
        warehouse="zaragoza",
    )

    details = nightly_export.export_telemetry_csv(engine, DAY, tmp_path)

    path = tmp_path / "telemetry_2026-09-30.csv"
    with path.open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    assert details == {"csv_path": str(path), "csv_created": True, "rows_exported": 2}
    assert [row["timestamp"] for row in rows] == ["2026-09-30T00:00:00+00:00", "2026-09-30T23:59:59+00:00"]
    assert tuple(rows[0]) == nightly_export.CSV_COLUMNS
    assert rows[0]["tags"] == '{"warehouse": "zaragoza"}'
    assert rows[0]["event_type"] == "inbound_order_created"


def test_empty_day_still_writes_the_header(engine, tmp_path):
    details = nightly_export.export_telemetry_csv(engine, DAY, tmp_path)

    assert details["rows_exported"] == 0
    assert (tmp_path / "telemetry_2026-09-30.csv").read_text(encoding="utf-8").strip() == ",".join(nightly_export.CSV_COLUMNS)


def test_existing_csv_is_not_overwritten(engine, insert_events, tmp_path):
    path = tmp_path / "telemetry_2026-09-30.csv"
    path.write_text("snapshot previo\n", encoding="utf-8")
    insert_events(datetime(2026, 9, 30, 10, tzinfo=timezone.utc))

    details = nightly_export.export_telemetry_csv(engine, DAY, tmp_path)

    assert details == {"csv_path": str(path), "csv_created": False}
    assert path.read_text(encoding="utf-8") == "snapshot previo\n"


def test_failed_export_leaves_no_file_behind(engine, tmp_path, monkeypatch):
    def broken_writer(*_args, **_kwargs):
        raise OSError("disco lleno")

    monkeypatch.setattr(nightly_export.csv, "writer", broken_writer)

    with pytest.raises(OSError):
        nightly_export.export_telemetry_csv(engine, DAY, tmp_path)
    # Sin archivo a medias: el siguiente intento vuelve a exportar.
    assert list(tmp_path.iterdir()) == [tmp_path / "trackflow.db"]


# ---------------------------------------------------------------------------
# Subproceso del pipeline
# ---------------------------------------------------------------------------

def test_pipeline_failure_raises_with_its_last_error_line(tmp_path):
    command, calls = fake_pipeline(tmp_path, exit_code=1)

    with pytest.raises(nightly_export.PipelineFailedError, match="código 1: Corrida fallida: PipelineAlreadyRunningError"):
        nightly_export.run_pipeline(DAY, command)
    assert launches(calls) == 1


def test_pipeline_timeout_is_a_failure(tmp_path):
    command = [sys.executable, "-c", "import time; time.sleep(5)"]

    with pytest.raises(nightly_export.PipelineFailedError, match="superó"):
        nightly_export.run_pipeline(DAY, command, timeout=0.5)


def test_default_command_runs_the_pipeline_module():
    assert nightly_export.PIPELINE_COMMAND[1:4] == ["-m", "data.pipelines.pipeline", "--triggered-by"]


# ---------------------------------------------------------------------------
# Extremo a extremo
# ---------------------------------------------------------------------------

def test_run_twice_on_the_same_day_is_idempotent(engine, insert_events, tmp_path):
    insert_events(datetime(2026, 9, 30, 10, tzinfo=timezone.utc))
    command, calls = fake_pipeline(tmp_path)

    first = nightly_export.run(engine, DAY, raw_dir=tmp_path, pipeline_command=command)
    csv_after_first = (tmp_path / "telemetry_2026-09-30.csv").read_bytes()
    second = nightly_export.run(engine, DAY, raw_dir=tmp_path, pipeline_command=command)

    assert (first.outcome, second.outcome) == ("completed", "skipped_duplicate")
    assert launches(calls) == 1
    assert (tmp_path / "telemetry_2026-09-30.csv").read_bytes() == csv_after_first
    [run] = job_runner.list_runs(engine, nightly_export.JOB_NAME, DAY)
    assert run["status"] == "completed"
    assert run["details"]["rows_exported"] == 1
    assert run["details"]["pipeline_exit_code"] == 0


def test_pipeline_failure_marks_the_run_failed_and_a_retry_reuses_the_csv(engine, insert_events, tmp_path):
    insert_events(datetime(2026, 9, 30, 10, tzinfo=timezone.utc))
    failing, _ = fake_pipeline(tmp_path, exit_code=1)

    with pytest.raises(nightly_export.PipelineFailedError):
        nightly_export.run(engine, DAY, raw_dir=tmp_path, pipeline_command=failing)

    [failed] = job_runner.list_runs(engine, nightly_export.JOB_NAME, DAY)
    assert failed["status"] == "failed"
    assert failed["error_message"].startswith("PipelineFailedError: El pipeline terminó con código 1")

    working, calls = fake_pipeline(tmp_path)
    retry = nightly_export.run(engine, DAY, raw_dir=tmp_path, pipeline_command=working)
    assert retry.outcome == "completed"
    assert retry.details["csv_created"] is False
    assert launches(calls) == 1


def test_main_exit_codes(engine, tmp_path, monkeypatch):
    database = engine.url.render_as_string(hide_password=False)
    monkeypatch.setenv("DATABASE_URL", database)
    monkeypatch.setattr(nightly_export, "RAW_DIR", tmp_path)
    command, calls = fake_pipeline(tmp_path)
    monkeypatch.setattr(nightly_export, "PIPELINE_COMMAND", command)
    monkeypatch.setattr(nightly_export, "configure_logging", lambda: None)

    monkeypatch.setenv("TARGET_DATE", "2026-09-30")
    assert nightly_export.main() == 0
    assert nightly_export.main() == 0  # duplicado: omitido sin error
    assert launches(calls) == 1

    monkeypatch.setenv("TARGET_DATE", "mañana")
    assert nightly_export.main() == 2

    failing, _ = fake_pipeline(tmp_path, exit_code=1)
    monkeypatch.setattr(nightly_export, "PIPELINE_COMMAND", failing)
    monkeypatch.setenv("TARGET_DATE", "2026-09-29")
    assert nightly_export.main() == 1


def test_script_runs_as_an_independent_process_without_fastapi(tmp_path):
    """`python scripts/nightly_export.py` no carga FastAPI ni la app de `services/api`."""
    code = (
        "import runpy, sys; sys.argv = ['nightly_export.py'];"
        f"runpy.run_path({str(nightly_export.ROOT / 'scripts' / 'nightly_export.py')!r}, run_name='not_main');"
        "loaded = [name for name in sys.modules if name == 'fastapi' or name.startswith('services.api')];"
        "print(loaded)"
    )
    output = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True, cwd=tmp_path)

    assert output.stdout.strip() == "[]"
