"""Tasks de transformación del pipeline `weekly_warehouse_client_performance`, en aislamiento.

Cada test llama a la función de la task (`task.fn`) con eventos en memoria que
tienen la forma que devuelve `extract_business_events` (columnas de
`telemetry_events` con las claves de `tags` separadas): sin base de datos, sin
servidor de Prefect y sin APIs externas. Los valores esperados están calculados
a mano a partir de las definiciones de `CONTEXT-company.md` (sección 2 y 4).

El último test ejecuta el subflow de transformación completo con un servidor de
Prefect temporal, para comprobar que funciona por sí solo con entradas explícitas.
"""

import uuid
from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd
import pytest

from data.pipelines import pipeline
from data.process.weekly_performance import (
    DISCREPANCY,
    INBOUND,
    OUTBOUND,
    OUTPUT_COLUMNS,
    SOURCE_COLUMNS,
    STOCKOUT,
    CleanBusinessEvents,
    MalformedBusinessEventsError,
    WeeklyPerformance,
)


WEEK = date(2026, 9, 21)  # lunes de una semana ISO cerrada
CURRENT_WEEK = WEEK + timedelta(weeks=1)
ZARAGOZA = {"warehouse": "zaragoza", "client_id": "purestep-footwear"}
LOS_ANGELES = {"warehouse": "los_angeles", "client_id": "fashion-co"}


def telemetry_event(event_type: str, hours: float = 10, **tags: Any) -> dict[str, Any]:
    """Una fila de la extracción: `hours` horas después del lunes 00:00 UTC de `WEEK`."""
    timestamp = datetime(WEEK.year, WEEK.month, WEEK.day, tzinfo=timezone.utc) + timedelta(hours=hours)
    row = dict.fromkeys(SOURCE_COLUMNS)
    row.update(
        id=str(uuid.uuid4()),
        event_type=event_type,
        timestamp=timestamp,
        received_at=timestamp + timedelta(seconds=1),
        **tags,
    )
    return row


def clean(*events: dict[str, Any]) -> CleanBusinessEvents:
    return pipeline.prepare_business_events.fn(pd.DataFrame(list(events)), [WEEK])


def kpi(frame: pd.DataFrame, column: str, combination: dict[str, str]) -> Any:
    match = frame[(frame["warehouse"] == combination["warehouse"]) & (frame["client_id"] == combination["client_id"])]
    assert len(match) == 1, frame
    assert match.iloc[0]["week_start"] == WEEK
    return match.iloc[0][column]


@pytest.fixture
def zaragoza_week() -> CleanBusinessEvents:
    """Semana de Zaragoza calculable a mano:

    - Volumen de entrada: 40 + 25 = 65 unidades.
    - Throughput de salida: 4 `dispatch` (la `loss` no es un pedido).
    - Frecuencia de quiebre de stock: 3 cruces (`low` y `out` del SKU-1, `low` del SKU-2).
    - Tasa de discrepancia: 1 discrepancia / 4 pedidos = 0,25.
    """
    return clean(
        telemetry_event(INBOUND, 1, order_id="101", quantity=40, **ZARAGOZA),
        telemetry_event(INBOUND, 2, order_id="102", quantity=25, **ZARAGOZA),
        *(telemetry_event(OUTBOUND, 3 + n, order_id=f"20{n}", exit_type="dispatch", quantity=1, **ZARAGOZA) for n in range(4)),
        telemetry_event(OUTBOUND, 8, order_id="299", exit_type="loss", quantity=2, **ZARAGOZA),
        telemetry_event(STOCKOUT, 9, product_id="SKU-1", stock_level="low", triggering_order_id="203", **ZARAGOZA),
        telemetry_event(STOCKOUT, 9, product_id="SKU-1", stock_level="out", triggering_order_id="203", **ZARAGOZA),
        telemetry_event(STOCKOUT, 9, product_id="SKU-2", stock_level="low", triggering_order_id="299", **ZARAGOZA),
        telemetry_event(DISCREPANCY, 12, count_id="7", **ZARAGOZA),
    )


# ---------------------------------------------------------------------------
# Una task por KPI de CONTEXT-company.md
# ---------------------------------------------------------------------------

def test_compute_inbound_volume_sums_the_units_received(zaragoza_week):
    inbound_volume = pipeline.compute_inbound_volume.fn(zaragoza_week.events)

    assert kpi(inbound_volume, "inbound_units_count", ZARAGOZA) == 65


def test_compute_outbound_throughput_counts_dispatched_orders_not_losses(zaragoza_week):
    outbound_throughput = pipeline.compute_outbound_throughput.fn(zaragoza_week.events)

    assert kpi(outbound_throughput, "outbound_orders_count", ZARAGOZA) == 4


