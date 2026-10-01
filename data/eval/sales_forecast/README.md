# Pronóstico de ingresos mensuales — evaluación del modelo

Responde a la RFI de Finanzas: ¿se pueden predecir los ingresos de los próximos meses a partir del histórico, con un error aceptable,
antes de construir un dashboard ejecutivo? Con este dataset, **sí**: pronosticando 24 meses seguidos sin ver ningún dato real de
esos meses, el modelo se desvía de media un **3,0 %** del ingreso de cada mes (MAPE), frente al 7,3 % de la regla manual de
"mismo mes del año pasado × crecimiento".

## Cómo reproducirlo

```bash
uv sync
uv run python scripts/train_sales_forecast.py          # entrena, evalúa y escribe esta carpeta
uv run pytest tests/pipelines/test_sales_forecast.py   # split 8/2, fuga de datos y métricas
```

Semilla fija (`random_state=42`): dos ejecuciones dan los mismos números.

| Archivo | Contenido |
|---|---|
| `metrics.json` | Métricas del modelo y del baseline, cobertura de la banda, importancia de las features |
| `predictions.csv` | Por mes de prueba: real, pronóstico, percentiles 5/10/90/95 y baseline |
| `forecast.png` | Pronóstico y banda de variabilidad frente a los ingresos reales de 2024–2025 |

## Datos y split

- Fuente: `data/raw/trackflow_sales.csv`, filas `market = "consolidated"`, 120 meses (2016-01 a 2025-12). Target: `revenue_eur`.
- **Entrenamiento: 2016–2023 (8 años, 96 meses). Prueba: 2024–2025 (2 años, 24 meses).** El split es por año natural y falla si
  los años no están completos o no son exactamente 10 (`data/process/sales_forecast.py`).
- Nulos: el CSV actual no tiene ninguno. Si aparecen, un `revenue_eur` no numérico o no positivo y un mes ausente se tratan como
  nulos; en entrenamiento se imputan por interpolación temporal **solo con datos de entrenamiento**, y en prueba esos meses se
  excluyen de las métricas. Ambos casos quedan en el log.
- `shipments_processed` y `avg_revenue_per_shipment_eur` no se usan como features: se conocen a la vez que el ingreso del mes
  (`revenue ≈ envíos × ingreso medio`), así que usarlas sería predecir con el resultado.

## Modelo

**Target normalizado.** Un modelo de árboles no puede predecir valores mayores que los que vio, y la serie crece ~6 % al año: todo
2024–2025 está por encima del entrenamiento. Por eso el modelo predice el índice `ingreso del mes / media de los 12 meses previos`
(estacionario) y el resultado se multiplica por esa media para volver a euros. Esta es la normalización que importa; además, las
features pasan por un `StandardScaler` ajustado solo con el entrenamiento.

**Features causales** (cada mes solo usa meses anteriores):

| Feature | Qué recoge | Importancia |
|---|---|---|
| `month_of_year` | Calendario del e-commerce: pico de noviembre–diciembre, valle de febrero | 0,52 |
| `last_year_index` | Índice del mismo mes del año anterior | 0,42 |
| `recent_momentum` | Media de los 3 últimos meses frente a la de 12 | 0,04 |
| `trailing_growth` | Crecimiento interanual de la media de 12 meses | 0,03 |

**Pronóstico recursivo.** Desde diciembre de 2023 se pronostican los 24 meses de prueba uno a uno; cada pronóstico se usa como
historia del siguiente. El modelo nunca recibe un ingreso real de 2024–2025, ni siquiera como lag: es el escenario real de Finanzas.

**Banda de variabilidad.** La recursión se repite con cada uno de los 500 árboles por separado, y la banda son los percentiles
10–90 y 5–95 de esas 500 trayectorias. Así la banda se ensancha con el horizonte, porque el error de cada mes se arrastra al siguiente.

### Por qué Random Forest y no XGBoost

- **Pocos datos:** 72 filas de entrenamiento útiles (los primeros 24 meses son historia para los lags). Con este tamaño, la
  ventaja de precisión de XGBoost no compensa su riesgo de sobreajuste ni su ajuste (learning rate, profundidad, regularización,
  early stopping), que además necesitaría apartar más meses para validar.
- **Explicabilidad para Finanzas:** "la media de 500 árboles, cada uno entrenado con una muestra distinta del histórico" se
  explica en una reunión, y la importancia de las features sale directamente.
- **Variabilidad incluida:** los árboles son independientes, así que su dispersión da la banda sin entrenar modelos de cuantiles.
  En XGBoost los árboles se corrigen en cadena y no forman una muestra de predicciones.
- **Validación sin tocar la prueba:** el R² out-of-bag (0,879 sobre el índice) mide el ajuste con las filas que cada árbol no vio.
- La falta de extrapolación afecta a los dos algoritmos por igual y se resuelve con el target normalizado, no cambiando de modelo.

