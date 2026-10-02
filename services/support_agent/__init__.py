"""Agente de primera línea de CX de TrackFlow: grafo de LangGraph con RAG, tool de incidencias y guardrails.

- `state.py`: estado mínimo que viaja entre nodos.
- `routing.py`: decide si la pregunta necesita la tool de tickets, el RAG o ambos.
- `tools/`: una tool de solo lectura por servicio (`incidents.py`: `GET /api/incidents/{id}`).
- `prompt.py`: system prompt del agente de CX y mensajes al modelo (instrucciones separadas del input).
- `guardrails/`: harness de protección (guard de entrada, aislamiento del contenido externo, guard de salida y
  registro de activaciones). `small_talk.py`: respuesta breve a small talk, siempre reconducida.
- `nodes.py`: un nodo por responsabilidad y las condiciones de salida de cada uno.
- `graph.py`: construcción, validación estructural y compilación del grafo (con checkpointer).
- `tracing.py` + `runner.py`: cada corrida deja un trace JSON consultable con los nodos, su salida y los checkpoints.
- `router.py`: `POST /agent/query`, que solo invoca el grafo, y `GET /agent/guardrails/summary`.
"""