def test_compute_stockout_frequency_counts_every_threshold_crossing(zaragoza_week):
    stockout_frequency = pipeline.compute_stockout_frequency.fn(zaragoza_week.events)

    assert kpi(stockout_frequency, "stockout_events_count", ZARAGOZA) == 3


def test_compute_discrepancy_rate_is_discrepancies_over_dispatched_orders(zaragoza_week):
    discrepancy = pipeline.compute_discrepancy_rate.fn(zaragoza_week.events)

    assert kpi(discrepancy, "discrepancy_events_count", ZARAGOZA) == 1
    assert kpi(discrepancy, "discrepancy_rate", ZARAGOZA) == pytest.approx(1 / 4)


def test_compute_discrepancy_rate_is_zero_without_orders_and_not_clipped_above_one():
    events = clean(
        telemetry_event(DISCREPANCY, 1, count_id="1", **ZARAGOZA),
        telemetry_event(DISCREPANCY, 2, count_id="2", **LOS_ANGELES),
        telemetry_event(DISCREPANCY, 3, count_id="3", **LOS_ANGELES),
        telemetry_event(OUTBOUND, 4, order_id="1", exit_type="dispatch", quantity=1, **LOS_ANGELES),
    ).events

    discrepancy = pipeline.compute_discrepancy_rate.fn(events)

    assert kpi(discrepancy, "discrepancy_rate", ZARAGOZA) == 0  # 0 si no hubo pedidos esa semana
    assert kpi(discrepancy, "discrepancy_rate", LOS_ANGELES) == 2  # 2 / 1: la señal de "auditar aquí"


def test_weekly_row_matches_the_context_definitions_calculated_by_hand(zaragoza_week):
    events = zaragoza_week.events

    performance = pipeline.assemble_weekly_performance.fn(
        zaragoza_week,
        pipeline.compute_inbound_volume.fn(events),
        pipeline.compute_outbound_throughput.fn(events),
        pipeline.compute_stockout_frequency.fn(events),
        pipeline.compute_discrepancy_rate.fn(events),
    )

    assert isinstance(performance, WeeklyPerformance)
    assert list(performance.rows.columns) == OUTPUT_COLUMNS
    assert performance.rows.to_dict("records") == [
        {
            "warehouse": "zaragoza",
            "client_id": "purestep-footwear",
            "week_start": WEEK,
            "inbound_units_count": 65,
            "outbound_orders_count": 4,
            "stockout_events_count": 3,
            "discrepancy_events_count": 1,
            "discrepancy_rate": 0.25,
        }
    ]
    assert performance.events_by_type[WEEK][f"{OUTBOUND}_loss"] == 1


def test_one_row_per_warehouse_and_client_never_mixed_across_clients():
    other_client = {"warehouse": "zaragoza", "client_id": "nordic-home"}
    events = clean(
        telemetry_event(INBOUND, 1, order_id="1", quantity=10, **ZARAGOZA),
        telemetry_event(INBOUND, 2, order_id="2", quantity=7, **other_client),
        telemetry_event(INBOUND, 3, order_id="3", quantity=5, **LOS_ANGELES),
    ).events

    inbound_volume = pipeline.compute_inbound_volume.fn(events)

    assert len(inbound_volume) == 3
    assert kpi(inbound_volume, "inbound_units_count", ZARAGOZA) == 10
    assert kpi(inbound_volume, "inbound_units_count", other_client) == 7
    assert kpi(inbound_volume, "inbound_units_count", LOS_ANGELES) == 5


# ---------------------------------------------------------------------------
# Comportamiento defensivo ante datos inválidos o mal formados
# ---------------------------------------------------------------------------

def test_prepare_business_events_rejects_invalid_rows_instead_of_imputing_them():
    prepared = clean(
        telemetry_event(INBOUND, 1, order_id="1", quantity=12, **ZARAGOZA),
        telemetry_event(INBOUND, 2, order_id="2", quantity=30, warehouse="zaragoza", client_id=None),  # cliente nulo
        telemetry_event(INBOUND, 3, order_id="3", quantity="doce", **ZARAGOZA),  # tipo incorrecto
        telemetry_event(INBOUND, 4, order_id="4", quantity=None, **ZARAGOZA),  # cantidad nula
        telemetry_event(INBOUND, 5, order_id="5", quantity=-3, **ZARAGOZA),  # cantidad negativa
        telemetry_event(OUTBOUND, 6, order_id="6", exit_type=None, quantity=1, **ZARAGOZA),  # salida sin tipo
        telemetry_event(STOCKOUT, 7, product_id="SKU-1", stock_level="low", warehouse="madrid", client_id="fashion-co"),
    )

    assert prepared.rows_rejected == 6
    inbound_volume = pipeline.compute_inbound_volume.fn(prepared.events)
    assert kpi(inbound_volume, "inbound_units_count", ZARAGOZA) == 12
    assert set(inbound_volume["client_id"]) == {"purestep-footwear"}


