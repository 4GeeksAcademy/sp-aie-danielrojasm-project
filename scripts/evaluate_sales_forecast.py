"""Evaluación técnica del modelo de pronóstico de ingresos: validación cruzada temporal y curva de aprendizaje.

Uso (desde la raíz del monorepo):

    uv run python scripts/evaluate_sales_forecast.py

Solo usa el entrenamiento 2016–2023; la prueba 2024–2025 queda reservada para la evaluación final de
`scripts/train_sales_forecast.py`. Mismo Random Forest y mismas features que ese script.

1. Validación cruzada con `TimeSeriesSplit` (5 folds de ventana creciente, validación de 12 meses: 2019…2023).
   Cada fold reconstruye sus features solo con sus meses (ver `data/process/forecast_validation.py`).
2. Curva de aprendizaje: validación fija en 2023 y entrenamiento con las 6, 12, … 60 filas más recientes.
3. MAE, RMSE y MSE en EUR y en % del ingreso mensual medio, para entrenamiento, validación a un paso y
   validación recursiva (12 meses sin ver ingresos reales), con media ± desviación estándar entre folds.
4. Pruebas del diagnóstico con la misma CV: barrido de `min_samples_leaf` (¿regularizar baja la validación?)
   y corrección del nivel anual con la regla de crecimiento alterno de TrackFlow (acción correctiva propuesta).

Escribe en `data/eval/`: `learning_curve.png`, `evaluation_metrics.json`, `cv_folds.csv` y `learning_curve.csv`.
"""

import json
import logging
import sys
import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.process.forecast_validation import (  # noqa: E402
    N_SPLITS,
    VALIDATION_MONTHS,
    FitModel,
    Fold,
    Predictor,
    cross_validate,
    error_metrics,
    learning_curve,
    recursive_forecast,
    temporal_folds,
)
from data.process.sales_forecast import (  # noqa: E402
    MIN_HISTORY,
    TARGET,
    build_training_matrix,
    fill_missing,
    load_sales,
    split_train_test,
)
from scripts.train_sales_forecast import FOREST_PARAMS, seasonal_naive_forecast, train_model  # noqa: E402


logger = logging.getLogger("trackflow.sales_forecast")

OUTPUT_DIR = ROOT / "data" / "eval"
SUBSETS = ("train", "validation_one_step", "validation_recursive")
METRICS = ("mae_eur", "rmse_eur", "mse_eur2", "mae_pct_of_mean_revenue", "rmse_pct_of_mean_revenue", "bias_pct")
LEARNING_CURVE_SIZES = list(range(6, 61, 6))
REGULARIZATION_LEAVES = (1, 2, 4, 6)


def make_fit(params: dict = FOREST_PARAMS) -> FitModel:
    def fit(X: pd.DataFrame, y: pd.Series) -> Predictor:
        # Con pocas filas algún mes no queda fuera de ningún árbol y sklearn avisa de que el R² OOB no es fiable;
        # la evaluación no usa el OOB, así que el aviso solo ensucia el log.
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=UserWarning, message=".*out-of-bag.*")
            return train_model(X, y, params).predict

    return fit


def mean_std(records: list[dict[str, float]]) -> dict[str, dict[str, float]]:
    """Media ± desviación estándar (muestral, ddof=1) entre folds de cada métrica."""
    frame = pd.DataFrame.from_records(records)
    return {metric: {"mean": float(frame[metric].mean()), "std": float(frame[metric].std())} for metric in METRICS}


def summarize(folds: pd.DataFrame) -> dict[str, dict[str, dict[str, float]]]:
    return {subset: mean_std(folds.loc[folds["subset"] == subset].to_dict("records")) for subset in SUBSETS}


def regularization_sweep(train: pd.DataFrame, folds: list[Fold]) -> dict[str, dict]:
    """Misma CV con hojas mínimas de 1, 2 (producción), 4 y 6 meses.

    Si el modelo sobreajustara, regularizar (hojas más grandes) bajaría el error de validación.
    """
    sweep = {}
    for leaf in REGULARIZATION_LEAVES:
        summary = summarize(cross_validate(train, make_fit({**FOREST_PARAMS, "min_samples_leaf": leaf}), folds))
        sweep[f"min_samples_leaf={leaf}"] = {
            subset: {metric: summary[subset][metric] for metric in ("mae_pct_of_mean_revenue", "rmse_pct_of_mean_revenue")}
            for subset in SUBSETS
        }
    return sweep


