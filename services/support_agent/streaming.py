"""Streaming de tokens del modelo hacia fuera del grafo y abort cooperativo de la generación en curso.

Solo se activa cuando la corrida lo pide (`runner.run_agent(on_token=…)`, el chat por WebSocket): la corrida pone un
`TokenStream` en `configurable[TOKEN_STREAM_KEY]`. Sin él, `complete()` hace la misma llamada sin streaming de
siempre (`POST /agent/query`, scripts, evals).

Con él, en los nodos de `TokenStream.nodes` la llamada al modelo usa `stream=True` y cada trozo de texto visible se
emite con el writer del modo `custom` de LangGraph (`{"token": "…"}`). Si el modelo responde en JSON, solo se emite
el valor de `visible_field` (`JsonFieldStreamer`), nunca el JSON crudo. Antes de cada trozo se mira `abort`: si está
puesto se cierra la respuesta HTTP del modelo (deja de generar) y se lanza `GenerationAborted`, que corta el grafo.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from langgraph.config import get_config, get_stream_writer


logger = logging.getLogger("trackflow.agent")

TOKEN_STREAM_KEY = "token_stream"


class GenerationAborted(RuntimeError):
    """El cliente interrumpió la generación: no se emiten más tokens y la corrida termina sin respuesta."""


@dataclass(frozen=True)
class TokenStream:
    abort: threading.Event = field(default_factory=threading.Event)
    # Nodos cuyo texto llega al usuario tal cual (en `no_information` el modelo responde, pero su texto no se usa).
    nodes: frozenset[str] = frozenset()


def current_stream() -> TokenStream | None:
    """El `TokenStream` de la corrida en curso, o `None` fuera de un grafo o si la corrida no pidió streaming."""
    try:
        config = get_config()
    except RuntimeError:
        return None
    stream = config.get("configurable", {}).get(TOKEN_STREAM_KEY)
    return stream if isinstance(stream, TokenStream) else None


def check_aborted() -> None:
    stream = current_stream()
    if stream is not None and stream.abort.is_set():
        raise GenerationAborted("La generación se interrumpió a petición del cliente.")


def complete(client: Any, *, visible_field: str | None = None, **request: Any) -> str:
    """Contenido de `client.chat.completions.create(**request)`; con streaming en este nodo, emite su texto visible.

    `visible_field` es la clave del JSON cuyo valor ve el usuario (`response_format` en modo JSON). Los errores del
    cliente (`openai.OpenAIError`) suben igual que sin streaming; cada nodo los traduce como siempre.
    """
    check_aborted()
    stream = current_stream()
    node = get_config().get("metadata", {}).get("langgraph_node") if stream is not None else None
    if stream is None or node not in stream.nodes:
        completion = client.chat.completions.create(**request)
        return (completion.choices[0].message.content or "") if completion.choices else ""

    write = get_stream_writer()
    visible = JsonFieldStreamer(visible_field) if visible_field else None
    parts: list[str] = []
    response = client.chat.completions.create(**request, stream=True)
    try:
        for delta in _deltas(response):
            if stream.abort.is_set():
                logger.info("stream_aborted node=%s chars=%d", node, sum(len(part) for part in parts))
                raise GenerationAborted("La generación se interrumpió a petición del cliente.")
            parts.append(delta)
            text = visible.feed(delta) if visible else delta
            if text:
                write({"token": text})
    finally:
        # Cerrar la respuesta corta la conexión con el gateway: el modelo deja de generar, no solo se ignora.
        response.close()
    return "".join(parts)


def _deltas(response: Iterable[Any]) -> Iterable[str]:
    for chunk in response:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


ESCAPES = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}


class JsonFieldStreamer:
    """Extrae, conforme llega, el valor de texto de una clave de primer nivel de un objeto JSON.

    `feed()` recibe trozos arbitrarios del JSON y devuelve el texto nuevo del valor ya decodificado (escapes y
    `\\uXXXX` incluidos). Antes de la clave y después de la comilla de cierre devuelve "".
    """

    def __init__(self, key: str):
        self.marker = f'"{key}"'
        self.state = "seek"
        self.pending = ""

    def feed(self, chunk: str) -> str:
        self.pending += chunk
        if self.state == "seek":
            self._seek()
        return self._value() if self.state == "value" else ""

    def _seek(self) -> None:
        start = self.pending.find(self.marker)
        if start < 0:
            # Conserva el final por si la clave llega partida entre dos trozos.
            self.pending = self.pending[-len(self.marker) :]
            return
        self.pending = self.pending[start:]
        rest = self.pending[len(self.marker) :].lstrip()
        if not rest:
            return
        if rest[0] != ":":
            # Era el mismo texto dentro de otro valor, no la clave: se sigue buscando después.
            self.pending = self.pending[len(self.marker) :]
            self._seek()
            return
        rest = rest[1:].lstrip()
        if not rest:
            return
        if rest[0] != '"':
            # El valor no es un texto: no hay nada que mostrar.
            self.state = "done"
            return
        self.state = "value"
        self.pending = rest[1:]

    def _value(self) -> str:
        out: list[str] = []
        text = self.pending
        index = 0
        while index < len(text):
            char = text[index]
            if char == '"':
                self.state = "done"
                index = len(text)
                break
            if char != "\\":
                out.append(char)
                index += 1
                continue
            if index + 1 >= len(text):
                break
            code = text[index + 1]
            if code == "u":
                if index + 6 > len(text):
                    break
                point = int(text[index + 2 : index + 6], 16)
                if 0xD800 <= point < 0xDC00:
                    # Par sustituto (emoji y similares): hacen falta los dos `\uXXXX`.
                    if index + 12 > len(text):
                        break
                    low = int(text[index + 8 : index + 12], 16)
                    point = 0x10000 + ((point - 0xD800) << 10) + (low - 0xDC00)
                    index += 6
                out.append(chr(point))
                index += 6
            else:
                out.append(ESCAPES.get(code, code))
                index += 2
        self.pending = text[index:] if self.state == "value" else ""
        return "".join(out)
