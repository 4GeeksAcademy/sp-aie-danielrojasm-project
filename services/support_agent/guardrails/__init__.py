"""Harness de protección del agente de CX: una capa por tipo de fallo, todas deterministas y sin llamar al modelo.

- `text.py`: normalización compartida (minúsculas, sin acentos ni caracteres invisibles) y troceo en frases.
- `input_guard.py`: decide antes del grafo si el mensaje se responde, se reconduce o se rechaza: cambio de
  instrucciones (seguridad), uso como chatbot personal, pedido ajeno a la sesión y small talk (contenido), y mezcla
  de políticas entre países.
- `isolation.py`: aísla el texto de la base de conocimiento, del gestor de incidencias y de la memoria; retira
  las órdenes incrustadas y las etiquetas que delimitan el prompt.
- `output_guard.py`: valida la respuesta antes de devolverla (formato, fuga de instrucciones internas, datos
  sensibles del CONTEXT).
- `events.py`: registro de cada activación (log `trackflow.guardrails` con el tipo de fallo) y su resumen.

El system prompt que estas capas protegen está en `services/support_agent/prompt.py`.
"""