def alternating_growth_adjustment(history: np.ndarray, forecast: np.ndarray) -> tuple[np.ndarray, dict[str, float]]:
    """Reescala un pronóstico de 12 meses al crecimiento anual que da la regla de alternancia.

    El crecimiento anual de TrackFlow alterna entre ~9 % y ~3 % (ver `data/eval/evaluation_report.md`), así que el
    del año siguiente se estima como `2 · media histórica − crecimiento del último año`, solo con años cerrados de
    `history`.
    El bosque conserva la forma estacional; solo cambia el nivel del año.
    """
    annual = history[len(history) % 12 :].reshape(-1, 12).sum(axis=1)
    growth = annual[1:] / annual[:-1] - 1
    expected = 2 * growth.mean() - growth[-1]
    implied = forecast.sum() / annual[-1] - 1
    return forecast * (1 + expected) / (1 + implied), {
        "last_year_growth_pct": 100 * float(growth[-1]),
        "model_implied_growth_pct": 100 * float(implied),
        "rule_growth_pct": 100 * float(expected),
    }


def growth_adjusted_cv(train: pd.DataFrame, folds: list[Fold]) -> tuple[list[dict], list[dict]]:
    """Validación recursiva por fold sin y con `alternating_growth_adjustment` (solo meses de antes del fold)."""
    revenue = train[TARGET].to_numpy(dtype=float)
    mean_revenue = float(revenue.mean())
    fit = make_fit()
    plain, adjusted = [], []
    for fold in folds:
        history = revenue[: fold.validation[0]]
        X, y = build_training_matrix(train.iloc[: fold.validation[0]])
        forecast = recursive_forecast(fit(X, y), history, train.index[fold.validation])
        corrected, growth = alternating_growth_adjustment(history, forecast)
        actual = revenue[fold.validation]
        real_growth = {"real_growth_pct": 100 * float(actual.sum() / history[-12:].sum() - 1)}
        plain.append({"fold": fold.number, **growth, **real_growth, **error_metrics(actual, forecast, mean_revenue)})
        adjusted.append({"fold": fold.number, **error_metrics(actual, corrected, mean_revenue)})
    return plain, adjusted


