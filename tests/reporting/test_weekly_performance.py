"""Reglas de cálculo de los cuatro KPIs (`data/process/weekly_performance.py`), sin base de datos."""

from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

from data.process.weekly_performance import (
    DISCREPANCY,
    INBOUND,
    OUTBOUND,
    OUTPUT_COLUMNS,
    STOCKOUT,
    compute_weekly_performance,
    contract_violations,
    last_closed_week,
    reconcile,
    week_start_of,
)
from tests.reporting.helpers import LA, ZGZ, at, make_event


WEEK = date(2026, 9, 21)  # lunes
NEXT_WEEK = WEEK + timedelta(weeks=1)


def frame(*events: dict) -> pd.DataFrame:
    """Eventos como los devuelve la extracción: claves de `tags` en columnas."""
    rows = []
    for event in events:
        tags = event["tags"]
        rows.append(
            {
                "id": event["id"],
                "event_type": event["event_type"],
                "timestamp": event["timestamp"],
                "received_at": event["received_at"],
                "quantity": tags.get("quantity"),
                **{key: tags.get(key) for key in ("warehouse", "client_id", "exit_type", "order_id", "count_id", "product_id", "stock_level", "triggering_order_id")},
            }
        )
    return pd.DataFrame(rows)


def single_row(result) -> dict:
    assert len(result.rows) == 1, result.rows
    return result.rows.iloc[0].to_dict()


def test_computes_the_four_kpis_as_defined_in_the_context():
    result = compute_weekly_performance(
        frame(
            make_event(INBOUND, at(WEEK), order_id=1, quantity=40, **ZGZ),
            make_event(INBOUND, at(WEEK, 30), order_id=2, quantity=25, **ZGZ),
            make_event(OUTBOUND, at(WEEK, 40), order_id=10, exit_type="dispatch", quantity=3, **ZGZ),
            make_event(OUTBOUND, at(WEEK, 41), order_id=11, exit_type="dispatch", quantity=1, **ZGZ),
            make_event(OUTBOUND, at(WEEK, 42), order_id=12, exit_type="dispatch", quantity=1, **ZGZ),
            make_event(STOCKOUT, at(WEEK, 42), product_id="SKU-1", stock_level="low", triggering_order_id=12, **ZGZ),
            make_event(STOCKOUT, at(WEEK, 42), product_id="SKU-1", stock_level="out", triggering_order_id=12, **ZGZ),
            make_event(DISCREPANCY, at(WEEK, 50), count_id=7, **ZGZ),
        ),
        [WEEK],
    )

    assert single_row(result) == {
        "warehouse": "zaragoza",
        "client_id": "purestep-footwear",
        "week_start": WEEK,
        "inbound_units_count": 65,  # suma de unidades, no conteo de eventos
        "outbound_orders_count": 3,
        "stockout_events_count": 2,  # `low` y `out` son dos avisos distintos
        "discrepancy_events_count": 1,
        "discrepancy_rate": 0.3333,  # 1 / 3 con 4 decimales
    }
    assert list(result.rows.columns) == OUTPUT_COLUMNS


def test_losses_are_not_orders_and_the_rate_is_zero_without_dispatches():
    result = compute_weekly_performance(
        frame(
            make_event(OUTBOUND, at(WEEK), order_id=10, exit_type="loss", quantity=2, **ZGZ),
            make_event(DISCREPANCY, at(WEEK, 2), count_id=7, **ZGZ),
        ),
        [WEEK],
    )

    row = single_row(result)
    assert row["outbound_orders_count"] == 0
    assert row["discrepancy_rate"] == 0
    assert result.events_by_type[WEEK][f"{OUTBOUND}_loss"] == 1
    assert result.events_by_type[WEEK][f"{OUTBOUND}_dispatch"] == 0


def test_rate_above_one_is_not_clipped():
    result = compute_weekly_performance(
        frame(
            make_event(OUTBOUND, at(WEEK), order_id=10, exit_type="dispatch", **ZGZ),
            make_event(DISCREPANCY, at(WEEK, 1), count_id=1, **ZGZ),
            make_event(DISCREPANCY, at(WEEK, 2), count_id=2, **ZGZ),
        ),
        [WEEK],
    )

    assert single_row(result)["discrepancy_rate"] == 2.0


def test_one_row_per_warehouse_and_client_never_aggregated_across_clients():
    other_client = {"warehouse": "zaragoza", "client_id": "nordic-home"}
    result = compute_weekly_performance(
        frame(
            make_event(INBOUND, at(WEEK), order_id=1, quantity=10, **ZGZ),
            make_event(INBOUND, at(WEEK), order_id=2, quantity=20, **other_client),
            make_event(INBOUND, at(WEEK), order_id=3, quantity=30, **LA),
        ),
        [WEEK],
    )

    by_key = {(row.warehouse, row.client_id): row.inbound_units_count for row in result.rows.itertuples()}
    assert by_key == {
        ("los_angeles", "fashion-co"): 30,
        ("zaragoza", "nordic-home"): 20,
        ("zaragoza", "purestep-footwear"): 10,
    }


