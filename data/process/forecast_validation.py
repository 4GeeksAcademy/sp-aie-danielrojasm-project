"""Validación cruzada temporal y curva de aprendizaje del pronóstico de ingresos mensuales.

Todo trabaja sobre el entrenamiento (2016–2023, fila `consolidated`): la prueba 2024–2025 no se toca.

Fuga de información entre folds. Las features de `sales_forecast.feature_row` son causales (el mes `t` solo
lee ingresos anteriores a `t`), pero aun así cada fold las reconstruye desde cero con su propio tramo:

- Entrenamiento del fold: `build_training_matrix` recibe solo los meses de entrenamiento del fold, así que
  ningún lag ni media móvil puede leer un mes de validación ni posterior.
- Validación a un paso: el mes `t` usa los ingresos reales anteriores a `t` (entrenamiento del fold y meses
  de validación ya cerrados), nunca `t` ni meses posteriores.
- Validación recursiva: el escenario real de Finanzas. Solo se conoce el entrenamiento del fold y cada mes
  pronosticado alimenta los lags del siguiente; no entra ningún ingreso real de la validación.

Las métricas se calculan en EUR: el modelo predice el índice `revenue_t / base_t` y se multiplica por `base_t`.
"""

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.model_selection import TimeSeriesSplit

from data.process.sales_forecast import MIN_HISTORY, TARGET, build_training_matrix, feature_row


N_SPLITS = 5
VALIDATION_MONTHS = 12  # un año completo por fold: cada validación recorre febrero y noviembre–diciembre

Predictor = Callable[[np.ndarray], np.ndarray]
FitModel = Callable[[pd.DataFrame, pd.Series], Predictor]


@dataclass(frozen=True)
class Fold:
    number: int
    train: np.ndarray  # posiciones de meses, en orden
    validation: np.ndarray


def temporal_folds(n_months: int, n_splits: int = N_SPLITS, validation_months: int = VALIDATION_MONTHS) -> list[Fold]:
    """Folds de ventana creciente (`TimeSeriesSplit`): entrena con todo lo anterior y valida el año siguiente.

    Falla si algún fold deja menos de un año de filas de entrenamiento tras reservar `MIN_HISTORY` meses
    de historia para los lags, y comprueba el orden cronológico antes de devolverlos.
    """
    splitter = TimeSeriesSplit(n_splits=n_splits, test_size=validation_months)
    folds = [
        Fold(number=i, train=train, validation=validation)
        for i, (train, validation) in enumerate(splitter.split(np.arange(n_months)), start=1)
    ]
    first_rows = len(folds[0].train) - MIN_HISTORY
    if first_rows < VALIDATION_MONTHS:
        raise ValueError(
            f"El primer fold tendría {first_rows} filas de entrenamiento; con {n_months} meses caben menos de {n_splits} folds"
        )
    assert_chronological(folds)
    return folds


def assert_chronological(folds: list[Fold]) -> None:
    """Falla si algún fold baraja meses, mezcla validación con entrenamiento o retrocede en el tiempo.

    - Entrenamiento y validación son tramos contiguos y crecientes; el entrenamiento empieza en el primer mes.
    - Todo el entrenamiento de un fold es anterior a su validación.
    - Cada validación empieza después de que termine la del fold anterior.
    """
    previous_end = -1
    for fold in folds:
        for name, positions in (("entrenamiento", fold.train), ("validación", fold.validation)):
            if len(positions) == 0 or not np.array_equal(positions, np.arange(positions[0], positions[0] + len(positions))):
                raise ValueError(f"Fold {fold.number}: el {name} no es un tramo contiguo y ordenado de meses")
        if fold.train[0] != 0:
            raise ValueError(f"Fold {fold.number}: el entrenamiento no empieza en el primer mes")
        if fold.train[-1] >= fold.validation[0]:
            raise ValueError(f"Fold {fold.number}: hay meses de entrenamiento posteriores a la validación")
        if fold.validation[0] <= previous_end:
            raise ValueError(f"Fold {fold.number}: la validación se solapa con la del fold anterior o la precede")
        previous_end = fold.validation[-1]


