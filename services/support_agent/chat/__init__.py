"""Chat por WebSocket con el agente: tokens en tiempo real, interrupción a mitad de respuesta y rehidratación.

- `models.py`: `ChatSession`, `ChatMessage` y el contrato de eventos (BRIEFING de la Parte 2).
- `store.py`: historial en Redis. `broker.py`: pub/sub en memoria, un canal por sesión.
- `hub.py`: productor; una sola generación por sesión, compartida por todas sus conexiones.
- `router.py`: `POST`/`GET /agent/chat/sessions` y el WebSocket `/agent/chat/sessions/{session_id}/ws`.
"""
