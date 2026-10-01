"""Entrena y evalúa el modelo de pronóstico de ingresos mensuales de TrackFlow (Random Forest).

Uso (desde la raíz del monorepo):

    uv run python scripts/train_sales_forecast.py

Pasos:

1. Carga `data/raw/trackflow_sales.csv` (fila `consolidated`) y separa 2016–2023
   (entrenamiento) de 2024–2025 (prueba). Los nulos del entrenamiento se imputan
   solo con el propio entrenamiento.
2. Entrena un Random Forest sobre el índice `revenue_t / media de los 12 meses previos`
   (ver `data/process/sales_forecast.py`).
3. Pronostica los 24 meses de prueba de forma recursiva desde diciembre de 2023:
   cada mes pronosticado alimenta los lags del siguiente y el modelo nunca ve un
   ingreso real de 2024–2025. Es el escenario real de Finanzas: decidir hoy con
   lo que se sabe hoy.
4. La banda de variabilidad sale de repetir la recursión con cada árbol del
   bosque por separado (500 trayectorias) y tomar sus percentiles 10–90 y 5–95.
5. Calcula MSE, PSI, Gini y K2 Score sobre la prueba, los compara con un baseline
   estacional ingenuo y escribe en `data/eval/sales_forecast/` `metrics.json`,
   `predictions.csv` y `forecast.png`.

Por qué Random Forest y no XGBoost:

- Datos: 96 meses de entrenamiento, 72 filas útiles tras reservar 24 meses de
  historia para los lags. Con tan pocas filas la ventaja de precisión del boosting
  no compensa su riesgo de sobreajuste ni su ajuste de hiperparámetros (learning
  rate, profundidad, regularización, early stopping), que además necesitaría
  apartar más meses de validación.
- Explicabilidad: el stakeholder es Finanzas/Dirección. "La predicción es la media
  de 500 árboles, cada uno entrenado con una muestra distinta del histórico" se
  explica en una reunión; la importancia de las features es directa.
- Variabilidad nativa: los árboles son independientes, así que su dispersión da
  la banda de incertidumbre sin entrenar modelos de cuantiles aparte; en XGBoost
  los árboles se corrigen en cadena y no forman una muestra de predicciones.
- Validación sin tocar la prueba: el error out-of-bag mide el ajuste con las
  filas que cada árbol no vio.
- Limitación común a ambos: ningún modelo de árboles extrapola la tendencia de
  crecimiento; se resuelve normalizando el target, no cambiando de algoritmo.
"""

import json
import logging
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.ensemble import RandomForestRegressor  # noqa: E402
from sklearn.pipeline import Pipeline  # noqa: E402
from sklearn.preprocessing import StandardScaler  # noqa: E402

# `python scripts/train_sales_forecast.py` solo pone `scripts/` en sys.path; `data` se importa desde la raíz.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.process.forecast_metrics import population_stability_index, regression_report  # noqa: E402
from data.process.sales_forecast import (  # noqa: E402
    BASE_WINDOW,
    FEATURE_COLUMNS,
    TARGET,
    build_training_matrix,
    feature_row,
    fill_missing,
    load_sales,
    split_train_test,
)


logger = logging.getLogger("trackflow.sales_forecast")

RANDOM_STATE = 42
OUTPUT_DIR = ROOT / "data" / "eval" / "sales_forecast"
FOREST_PARAMS = {
    "n_estimators": 500,
    "min_samples_leaf": 2,  # hojas de al menos 2 meses: suaviza el ruido mensual de ±5 %
    "max_features": 1.0,
    "oob_score": True,
    "random_state": RANDOM_STATE,
}
BAND_PERCENTILES = (5, 10, 90, 95)


