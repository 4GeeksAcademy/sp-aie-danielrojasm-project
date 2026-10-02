"""Memoria del agente de soporte: propuesta → decisión explícita del usuario → consolidación, con registro auditable.

- `models.py`: propuesta del modelo (`propuesta_memoria`), propuesta pendiente, entradas consolidadas y decisión.
- `policy.py`: qué se puede recordar y qué nunca (CONTEXT de TrackFlow), claves de consolidación, caducidades y
  límites. Toda escritura pasa por aquí, también la de un hecho editado por el usuario.
- `store.py`: interfaz explícita de lectura/escritura sobre Redis (`trackflow:agent_memory:*`), separada de la base
  de conocimiento (`trackflow_knowledge` en Qdrant, de solo lectura para el agente).
- `self_evaluation.py`: la única llamada de generación devuelve la respuesta y `propuesta_memoria`.
- `decision.py`: clasifica la respuesta del usuario frente a la propuesta pendiente (aprobar, rechazar, editar o
  no relacionada); ante la duda, se descarta.

Diseño y evidencias en `docs/agent-memory/memory-design.md`.
"""
