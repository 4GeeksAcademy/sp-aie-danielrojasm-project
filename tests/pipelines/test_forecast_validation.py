"""Validación cruzada temporal del pronóstico de ventas: orden cronológico de los folds y sin fuga entre ellos.

Usa el entrenamiento real (`data/raw/trackflow_sales.csv`, 2016–2023). Los tests de fuga usan un predictor
trivial en lugar del Random Forest: lo que se comprueba es qué datos llegan al modelo, no su precisión.
"""

import numpy as np
import pandas as pd
import pytest

from data.process.forecast_validation import (
    Fold,
    assert_chronological,
    error_metrics,
    evaluate_window,
    one_step_forecast,
    recursive_forecast,
    temporal_folds,
)
from data.process.sales_forecast import MIN_HISTORY, TARGET, build_training_matrix, load_sales, split_train_test


@pytest.fixture(scope="module")
def train() -> pd.DataFrame:
    return split_train_test(load_sales()).train


@pytest.fixture(scope="module")
def folds(train: pd.DataFrame) -> list[Fold]:
    return temporal_folds(len(train))


def recording_fit(seen: list[pd.DataFrame]):
    """Ajuste falso: guarda la matriz de entrenamiento y predice el índice del mismo mes del año anterior."""

    def fit(X: pd.DataFrame, y: pd.Series):
        seen.append(X.copy())
        return lambda rows: np.asarray(rows)[:, 1]

    return fit


def test_folds_preserve_chronological_order(train: pd.DataFrame, folds: list[Fold]) -> None:
    """Ningún índice de un fold posterior aparece antes que uno de un fold anterior."""
    assert len(folds) == 5
    for fold in folds:
        assert np.all(np.diff(fold.train) == 1)
        assert np.all(np.diff(fold.validation) == 1)
        assert fold.train[0] == 0
        assert fold.train.max() < fold.validation.min()
        assert train.index[fold.train].is_monotonic_increasing
        assert train.index[fold.validation].is_monotonic_increasing
    for earlier, later in zip(folds, folds[1:]):
        assert earlier.validation.max() < later.validation.min()
        assert len(later.train) > len(earlier.train)
        assert later.train.max() >= earlier.validation.max()  # el fold siguiente entrena con la validación anterior


def test_folds_validate_one_calendar_year_each(train: pd.DataFrame, folds: list[Fold]) -> None:
    years = [sorted(train.index[fold.validation].year.unique()) for fold in folds]
    assert years == [[2019], [2020], [2021], [2022], [2023]]
    assert all(list(train.index[fold.validation].month) == list(range(1, 13)) for fold in folds)
    assert [len(fold.train) - MIN_HISTORY for fold in folds] == [12, 24, 36, 48, 60]


@pytest.mark.parametrize(
    "fold, message",
    [
        (Fold(1, np.array([0, 2, 1, 3]), np.array([4, 5])), "contiguo y ordenado"),
        (Fold(1, np.array([1, 2, 3]), np.array([4, 5])), "no empieza en el primer mes"),
        (Fold(1, np.array([0, 1, 2, 3]), np.array([3, 4])), "posteriores a la validación"),
    ],
)
def test_assert_chronological_rejects_shuffled_or_mixed_folds(fold: Fold, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        assert_chronological([fold])


def test_assert_chronological_rejects_folds_going_back_in_time() -> None:
    later_first = [Fold(1, np.arange(8), np.arange(8, 10)), Fold(2, np.arange(6), np.arange(6, 8))]

    with pytest.raises(ValueError, match="se solapa"):
        assert_chronological(later_first)


def test_temporal_folds_rejects_series_too_short_for_five_folds() -> None:
    with pytest.raises(ValueError, match="filas de entrenamiento"):
        temporal_folds(n_months=72)


def test_fold_training_features_never_see_validation_or_later_months(train: pd.DataFrame, folds: list[Fold]) -> None:
    """Multiplicar por 10 los ingresos desde la validación no cambia lo que recibe el modelo ni su pronóstico recursivo."""
    fold = folds[2]
    altered = train.copy()
    altered.iloc[fold.validation[0] :, altered.columns.get_loc(TARGET)] *= 10

    seen, seen_altered = [], []
    original = evaluate_window(train, recording_fit(seen), slice(None), fold.validation, 1.0)
    changed = evaluate_window(altered, recording_fit(seen_altered), slice(None), fold.validation, 1.0)

    pd.testing.assert_frame_equal(seen[0], seen_altered[0])
    assert seen[0].index.max() < train.index[fold.validation[0]]
    assert original["train"] == changed["train"]

    predict = lambda rows: np.asarray(rows)[:, 1]  # noqa: E731
    months = train.index[fold.validation]
    np.testing.assert_array_equal(
        recursive_forecast(predict, train[TARGET].to_numpy()[: fold.validation[0]], months),
        recursive_forecast(predict, altered[TARGET].to_numpy()[: fold.validation[0]], months),
    )


def test_one_step_validation_only_uses_months_before_each_prediction(train: pd.DataFrame, folds: list[Fold]) -> None:
    """Cambiar el ingreso del mes t de validación no cambia los pronósticos de t ni de los meses anteriores."""
    fold = folds[-1]
    changed = fold.validation[5]
    altered = train.copy()
    altered.iloc[changed, altered.columns.get_loc(TARGET)] *= 2

    predict = recording_fit([])(*build_training_matrix(train.iloc[: fold.validation[0]]))
    before = one_step_forecast(predict, train[TARGET].to_numpy(), train.index, fold.validation)
    after = one_step_forecast(predict, altered[TARGET].to_numpy(), train.index, fold.validation)

    np.testing.assert_array_equal(before[:6], after[:6])
    assert not np.array_equal(before[6:], after[6:])


def test_error_metrics_bias_is_negative_when_the_model_overestimates() -> None:
    actual = np.array([100.0, 200.0])
    metrics = error_metrics(actual, actual + 10, mean_revenue=150.0)

    assert metrics["mae_eur"] == pytest.approx(10.0)
    assert metrics["rmse_eur"] == pytest.approx(10.0)
    assert metrics["mse_eur2"] == pytest.approx(100.0)
    assert metrics["bias_pct"] == pytest.approx(-100 * 10 / 150)
