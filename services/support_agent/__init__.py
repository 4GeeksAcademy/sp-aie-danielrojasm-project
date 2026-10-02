"""Agente de soporte comercial de TrackFlow: grafo de LangGraph con el RAG y la tool del gestor de incidencias.

- `state.py`: estado mínimo que viaja entre nodos.
- `routing.py`: decide si la pregunta necesita la tool de tickets, el RAG o ambos.
- `tools/`: una tool de solo lectura por servicio (`incidents.py`: `GET /api/incidents/{id}`).
- `nodes.py`: un nodo por responsabilidad y las condiciones de salida de cada uno.
- `graph.py`: construcción, validación estructural y compilación del grafo (con checkpointer).
- `tracing.py` + `runner.py`: cada corrida deja un trace JSON consultable con los nodos, su salida y los checkpoints.
- `router.py`: `POST /agent/query`, que solo invoca el grafo.
"""
