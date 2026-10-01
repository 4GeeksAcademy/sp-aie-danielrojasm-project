# Carpeta `data/pipelines`

Esta carpeta agrupa **todos los pipelines de datos del monorepo** relacionados con la compañía: procesos de ingesta, ETL/ELT, limpieza, transformación y carga hacia sistemas analíticos o de producción.

Cada subcarpeta o archivo dentro de `data/pipelines/` debe representar **un pipeline o conjunto de jobs** (por ejemplo `sales-etl`, `telemetry-stream`, `customer-segmentation`) e incluir la configuración necesaria (scripts, orquestación, conectores, esquemas, etc.).

- **Propósito principal**: unificar en un único lugar la lógica de movimiento y transformación de datos que soporta las aplicaciones y analíticas de la compañía.
- **Recomendación**: documenta aquí los pipelines que vayas añadiendo, describiendo su objetivo, orígenes/destinos de datos, dependencias y cómo ejecutarlos en desarrollo, pruebas y producción.

## Pipelines

- **`weekly_warehouse_client_performance`** (implementado, Prefect 3): consolidado semanal por almacén y cliente para el reporte ejecutivo, en `reporting.weekly_warehouse_client_performance`. Se ejecuta desde la raíz con `uv run python data/pipelines/pipeline.py` (`--serve` para la programación de los lunes a las 02:00 UTC). Diseño y comandos en [PIPELINE_DESIGN.md](./PIPELINE_DESIGN.md).