def train_model(X: pd.DataFrame, y: pd.Series) -> Pipeline:
    # El escalado no cambia los cortes de un árbol, pero deja todas las features en la
    # misma magnitud por contrato (el mes 1–12 frente a índices ~1,0) y se ajusta solo
    # con el entrenamiento. La normalización que sí importa es la del target.
    model = Pipeline([("scale", StandardScaler()), ("forest", RandomForestRegressor(**FOREST_PARAMS))])
    model.fit(X.to_numpy(), y.to_numpy())
    return model


def recursive_forecast(model: Pipeline, history: np.ndarray, months: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray]:
    """Pronóstico central (bosque completo) y una trayectoria por árbol, alimentando cada mes con lo pronosticado."""
    scaler: StandardScaler = model.named_steps["scale"]
    trees = model.named_steps["forest"].estimators_

    central = list(history)
    paths = np.tile(history, (len(trees), 1)).tolist()
    for month in months:
        features, base = feature_row(np.asarray(central), month.month)
        central.append(model.predict(np.array([features]))[0] * base)

        rows, bases = zip(*(feature_row(np.asarray(path), month.month) for path in paths))
        scaled = scaler.transform(np.array(rows))
        for path, tree, row, path_base in zip(paths, trees, scaled, bases):
            path.append(tree.predict(row.reshape(1, -1))[0] * path_base)

    horizon = len(months)
    return np.asarray(central[-horizon:]), np.asarray(paths)[:, -horizon:]


def seasonal_naive_forecast(history: np.ndarray, horizon: int) -> np.ndarray:
    """Baseline: mismo mes del año anterior × crecimiento interanual de los últimos 12 meses."""
    growth = history[-BASE_WINDOW:].sum() / history[-2 * BASE_WINDOW : -BASE_WINDOW].sum()
    series = list(history)
    for _ in range(horizon):
        series.append(series[-BASE_WINDOW] * growth)
    return np.asarray(series[-horizon:])


def seasonal_index(revenue: pd.Series) -> pd.Series:
    """Ingreso de cada mes frente a la media de sus 12 meses previos (solo con valores reales)."""
    return (revenue / revenue.shift(1).rolling(BASE_WINDOW).mean()).dropna()