def error_metrics(actual: np.ndarray, predicted: np.ndarray, mean_revenue: float) -> dict[str, float]:
    """MAE, RMSE y MSE en EUR, el MAE y el RMSE también en % de `mean_revenue`, y el sesgo.

    El sesgo sigue la convención de `forecast_metrics.regression_report`: media de `actual − predicted`,
    así que negativo = el modelo sobreestima y positivo = subestima.
    """
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    mse = float(mean_squared_error(actual, predicted))
    mae = float(mean_absolute_error(actual, predicted))
    return {
        "mae_eur": mae,
        "rmse_eur": float(np.sqrt(mse)),
        "mse_eur2": mse,
        "mae_pct_of_mean_revenue": 100 * mae / mean_revenue,
        "rmse_pct_of_mean_revenue": 100 * float(np.sqrt(mse)) / mean_revenue,
        "bias_pct": 100 * float((actual - predicted).mean()) / mean_revenue,
    }


def one_step_forecast(predict: Predictor, revenue: np.ndarray, months: pd.DatetimeIndex, positions: np.ndarray) -> np.ndarray:
    """Pronóstico en EUR de cada posición con los ingresos reales anteriores a ella."""
    rows, bases = zip(*(feature_row(revenue[:position], months[position].month) for position in positions))
    return predict(np.array(rows)) * np.array(bases)


def recursive_forecast(predict: Predictor, history: np.ndarray, months: pd.DatetimeIndex) -> np.ndarray:
    """Pronóstico en EUR de `months` desde `history`, alimentando cada mes con lo pronosticado."""
    series = list(history)
    for month in months:
        features, base = feature_row(np.asarray(series), month.month)
        series.append(predict(np.array([features]))[0] * base)
    return np.asarray(series[len(history):])


def evaluate_window(
    train: pd.DataFrame, fit: FitModel, train_rows: slice, validation: np.ndarray, mean_revenue: float
) -> dict[str, dict[str, float]]:
    """Entrena con las filas `train_rows` de la matriz de features y valida en las posiciones `validation` de `train`.

    `train_rows` limita el tamaño del entrenamiento (curva de aprendizaje) sin cambiar el tramo de meses del que
    salen las features, que siempre termina justo antes de la validación.
    """
    window = train.iloc[: validation[0]]
    X, y = build_training_matrix(window)
    X, y = X.iloc[train_rows], y.iloc[train_rows]
    predict = fit(X, y)

    revenue = train[TARGET].to_numpy(dtype=float)
    fitted_actual = window.loc[X.index, TARGET].to_numpy(dtype=float)
    fitted = predict(X.to_numpy()) * fitted_actual / y.to_numpy()  # base_t = revenue_t / índice_t
    actual = revenue[validation]
    return {
        "train": error_metrics(fitted_actual, fitted, mean_revenue),
        "validation_one_step": error_metrics(actual, one_step_forecast(predict, revenue, train.index, validation), mean_revenue),
        "validation_recursive": error_metrics(
            actual, recursive_forecast(predict, revenue[: validation[0]], train.index[validation]), mean_revenue
        ),
    }


def cross_validate(train: pd.DataFrame, fit: FitModel, folds: list[Fold]) -> pd.DataFrame:
    """Una fila por fold y conjunto (`train`, `validation_one_step`, `validation_recursive`) con sus métricas."""
    mean_revenue = float(train[TARGET].mean())
    records = []
    for fold in folds:
        results = evaluate_window(train, fit, slice(None), fold.validation, mean_revenue)
        for subset, metrics in results.items():
            records.append(
                {
                    "fold": fold.number,
                    "train_period": f"{train.index[fold.train[0]]:%Y-%m}..{train.index[fold.train[-1]]:%Y-%m}",
                    "validation_period": f"{train.index[fold.validation[0]]:%Y-%m}..{train.index[fold.validation[-1]]:%Y-%m}",
                    "train_rows": len(fold.train) - MIN_HISTORY,
                    "subset": subset,
                    **metrics,
                }
            )
    return pd.DataFrame.from_records(records)


def learning_curve(train: pd.DataFrame, fit: FitModel, train_sizes: list[int], validation: np.ndarray) -> pd.DataFrame:
    """Errores al entrenar con las `n` filas más recientes antes de `validation`, para cada `n` de `train_sizes`.

    La validación es fija para que la curva solo refleje el tamaño del entrenamiento, y las filas son las
    más recientes para que no quede un hueco de meses entre entrenamiento y validación.
    """
    available = validation[0] - MIN_HISTORY
    if max(train_sizes) > available:
        raise ValueError(f"Antes de la validación solo hay {available} filas de entrenamiento")
    mean_revenue = float(train[TARGET].mean())
    records = []
    for size in train_sizes:
        results = evaluate_window(train, fit, slice(-size, None), validation, mean_revenue)
        for subset, metrics in results.items():
            records.append({"train_rows": size, "subset": subset, **metrics})
    return pd.DataFrame.from_records(records)