def test_duplicates_by_event_id_and_by_business_key_count_once():
    original = make_event(INBOUND, at(WEEK), order_id=1, quantity=40, **ZGZ)
    reemitted = make_event(INBOUND, at(WEEK), received_at=at(WEEK, 5), order_id="1", quantity=40, **ZGZ)
    result = compute_weekly_performance(
        frame(
            original,
            original,  # mismo eventId dos veces
            reemitted,  # mismo pedido con otro eventId
            make_event(DISCREPANCY, at(WEEK), count_id=7, **ZGZ),
            make_event(DISCREPANCY, at(WEEK), count_id=7, **ZGZ),
        ),
        [WEEK],
    )

    assert single_row(result)["inbound_units_count"] == 40
    assert single_row(result)["discrepancy_events_count"] == 1
    assert result.duplicates_dropped == 3
    assert result.max_received_at[WEEK] == original["received_at"]


def test_rows_without_valid_dimensions_are_rejected_not_imputed():
    result = compute_weekly_performance(
        frame(
            make_event(INBOUND, at(WEEK), order_id=1, quantity=40, **ZGZ),
            make_event(INBOUND, at(WEEK), order_id=2, quantity=5, warehouse="LA", client_id="fashion-co"),
            make_event(INBOUND, at(WEEK), order_id=3, quantity=5, warehouse="zaragoza", client_id="Bad Client"),
            make_event(INBOUND, at(WEEK), order_id=4, warehouse="zaragoza", client_id="purestep-footwear"),
            make_event(OUTBOUND, at(WEEK), order_id=5, exit_type="return", **ZGZ),
        ),
        [WEEK],
    )

    assert single_row(result)["inbound_units_count"] == 40
    assert result.rows_rejected == 4


def test_weeks_are_iso_weeks_in_utc_and_only_target_weeks_count():
    sunday_night = datetime(2026, 9, 27, 23, 59, tzinfo=timezone.utc)
    monday_midnight = datetime(2026, 9, 28, 0, 0, tzinfo=timezone.utc)
    los_angeles_sunday = datetime(2026, 9, 27, 18, 0, tzinfo=timezone(timedelta(hours=-7)))  # lunes 01:00 UTC

    result = compute_weekly_performance(
        frame(
            make_event(INBOUND, sunday_night, order_id=1, quantity=1, **ZGZ),
            make_event(INBOUND, monday_midnight, order_id=2, quantity=10, **ZGZ),
            make_event(INBOUND, los_angeles_sunday, order_id=3, quantity=100, **ZGZ),
            make_event(INBOUND, at(WEEK - timedelta(weeks=5)), order_id=4, quantity=1000, **ZGZ),
        ),
        [WEEK, NEXT_WEEK],
    )

    by_week = dict(zip(result.rows["week_start"], result.rows["inbound_units_count"], strict=True))
    assert by_week == {WEEK: 1, NEXT_WEEK: 110}
    assert result.rows_rejected == 0  # fuera de las semanas objetivo no es un rechazo


def test_no_events_gives_no_rows_and_zeroed_counters():
    result = compute_weekly_performance(frame(), [WEEK])

    assert result.rows.empty
    assert result.events_by_type == {WEEK: dict.fromkeys(result.events_by_type[WEEK], 0)}
    assert result.max_received_at == {WEEK: None}


def test_week_helpers():
    assert week_start_of(datetime(2026, 10, 1, 17, tzinfo=timezone.utc)) == date(2026, 9, 28)
    assert last_closed_week(datetime(2026, 10, 1, tzinfo=timezone.utc)) == date(2026, 9, 21)
    assert last_closed_week(datetime(2026, 9, 28, 0, 0, tzinfo=timezone.utc)) == date(2026, 9, 21)


def kpi_row(**overrides) -> dict:
    return {
        "warehouse": "zaragoza",
        "client_id": "purestep-footwear",
        "week_start": WEEK,
        "inbound_units_count": 10,
        "outbound_orders_count": 4,
        "stockout_events_count": 0,
        "discrepancy_events_count": 1,
        "discrepancy_rate": 0.25,
        **overrides,
    }


def test_contracts_accept_valid_rows():
    assert contract_violations(pd.DataFrame([kpi_row()]), [WEEK], NEXT_WEEK) == []


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ([kpi_row(), kpi_row()], "repiten"),
        ([kpi_row(discrepancy_rate=0.5)], "discrepancy_rate"),
        ([kpi_row(inbound_units_count=-1)], "negativos"),
        ([kpi_row(week_start=NEXT_WEEK)], "semana en curso"),
        ([kpi_row(warehouse="LA")], "almacenes"),
    ],
)
def test_contracts_reject_broken_rows(rows, message):
    problems = contract_violations(pd.DataFrame(rows), [WEEK, NEXT_WEEK], NEXT_WEEK)
    assert any(message in problem for problem in problems), problems


def test_reconciliation_flags_movements_without_events():
    rows = pd.DataFrame([kpi_row(inbound_units_count=10, outbound_orders_count=1, discrepancy_events_count=0, discrepancy_rate=0.0)])
    movements = pd.DataFrame(
        [
            {"measure": "inbound_units", "warehouse": "zaragoza", "created_at": at(WEEK), "amount": 10},
            {"measure": "dispatched_orders", "warehouse": "zaragoza", "created_at": at(WEEK), "amount": 1},
        ]
    )

    assert reconcile(rows, movements, [WEEK])[WEEK]["status"] == "ok"

    lost = pd.concat(
        [movements, pd.DataFrame([{"measure": "dispatched_orders", "warehouse": "zaragoza", "created_at": at(WEEK, 3), "amount": 1}])]
    )
    detail = reconcile(rows, lost, [WEEK])[WEEK]
    assert detail["status"] == "gap"
    assert detail["warehouses"]["zaragoza"]["dispatched_orders"] == {"events": 1, "domain": 2}