def plot_forecast(train: pd.DataFrame, result: pd.DataFrame, path: Path) -> None:
    ink, muted, grid, accent = "#0b0b0b", "#8a8984", "#e6e5e0", "#2a78d6"
    context = train[TARGET].iloc[-24:] / 1e6
    months = result.index
    fig, ax = plt.subplots(figsize=(11, 5.5), dpi=150)
    fig.patch.set_facecolor("#fcfcfb")
    ax.set_facecolor("#fcfcfb")

    ax.fill_between(months, result["p05"] / 1e6, result["p95"] / 1e6, color=accent, alpha=0.12, linewidth=0, label="Rango p5–p95")
    ax.fill_between(months, result["p10"] / 1e6, result["p90"] / 1e6, color=accent, alpha=0.22, linewidth=0, label="Rango p10–p90")
    ax.plot(context.index, context, color=muted, linewidth=2, label="Real (entrenamiento)")
    ax.plot(months, result["actual"] / 1e6, color=ink, linewidth=2, marker="o", markersize=4, label="Real (prueba)")
    ax.plot(months, result["forecast"] / 1e6, color=accent, linewidth=2, label="Pronóstico Random Forest")
    ax.axvline(months[0] - pd.Timedelta(days=15), color=muted, linewidth=1, linestyle="--")
    ax.text(months[0], ax.get_ylim()[1], "  inicio de la prueba: el modelo no ve datos reales desde aquí", color=muted, fontsize=9, va="top")

    ax.set_title("TrackFlow · Ingresos mensuales consolidados: pronóstico 2024–2025 vs real", loc="left", fontsize=13, color=ink)
    ax.set_ylabel("Millones de EUR", color=ink)
    ax.grid(axis="y", color=grid, linewidth=0.8)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(grid)
    ax.tick_params(colors=muted)
    ax.legend(loc="upper left", frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(path, facecolor=fig.get_facecolor())
    plt.close(fig)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    sales = load_sales()
    split = split_train_test(sales)
    train = fill_missing(split.train)
    X, y = build_training_matrix(train)
    model = train_model(X, y)
    forest: RandomForestRegressor = model.named_steps["forest"]
    logger.info("Random Forest entrenado con %d filas; R² out-of-bag del índice: %.3f", len(X), forest.oob_score_)

    history = train[TARGET].to_numpy(dtype=float)
    central, paths = recursive_forecast(model, history, split.test.index)
    bands = np.percentile(paths, BAND_PERCENTILES, axis=0)
    result = pd.DataFrame(
        {
            "actual": split.test[TARGET],
            "forecast": central,
            **{f"p{p:02d}": band for p, band in zip(BAND_PERCENTILES, bands)},
            "seasonal_naive": seasonal_naive_forecast(history, len(split.test)),
        },
        index=split.test.index,
    )

    evaluated = result.dropna(subset=["actual"])
    if len(evaluated) < len(result):
        logger.warning("%d meses de prueba sin dato real: se excluyen de las métricas", len(result) - len(evaluated))
    actual = evaluated["actual"].to_numpy()
    index_train, index_all = seasonal_index(train[TARGET]), seasonal_index(sales[TARGET])
    metrics = {
        "model": "RandomForestRegressor",
        "params": FOREST_PARAMS,
        "features": list(FEATURE_COLUMNS),
        "train_period": f"{split.train.index[0]:%Y-%m}..{split.train.index[-1]:%Y-%m}",
        "test_period": f"{split.test.index[0]:%Y-%m}..{split.test.index[-1]:%Y-%m}",
        "train_rows": len(X),
        "test_months_evaluated": len(evaluated),
        "oob_r2_revenue_index": float(forest.oob_score_),
        "feature_importance": dict(zip(FEATURE_COLUMNS, forest.feature_importances_.round(4).tolist())),
        "random_forest": regression_report(actual, evaluated["forecast"].to_numpy()),
        "seasonal_naive_baseline": regression_report(actual, evaluated["seasonal_naive"].to_numpy()),
        "band_coverage_pct": {
            "p10_p90": 100 * float(((actual >= evaluated["p10"]) & (actual <= evaluated["p90"])).mean()),
            "p05_p95": 100 * float(((actual >= evaluated["p05"]) & (actual <= evaluated["p95"])).mean()),
        },
        # Deriva del patrón estacional entre entrenamiento y prueba, con valores reales.
        "psi_seasonal_index_train_vs_test": population_stability_index(
            index_train.to_numpy(), index_all.loc[split.test.index].dropna().to_numpy()
        ),
        "mean_test_revenue_eur": float(actual.mean()),
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    result.round(2).rename_axis("month").to_csv(OUTPUT_DIR / "predictions.csv", date_format="%Y-%m-%d")
    plot_forecast(train, result, OUTPUT_DIR / "forecast.png")

    rf, naive = metrics["random_forest"], metrics["seasonal_naive_baseline"]
    logger.info(
        "Prueba 2024–2025 · RF: MSE=%.4g EUR² (RMSE %.2f %% del ingreso medio), MAPE=%.2f %%, PSI=%.3f, Gini=%.3f, K2(R²)=%.3f",
        rf["mse_eur2"], rf["rmse_pct_of_mean_revenue"], rf["mape_pct"], rf["psi_predicted_vs_actual"],
        rf["gini_normalized"], rf["k2_score_r2"],
    )
    logger.info("Baseline estacional: RMSE %.2f %%, MAPE=%.2f %%, K2(R²)=%.3f", naive["rmse_pct_of_mean_revenue"], naive["mape_pct"], naive["k2_score_r2"])
    logger.info("Cobertura de la banda p10–p90: %.0f %%; p5–p95: %.0f %%", *metrics["band_coverage_pct"].values())
    logger.info("Salidas en %s", OUTPUT_DIR.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