## Resultados sobre la prueba (2024–2025, 24 meses)

Ingreso mensual medio de la prueba: **1.299.073 €**.

| Métrica | Random Forest | Baseline estacional | Cómo leerla |
|---|---|---|---|
| **MSE** | 1,98·10⁹ EUR² | 1,16·10¹⁰ EUR² | Error cuadrático medio; penaliza mucho los fallos grandes |
| RMSE (raíz del MSE) | 44.458 € · **3,4 %** del ingreso medio | 107.935 € · 8,3 % | El MSE en euros: el fallo típico de un mes |
| MAPE | **3,0 %** | 7,3 % | Desviación media de cada mes, en % de su ingreso |
| Sesgo | −0,05 % | −7,0 % | Negativo = el modelo sobreestima en promedio |
| **PSI** (pronóstico vs real) | **0,078** | 0,740 | < 0,10: la distribución pronosticada es como la real |
| **Gini** normalizado | **0,918** | 0,921 | 1 = ordena los meses de mayor a menor igual que la realidad |
| **K2 Score** (R²) | **0,932** | 0,602 | Parte de la variación real de un mes a otro que explica el modelo |
| K² de D'Agostino (residuos) | 3,73 (p = 0,15) | 1,44 (p = 0,49) | p > 0,05: residuos compatibles con ruido normal |

Cobertura de la banda: el **79 %** de los meses reales cae dentro de p10–p90 (nominal 80 %) y el **100 %** dentro de p5–p95.

### Qué mide cada métrica

- **MSE:** media de los errores al cuadrado, en EUR². Penaliza un mes con un fallo grande más que varios con fallos pequeños, pero
  sus unidades no se pueden explicar a nadie; por eso se reporta también su raíz (RMSE) en euros y en % del ingreso medio.
- **MAPE:** la métrica para Finanzas: "de media, el pronóstico de cada mes se desvía un 3 % del ingreso real".
- **PSI (Population Stability Index):** compara cómo se reparten dos conjuntos de valores entre los mismos intervalos (cuartiles
  del real). Aquí detecta si el modelo pronostica una mezcla de meses altos y bajos distinta de la real. Para la deriva de los
  datos se calcula también entre el índice estacional de entrenamiento y el de prueba: **0,078**, el patrón estacional de 2024–2025
  es el mismo que el de 2016–2023.
- **Gini normalizado:** mide si el modelo ordena bien los meses (un febrero bajo frente a un noviembre alto), sin importar el
  nivel. Es lo que permite distinguir un mes flojo esperado de una caída atípica que haya que investigar.
- **K2 Score:** se interpreta como el R² (`r2_score`): 1 explica toda la variación entre meses y 0 no mejora a predecir siempre la
  media. Como "K²" también es el nombre del test de normalidad de D'Agostino-Pearson, se reporta además sobre los residuos.

### Por qué un MSE bajo no basta

- **No dice si es bajo:** sin una referencia, 1,98·10⁹ EUR² no significa nada. Frente a la regla estacional (1,16·10¹⁰), el modelo
  reduce el MSE 5,9 veces; ese contraste es lo que justifica el modelo.
- **Esconde el sesgo:** un MSE moderado puede venir de sobreestimar todos los meses, que es lo peor para planificar caja. El
  baseline sobreestima un 7 %; el modelo, un 0,05 %.
- **No dice si ordena bien los meses:** el Gini y el R² sí. El caso inverso también ocurre: el baseline ordena igual de bien
  (Gini 0,921) pero falla el nivel, así que ninguna métrica sola basta.
- **Puede venir de memorizar el pasado:** un MSE medido sobre el entrenamiento o con lags reales de los meses de prueba sale
  bajo sin que el modelo sepa pronosticar. Aquí se mide sobre dos años no vistos y en recursión.
- **No dice nada de la incertidumbre:** la banda y su cobertura sí.

## Límites

- **24 meses de prueba son pocos.** El PSI depende de cuántos intervalos se usen: con la regla de al menos 6 meses por intervalo
  salen 4 (0,078); forzando 5 intervalos sube a 0,39. Es una señal, no una prueba estadística.
- **La mezcla Los Ángeles / Zaragoza no se puede medir:** el CSV solo trae la fila `consolidated`. Si cambia el reparto ~60/40
  entre países, el modelo no lo verá hasta que se refleje en el total; hace falta el desglose por mercado para monitorizarlo.
- **La banda refleja la incertidumbre del modelo, no shocks externos:** una pérdida de un cliente grande o un cambio de tarifas
  queda fuera de lo que el histórico puede anticipar.
- **El horizonte importa:** el error se acumula en la recursión; para el dashboard conviene reentrenar cada mes con el dato real
  más reciente.
