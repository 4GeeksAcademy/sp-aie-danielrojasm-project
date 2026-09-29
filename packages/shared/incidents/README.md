# `packages/shared/incidents`

Lógica de incidencias compartida (Python) entre `services/api` y `scripts/`.
Se importa desde la raíz del monorepo como `packages.shared.incidents.*`.

- `csv_validation.py` — reglas de fila del CSV del analizador
  (`validate_row`, `iter_validated_rows`, `INVALID_REASONS`). La usan
  `services/api/incidents_analyzer.py` y `scripts/seed_incidents.py`, así que
  ambos aceptan exactamente los mismos 95 registros de `incidents-trackflow.csv`.
- `domain.py` — valores permitidos del gestor (categorías,
  estados, orígenes, sedes), transiciones del ciclo de vida
  (`STATUS_TRANSITIONS`, `can_transition`) y la transformación CSV → modelo
  (`incident_from_csv_row`). La API construye sus modelos Pydantic con estos
  enums.

Los tipos de `uis/backoffice/lib/incidents.ts` reflejan estos valores; si se
añade uno aquí, hay que añadirlo allí (los `Record` de etiquetas romperán la
compilación hasta hacerlo).
