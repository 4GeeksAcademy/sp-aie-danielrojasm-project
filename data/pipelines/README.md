# `data/pipelines` folder

This folder groups **all data pipelines in the monorepo** related to the company: ingestion, ETL/ELT, cleaning, transformation, and loading into analytical or production systems.

Each subfolder or file under `data/pipelines/` should represent **one pipeline or job set** (for example `sales-etl`, `telemetry-stream`, `customer-segmentation`) and include the required configuration (scripts, orchestration, connectors, schemas, etc.).

- **Main purpose**: consolidate in one place the data movement and transformation logic that powers the company’s applications and analytics.
- **Recommendation**: document pipelines as you add them—their goal, data sources and sinks, dependencies, and how to run them in development, testing, and production.

## Pipelines

- **`weekly_warehouse_client_performance`** (implemented, Prefect 3): weekly per-warehouse, per-client rollup for the executive report, written to `reporting.weekly_warehouse_client_performance`. Run it from the repo root with `uv run python data/pipelines/pipeline.py` (`--serve` for the Monday 02:00 UTC schedule). The main flow coordinates extraction, transformation and load subflows; task unit tests live in `tests/pipelines/test_pipeline.py` and the dashboard in `uis/backoffice` → `/reporting`. Design and run commands (in Spanish) in [PIPELINE_DESIGN.md](./PIPELINE_DESIGN.md).

> _Spanish version: [README.es.md](./README.es.md)._
