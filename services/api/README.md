# TrackFlow Incidents API

API de análisis agregado para incidencias. El procesamiento usa el mismo módulo
`incidents_analyzer.py` que el CLI de `scripts/incidents-analyzer/`; procesa las
filas en streaming y no guarda ni devuelve datos de clientes.

## Ejecutar

```bash
python -m pip install -r services/api/requirements.txt
uvicorn services.api.main:app --reload --port 8000
```

El backoffice se sirve en `http://localhost:3002` y reenvía `/api/incidents/*`
al servicio desde Next, en el mismo origen que la página. En Codespaces, no hace
falta exponer el puerto 8000 al navegador. Si la API se ejecuta en otro host,
configura `INCIDENTS_API_INTERNAL_URL` en el proceso del backoffice.
`BACKOFFICE_ORIGIN` permite autorizar otro origen si se consume la API
directamente.

## Endpoints

- `POST /api/incidents/analyze`: recibe el campo multipart `file` y devuelve el
  resumen JSON. CSV vacío, cabecera incompatible o contenido inválido responde
  `400` con un mensaje que no incluye valores del fichero.
- `GET /api/incidents/results/export`: descarga las métricas agregadas del
  último análisis correcto como CSV. Antes de un análisis responde `404`.
- `GET /`: informa que el servicio está activo.

El resumen más reciente vive en memoria del proceso y se reemplaza tras cada
carga correcta; no se persiste el fichero ni sus registros.