def test_prepare_business_events_counts_a_reemitted_order_once():
    original = telemetry_event(OUTBOUND, 1, order_id="77", exit_type="dispatch", quantity=1, **ZARAGOZA)
    reemitted = {**original, "id": str(uuid.uuid4()), "received_at": original["received_at"] + timedelta(minutes=5)}

    prepared = clean(original, reemitted)

    assert prepared.duplicates_dropped == 1
    assert kpi(pipeline.compute_outbound_throughput.fn(prepared.events), "outbound_orders_count", ZARAGOZA) == 1


@pytest.mark.parametrize(
    "task",
    [
        pipeline.compute_inbound_volume,
        pipeline.compute_outbound_throughput,
        pipeline.compute_stockout_frequency,
        pipeline.compute_discrepancy_rate,
    ],
    ids=lambda task: task.name,
)
def test_kpi_tasks_fail_clearly_on_malformed_events(task):
    malformed = pd.DataFrame([{"event_type": INBOUND, "quantity": 3}])  # sin warehouse, client_id ni week_start

    with pytest.raises(MalformedBusinessEventsError, match="faltan las columnas"):
        task.fn(malformed)


def test_prepare_business_events_fails_clearly_when_a_source_column_is_missing():
    events = pd.DataFrame([telemetry_event(INBOUND, 1, order_id="1", quantity=4, **ZARAGOZA)]).drop(columns="client_id")

    with pytest.raises(MalformedBusinessEventsError, match="client_id"):
        pipeline.prepare_business_events.fn(events, [WEEK])


def test_malformed_events_are_not_retried():
    assert MalformedBusinessEventsError in pipeline.NON_RETRYABLE


def test_validate_weekly_performance_stops_an_inconsistent_discrepancy_rate(zaragoza_week):
    rows = pipeline.assemble_weekly_performance.fn(
        zaragoza_week,
        pipeline.compute_inbound_volume.fn(zaragoza_week.events),
        pipeline.compute_outbound_throughput.fn(zaragoza_week.events),
        pipeline.compute_stockout_frequency.fn(zaragoza_week.events),
        pipeline.compute_discrepancy_rate.fn(zaragoza_week.events),
    ).rows.assign(discrepancy_rate=0.9)
    broken = WeeklyPerformance(rows=rows, duplicates_dropped=0, rows_rejected=0)

    with pytest.raises(pipeline.ContractViolationError, match="discrepancy_rate"):
        pipeline.validate_weekly_performance.fn(uuid.uuid4(), broken, [WEEK], CURRENT_WEEK)


def test_no_events_in_the_week_gives_no_rows():
    prepared = pipeline.prepare_business_events.fn(pd.DataFrame(), [WEEK])

    rows = pipeline.compute_inbound_volume.fn(prepared.events)

    assert rows.empty
    assert (prepared.rows_rejected, prepared.duplicates_dropped) == (0, 0)


# ---------------------------------------------------------------------------
# El subflow de transformación se ejecuta por sí solo
# ---------------------------------------------------------------------------

@pytest.fixture
def prefect_server(tmp_path, monkeypatch) -> Iterator[None]:
    """Servidor de Prefect temporal; sin `DATABASE_URL`, el checkpoint de fase solo deja un aviso."""
    from prefect.settings import PREFECT_LOCAL_STORAGE_PATH, temporary_settings
    from prefect.testing.utilities import prefect_test_harness

    monkeypatch.delenv("DATABASE_URL", raising=False)
    with prefect_test_harness(), temporary_settings({PREFECT_LOCAL_STORAGE_PATH: tmp_path / "prefect-results"}):
        yield


def test_transform_subflow_runs_on_its_own_with_explicit_inputs(prefect_server):
    events = pd.DataFrame(
        [
            telemetry_event(INBOUND, 1, order_id="1", quantity=20, **LOS_ANGELES),
            telemetry_event(OUTBOUND, 2, order_id="2", exit_type="dispatch", quantity=1, **LOS_ANGELES),
            telemetry_event(DISCREPANCY, 3, count_id="5", **LOS_ANGELES),
        ]
    )

    performance = pipeline.transform_weekly_kpis_flow(uuid.uuid4(), events, [WEEK], CURRENT_WEEK)

    assert performance.rows.to_dict("records") == [
        {
            "warehouse": "los_angeles",
            "client_id": "fashion-co",
            "week_start": WEEK,
            "inbound_units_count": 20,
            "outbound_orders_count": 1,
            "stockout_events_count": 0,
            "discrepancy_events_count": 1,
            "discrepancy_rate": 1.0,
        }
    ]
