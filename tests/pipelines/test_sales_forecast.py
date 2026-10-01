"""Split 8/2 años, ausencia de fuga de datos y métricas del modelo de pronóstico de ventas.

Los tests del split usan el CSV real (`data/raw/trackflow_sales.csv`, 2016-01..2025-12);
los de validación construyen CSV mínimos en `tmp_path`.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from data.process.forecast_metrics import normalized_gini, population_stability_index
from data.process.sales_forecast import (
    MIN_HISTORY,
    SALES_COLUMNS,
    TARGET,
    SalesDataError,
    build_training_matrix,
    fill_missing,
    load_sales,
    split_train_test,
)


@pytest.fixture(scope="module")
def sales() -> pd.DataFrame:
    return load_sales()


def write_sales_csv(path: Path, months: pd.DatetimeIndex, revenue: list[float] | None = None) -> Path:
    revenue = revenue if revenue is not None else [1_000_000.0 + 1_000 * i for i in range(len(months))]
    frame = pd.DataFrame(
        {
            "month": months.strftime("%Y-%m-%d"),
            "revenue_eur": revenue,
            "shipments_processed": 70_000,
            "avg_revenue_per_shipment_eur": 15.0,
            "market": "consolidated",
        },
        columns=list(SALES_COLUMNS),
    )
    frame.to_csv(path, index=False)
    return path


def test_dataset_matches_expected_schema_and_range(sales: pd.DataFrame) -> None:
    assert list(sales.columns) == ["revenue_eur", "shipments_processed", "avg_revenue_per_shipment_eur"]
    assert sales.index[0] == pd.Timestamp("2016-01-01")
    assert sales.index[-1] == pd.Timestamp("2025-12-01")
    assert len(sales) == 120
    assert (sales[TARGET] > 0).all()


def test_split_uses_first_eight_years_for_training_and_last_two_for_test(sales: pd.DataFrame) -> None:
    split = split_train_test(sales)

    assert sorted(split.train.index.year.unique()) == list(range(2016, 2024))
    assert sorted(split.test.index.year.unique()) == [2024, 2025]
    assert len(split.train) == 8 * 12
    assert len(split.test) == 2 * 12


def test_split_has_no_overlap_and_keeps_temporal_order(sales: pd.DataFrame) -> None:
    split = split_train_test(sales)

    assert split.train.index.intersection(split.test.index).empty
    assert split.train.index.max() < split.test.index.min()
    assert split.train.index.append(split.test.index).equals(sales.index)


def test_training_matrix_does_not_change_when_test_years_change(sales: pd.DataFrame) -> None:
    """Fuga de datos: si los años de prueba fueran otros, el entrenamiento sería idéntico."""
    altered = sales.copy()
    altered.loc[altered.index.year >= 2024, TARGET] *= 10

    X, y = build_training_matrix(split_train_test(sales).train)
    X_altered, y_altered = build_training_matrix(split_train_test(altered).train)

    pd.testing.assert_frame_equal(X, X_altered)
    pd.testing.assert_series_equal(y, y_altered)
    assert X.index.max() < pd.Timestamp("2024-01-01")


def test_features_only_use_past_months(sales: pd.DataFrame) -> None:
    """Cambiar el ingreso del mes t solo puede cambiar el target de t y las features de meses posteriores."""
    train = split_train_test(sales).train
    changed_month = train.index[MIN_HISTORY + 20]
    altered = train.copy()
    altered.loc[changed_month, TARGET] *= 2

    X, y = build_training_matrix(train)
    X_altered, y_altered = build_training_matrix(altered)

    upto = X.index <= changed_month
    pd.testing.assert_frame_equal(X[upto], X_altered[upto])
    pd.testing.assert_series_equal(y[X.index < changed_month], y_altered[X.index < changed_month])
    assert y[changed_month] != y_altered[changed_month]


def test_split_rejects_incomplete_years(tmp_path: Path) -> None:
    csv = write_sales_csv(tmp_path / "sales.csv", pd.date_range("2016-01-01", "2025-11-01", freq="MS"))

    with pytest.raises(SalesDataError, match="años completos"):
        split_train_test(load_sales(csv))


def test_split_rejects_wrong_number_of_years(tmp_path: Path) -> None:
    csv = write_sales_csv(tmp_path / "sales.csv", pd.date_range("2015-01-01", "2025-12-01", freq="MS"))

    with pytest.raises(SalesDataError, match="Se esperaban 10 años"):
        split_train_test(load_sales(csv))


def test_load_sales_rejects_missing_columns(tmp_path: Path) -> None:
    csv = tmp_path / "sales.csv"
    pd.DataFrame({"month": ["2016-01-01"], "revenue_eur": [1.0]}).to_csv(csv, index=False)

    with pytest.raises(SalesDataError, match="faltan las columnas"):
        load_sales(csv)


def test_missing_months_and_invalid_revenue_become_nulls_and_are_imputed(tmp_path: Path) -> None:
    months = pd.date_range("2016-01-01", "2016-06-01", freq="MS")
    revenue = [100.0, -5.0, 300.0, 400.0, 500.0, 600.0]
    csv = write_sales_csv(tmp_path / "sales.csv", months.delete(3), revenue[:3] + revenue[4:])

    sales = load_sales(csv)
    assert len(sales) == 6
    assert sales[TARGET].isna().sum() == 2  # febrero negativo y abril ausente

    filled = fill_missing(sales)
    assert not filled[TARGET].isna().any()
    assert filled.loc["2016-04-01", TARGET] == pytest.approx(400.0, rel=0.02)


def test_training_matrix_rejects_nulls(sales: pd.DataFrame) -> None:
    train = split_train_test(sales).train.copy()
    train.iloc[30, 0] = np.nan

    with pytest.raises(SalesDataError, match="fill_missing"):
        build_training_matrix(train)


def test_psi_is_zero_for_identical_distributions_and_grows_with_shift() -> None:
    reference = np.linspace(1.0, 2.0, 24)

    assert population_stability_index(reference, reference) == pytest.approx(0.0)
    assert population_stability_index(reference, reference + 0.5) > 0.25


def test_normalized_gini_bounds() -> None:
    actual = np.array([10.0, 30.0, 20.0, 50.0, 40.0])

    assert normalized_gini(actual, actual) == pytest.approx(1.0)
    assert normalized_gini(actual, -actual) == pytest.approx(-1.0)
