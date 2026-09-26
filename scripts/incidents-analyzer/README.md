# Analizador de incidencias

Ejecuta el CLI desde la raíz del monorepo:

```bash
python scripts/incidents-analyzer/analyze.py scripts/incidents-trackflow.csv
```

Desde esta carpeta, el CSV de prueba está en el directorio padre:

```bash
python3 analyze.py ../incidents-trackflow.csv
```

También acepta cualquier ruta CSV compatible como primer argumento. Valida las
reglas definidas en `Context-incidents.md`, calcula métricas solo con filas
válidas y pregunta si debe crear `results.csv` en el directorio de ejecución.
El resumen y el CSV exportado contienen únicamente métricas agregadas; no
incluyen correos ni valores de registros individuales.