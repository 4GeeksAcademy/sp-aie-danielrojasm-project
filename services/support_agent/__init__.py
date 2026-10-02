"""Agente de soporte comercial de TrackFlow: el RAG de `data/pipelines/rag.py` como grafo de LangGraph.

- `state.py`: estado mínimo que viaja entre nodos.
- `nodes.py`: un nodo por responsabilidad y las condiciones de salida de cada uno.
- `graph.py`: construcción, validación estructural y compilación del grafo (con checkpointer).
- `tracing.py` + `runner.py`: cada corrida deja un trace JSON consultable con los nodos, su salida y los checkpoints.
- `router.py`: `POST /agent/query`, que solo invoca el grafo.
"""