def plot_learning_curve(curve: pd.DataFrame, naive: dict[str, float], validation_period: str, path: Path) -> None:
    ink, muted, grid = "#0b0b0b", "#8a8984", "#e6e5e0"
    styles = {
        "train": ("Entrenamiento (in-sample)", "#2a78d6", "-", "o"),
        "validation_one_step": (f"Validación a un paso ({validation_period})", "#d9622b", "-", "o"),
        "validation_recursive": (f"Validación recursiva 12 meses ({validation_period})", "#d9622b", "--", "s"),
    }
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), dpi=150, sharex=True)
    fig.patch.set_facecolor("#fcfcfb")
    for ax, metric, title in zip(axes, ("mae_pct_of_mean_revenue", "rmse_pct_of_mean_revenue"), ("MAE", "RMSE")):
        ax.set_facecolor("#fcfcfb")
        for subset, (label, color, linestyle, marker) in styles.items():
            rows = curve[curve["subset"] == subset]
            ax.plot(rows["train_rows"], rows[metric], color=color, linestyle=linestyle, marker=marker, markersize=4, linewidth=2, label=label)
        ax.axhline(naive[metric], color=muted, linestyle=":", linewidth=1.5, label="Baseline estacional (validación recursiva)")
        ax.set_title(f"{title} en % del ingreso mensual medio", loc="left", fontsize=11, color=ink)
        ax.set_xlabel("Meses de entrenamiento (filas con features)", color=ink)
        ax.set_ylim(bottom=0)
        ax.grid(axis="y", color=grid, linewidth=0.8)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(grid)
        ax.tick_params(colors=muted)
    axes[0].legend(loc="upper right", frameon=False, fontsize=8)
    fig.suptitle("TrackFlow · Curva de aprendizaje del Random Forest (revenue_eur, consolidated)", x=0.01, ha="left", fontsize=13, color=ink)
    fig.tight_layout()
    fig.savefig(path, facecolor=fig.get_facecolor())
    plt.close(fig)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    train = fill_missing(split_train_test(load_sales()).train)
    revenue = train[TARGET].to_numpy(dtype=float)
    mean_revenue = float(revenue.mean())

    folds = temporal_folds(len(train))
    for fold in folds:
        logger.info(
            "Fold %d: entrenamiento %s–%s (%d filas), validación %s–%s",
            fold.number, f"{train.index[fold.train[0]]:%Y-%m}", f"{train.index[fold.train[-1]]:%Y-%m}",
            len(fold.train) - MIN_HISTORY, f"{train.index[fold.validation[0]]:%Y-%m}", f"{train.index[fold.validation[-1]]:%Y-%m}",
        )
    cv = cross_validate(train, make_fit(), folds)
    summary = summarize(cv)

    naive_by_fold = [
        error_metrics(revenue[fold.validation], seasonal_naive_forecast(revenue[: fold.validation[0]], len(fold.validation)), mean_revenue)
        for fold in folds
    ]
    growth_plain, growth_adjusted = growth_adjusted_cv(train, folds)

    last = folds[-1].validation
    validation_period = f"{train.index[last[0]]:%Y-%m}..{train.index[last[-1]]:%Y-%m}"
    curve = learning_curve(train, make_fit(), LEARNING_CURVE_SIZES, last)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    metrics = {
        "model": "RandomForestRegressor",
        "params": FOREST_PARAMS,
        "target": f"{TARGET} (market = consolidated)",
        "cv": {"strategy": "TimeSeriesSplit", "n_splits": N_SPLITS, "validation_months": VALIDATION_MONTHS, "shuffle": False},
        "mean_train_revenue_eur": mean_revenue,
        "cv_summary": summary,
        "cv_seasonal_naive_recursive": mean_std(naive_by_fold),
        "cv_regularization_sweep": regularization_sweep(train, folds),
        "cv_alternating_growth_adjustment": {
            "by_fold": [
                {**plain, **{f"adjusted_{metric}": adjusted[metric] for metric in METRICS}}
                for plain, adjusted in zip(growth_plain, growth_adjusted)
            ],
            "recursive": mean_std(growth_plain),
            "recursive_adjusted": mean_std(growth_adjusted),
        },
        "learning_curve_validation_period": validation_period,
        "learning_curve_seasonal_naive": naive_by_fold[-1],
    }
    (OUTPUT_DIR / "evaluation_metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    cv.round(4).to_csv(OUTPUT_DIR / "cv_folds.csv", index=False)
    curve.round(4).to_csv(OUTPUT_DIR / "learning_curve.csv", index=False)
    plot_learning_curve(curve, naive_by_fold[-1], validation_period, OUTPUT_DIR / "learning_curve.png")

    for subset in SUBSETS:
        s = summary[subset]
        logger.info(
            "CV %-21s MAE %.2f ± %.2f %% · RMSE %.2f ± %.2f %% del ingreso medio · sesgo %+.2f %%",
            subset, s["mae_pct_of_mean_revenue"]["mean"], s["mae_pct_of_mean_revenue"]["std"],
            s["rmse_pct_of_mean_revenue"]["mean"], s["rmse_pct_of_mean_revenue"]["std"], s["bias_pct"]["mean"],
        )
    for label, block in (
        ("baseline estacional", metrics["cv_seasonal_naive_recursive"]),
        ("recursiva + crecimiento", metrics["cv_alternating_growth_adjustment"]["recursive_adjusted"]),
    ):
        logger.info(
            "CV %-23s MAE %.2f ± %.2f %% · RMSE %.2f ± %.2f %%", label,
            block["mae_pct_of_mean_revenue"]["mean"], block["mae_pct_of_mean_revenue"]["std"],
            block["rmse_pct_of_mean_revenue"]["mean"], block["rmse_pct_of_mean_revenue"]["std"],
        )
    logger.info("Salidas en %s", OUTPUT_DIR.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
