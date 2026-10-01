"""Métricas de evaluación del pronóstico de ventas, siempre sobre el conjunto de prueba.

- MSE (EUR²) y su raíz como % del ingreso mensual medio: cuánto se equivoca el modelo.
- PSI: si la distribución de una variable cambió entre una referencia y otra muestra.
- Gini normalizado: si el modelo ordena bien los meses (temporada alta vs baja).
- K2 Score: R² (`r2_score`), proporción de la varianza real que explica el modelo.
  Como complemento se reporta el K² de D'Agostino-Pearson sobre los residuos.
"""

import numpy as np
from scipy import stats
from sklearn.metrics import mean_absolute_error, mean_absolute_percentage_error, mean_squared_error, r2_score


PSI_MIN_PER_BIN = 6  # con 24 meses de prueba salen 4 bins; con menos por bin el PSI es ruido
PSI_MAX_BINS = 10
PSI_SMOOTHING = 0.5  # suma 0,5 a cada bin: un bin vacío no dispara ln(0) en muestras pequeñas


def psi_bins(*samples: np.ndarray) -> int:
    """Número de bins: los que permitan al menos `PSI_MIN_PER_BIN` valores de la muestra más pequeña."""
    return max(2, min(PSI_MAX_BINS, min(len(sample) for sample in samples) // PSI_MIN_PER_BIN))


def _shares(values: np.ndarray, edges: np.ndarray) -> np.ndarray:
    counts = np.histogram(values, edges)[0]
    return (counts + PSI_SMOOTHING) / (len(values) + PSI_SMOOTHING * len(counts))


def population_stability_index(reference: np.ndarray, current: np.ndarray, n_bins: int | None = None) -> float:
    """PSI = Σ (p_cur − p_ref) · ln(p_cur / p_ref) con bins por cuantiles de `reference`.

    Lectura habitual: < 0,10 estable; 0,10–0,25 cambio moderado; > 0,25 cambio significativo.
    """
    reference = np.asarray(reference, dtype=float)
    current = np.asarray(current, dtype=float)
    n_bins = n_bins or psi_bins(reference, current)
    edges = np.unique(np.quantile(reference, np.linspace(0, 1, n_bins + 1)))
    edges[0], edges[-1] = -np.inf, np.inf
    ref_share, cur_share = _shares(reference, edges), _shares(current, edges)
    return float(np.sum((cur_share - ref_share) * np.log(cur_share / ref_share)))


def _gini(actual: np.ndarray, ranking: np.ndarray) -> float:
    # Ordena los valores reales de mayor a menor según `ranking` (empates: orden original)
    # y mide cuánto se aleja su curva acumulada de un orden aleatorio.
    order = np.lexsort((np.arange(len(ranking)), -ranking))
    cumulative_share = np.cumsum(actual[order]) / actual.sum()
    n = len(actual)
    return float(cumulative_share.sum() / n - (n + 1) / (2 * n))


def normalized_gini(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Gini del orden que da la predicción dividido por el del orden perfecto: 1 = ordena igual que la realidad."""
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    return _gini(actual, predicted) / _gini(actual, actual)


def regression_report(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    """Métricas de error y ajuste de `predicted` frente a `actual` (mismos meses, en EUR)."""
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    mse = mean_squared_error(actual, predicted)
    rmse = float(np.sqrt(mse))
    residuals = actual - predicted
    k2_normality = stats.normaltest(residuals)
    return {
        "mse_eur2": float(mse),
        "rmse_eur": rmse,
        "rmse_pct_of_mean_revenue": 100 * rmse / float(actual.mean()),
        "mae_eur": float(mean_absolute_error(actual, predicted)),
        "mape_pct": 100 * float(mean_absolute_percentage_error(actual, predicted)),
        "bias_pct": 100 * float(residuals.mean() / actual.mean()),
        "psi_predicted_vs_actual": population_stability_index(actual, predicted),
        "gini_normalized": normalized_gini(actual, predicted),
        "k2_score_r2": float(r2_score(actual, predicted)),
        "residuals_dagostino_k2": float(k2_normality.statistic),
        "residuals_dagostino_p_value": float(k2_normality.pvalue),
    }
