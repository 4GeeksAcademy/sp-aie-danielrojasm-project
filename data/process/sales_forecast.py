"""Preparación de la serie mensual de ingresos para el modelo de pronóstico de ventas.

Lee `data/raw/trackflow_sales.csv` (fila `consolidated`), valida el esquema y el
rango mensual, separa los primeros 8 años como entrenamiento y los 2 más
recientes como prueba, y construye features causales: cada fila de features del
mes `t` solo usa ingresos de meses anteriores a `t`.

Normalización del target: los árboles de decisión no extrapolan, y la serie
crece ~6 % al año, así que los años de prueba quedan por encima de todo lo visto
en entrenamiento. Por eso el modelo no predice euros sino el índice
`revenue_t / base_t`, donde `base_t` es la media de los 12 meses previos. Ese
índice es estacionario (recoge estacionalidad y crecimiento reciente) y se
vuelve a euros multiplicando por `base_t`.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


logger = logging.getLogger("trackflow.sales_forecast")

SALES_CSV = Path(__file__).resolve().parents[1] / "raw" / "trackflow_sales.csv"
SALES_COLUMNS = ("month", "revenue_eur", "shipments_processed", "avg_revenue_per_shipment_eur", "market")
NUMERIC_COLUMNS = ("revenue_eur", "shipments_processed", "avg_revenue_per_shipment_eur")
TARGET = "revenue_eur"
MARKET = "consolidated"

TRAIN_YEARS = 8
TEST_YEARS = 2
BASE_WINDOW = 12  # meses de la media móvil que normaliza el target
# Meses de historia que necesita la primera fila de features: base_{t-12} usa t-24..t-13.
MIN_HISTORY = 2 * BASE_WINDOW
FEATURE_COLUMNS = ("month_of_year", "last_year_index", "trailing_growth", "recent_momentum")


class SalesDataError(ValueError):
    """El dataset de ventas no cumple el esquema o el rango esperado."""


@dataclass(frozen=True)
class SalesSplit:
    train: pd.DataFrame
    test: pd.DataFrame


def load_sales(path: Path = SALES_CSV) -> pd.DataFrame:
    """Serie mensual `consolidated` indexada por mes (DatetimeIndex, sin huecos).

    Valores no numéricos o no positivos de `revenue_eur` y meses ausentes quedan
    como NaN: se imputan después del split (`fill_missing`) para que la prueba
    nunca alimente la imputación del entrenamiento.
    """
    raw = pd.read_csv(path)
    missing = [column for column in SALES_COLUMNS if column not in raw.columns]
    if missing:
        raise SalesDataError(f"{path.name}: faltan las columnas {missing}; se esperaban {list(SALES_COLUMNS)}")

    frame = raw.loc[raw["market"] == MARKET, list(SALES_COLUMNS)].copy()
    if frame.empty:
        raise SalesDataError(f"{path.name}: no hay filas con market='{MARKET}'")

    frame["month"] = pd.to_datetime(frame["month"], format="%Y-%m-%d", errors="coerce")
    if frame["month"].isna().any():
        raise SalesDataError(f"{path.name}: {int(frame['month'].isna().sum())} filas con `month` inválido (formato YYYY-MM-01)")
    if (frame["month"].dt.day != 1).any():
        raise SalesDataError(f"{path.name}: `month` debe ser el primer día del mes")
    duplicated = frame["month"].duplicated()
    if duplicated.any():
        raise SalesDataError(f"{path.name}: meses repetidos {frame.loc[duplicated, 'month'].dt.strftime('%Y-%m').tolist()}")

    for column in NUMERIC_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    non_positive = frame[TARGET] <= 0
    if non_positive.any():
        logger.warning("revenue_eur no positivo en %d meses: se trata como nulo", int(non_positive.sum()))
        frame.loc[non_positive, TARGET] = np.nan

    frame = frame.set_index("month").sort_index().drop(columns="market")
    full_range = pd.date_range(frame.index.min(), frame.index.max(), freq="MS", name="month")
    absent = full_range.difference(frame.index)
    if len(absent):
        logger.warning("Meses ausentes en el CSV (quedan como nulos): %s", absent.strftime("%Y-%m").tolist())
    frame = frame.reindex(full_range)

    nulls = frame[TARGET].isna().sum()
    if nulls:
        logger.warning("%d meses sin revenue_eur válido", int(nulls))
    return frame


def split_train_test(frame: pd.DataFrame, train_years: int = TRAIN_YEARS, test_years: int = TEST_YEARS) -> SalesSplit:
    """Primeros `train_years` años naturales para entrenar, últimos `test_years` para probar.

    Exige años completos (enero a diciembre) y exactamente `train_years + test_years`
    años, para que la regla 8/2 no dependa de cuántas filas traiga el CSV.
    """
    index = frame.index
    if not frame.index.is_monotonic_increasing or frame.index.has_duplicates:
        raise SalesDataError("El índice mensual debe ser creciente y sin repetidos")
    if index[0].month != 1 or index[-1].month != 12:
        raise SalesDataError(
            f"Se necesitan años completos: la serie va de {index[0]:%Y-%m} a {index[-1]:%Y-%m}"
        )
    years = sorted(index.year.unique())
    if len(years) != train_years + test_years:
        raise SalesDataError(f"Se esperaban {train_years + test_years} años y hay {len(years)} ({years[0]}–{years[-1]})")

    first_test_year = years[train_years]
    train = frame.loc[index.year < first_test_year].copy()
    test = frame.loc[index.year >= first_test_year].copy()
    logger.info(
        "Split: entrenamiento %s–%s (%d meses), prueba %s–%s (%d meses)",
        f"{train.index[0]:%Y-%m}", f"{train.index[-1]:%Y-%m}", len(train),
        f"{test.index[0]:%Y-%m}", f"{test.index[-1]:%Y-%m}", len(test),
    )
    return SalesSplit(train=train, test=test)


def fill_missing(frame: pd.DataFrame) -> pd.DataFrame:
    """Imputa nulos interpolando en el tiempo, solo con las filas del propio conjunto.

    Los extremos sin vecino se rellenan con el valor más cercano. Se aplica al
    entrenamiento; en la prueba los meses sin dato real se excluyen de las métricas.
    """
    nulls = int(frame[list(NUMERIC_COLUMNS)].isna().sum().sum())
    if not nulls:
        return frame
    logger.warning("Imputando %d valores nulos por interpolación temporal", nulls)
    filled = frame.copy()
    filled[list(NUMERIC_COLUMNS)] = filled[list(NUMERIC_COLUMNS)].interpolate(method="time").ffill().bfill()
    return filled


def feature_row(history: np.ndarray, month_of_year: int) -> tuple[list[float], float]:
    """Features y `base_t` del mes siguiente a `history` (ingresos hasta t-1, en orden).

    - `month_of_year`: 1..12, la estacionalidad del calendario de e-commerce.
    - `last_year_index`: índice del mismo mes del año anterior (revenue_{t-12} / base_{t-12}).
    - `trailing_growth`: crecimiento interanual de la media de 12 meses (base_t / base_{t-12}).
    - `recent_momentum`: media de los 3 últimos meses frente a `base_t`.
    """
    if len(history) < MIN_HISTORY:
        raise ValueError(f"Hacen falta {MIN_HISTORY} meses de historia y hay {len(history)}")
    base = history[-BASE_WINDOW:].mean()
    base_last_year = history[-2 * BASE_WINDOW : -BASE_WINDOW].mean()
    last_year_index = history[-BASE_WINDOW] / base_last_year
    features = [
        float(month_of_year),
        last_year_index,
        base / base_last_year,
        history[-3:].mean() / base,
    ]
    return features, base


def build_training_matrix(train: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Features `X` e índice objetivo `y = revenue_t / base_t` de cada mes de `train` con historia suficiente.

    Solo lee `train`: la fila del mes `t` usa los ingresos de `train` anteriores a `t`.
    """
    revenue = train[TARGET].to_numpy(dtype=float)
    if np.isnan(revenue).any():
        raise SalesDataError("El entrenamiento tiene nulos: aplica `fill_missing` antes")
    rows, targets = [], []
    for position in range(MIN_HISTORY, len(revenue)):
        features, base = feature_row(revenue[:position], train.index[position].month)
        rows.append(features)
        targets.append(revenue[position] / base)
    index = train.index[MIN_HISTORY:]
    return pd.DataFrame(rows, columns=list(FEATURE_COLUMNS), index=index), pd.Series(targets, index=index, name="revenue_index")
