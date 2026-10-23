"""Respuesta breve a small talk o trivia: una o dos frases del modelo, sin RAG ni tools.

La reconducción hacia TrackFlow no depende del modelo: la añade el guard de salida (`check_output(mode="small_talk")`).
"""

from __future__ import annotations

import logging

import openai

from data.pipelines import rag
from data.process.rag import RagServiceError, get_llm_client, load_settings
from services.support_agent.prompt import build_small_talk_messages


logger = logging.getLogger("trackflow.agent")


def brief_reply(question: str) -> str:
    model = load_settings().generation_model
    try:
        completion = get_llm_client().chat.completions.create(
            model=model,
            messages=build_small_talk_messages(question),
            temperature=rag.GENERATION_TEMPERATURE,
        )
    except openai.OpenAIError as error:
        logger.error("brief_reply fallo del modelo %s: %s", model, type(error).__name__)
        raise RagServiceError("El modelo de generación no respondió.") from error
    answer = (completion.choices[0].message.content or "").strip() if completion.choices else ""
    if not answer:
        raise RagServiceError("El modelo de generación devolvió una respuesta vacía.")
    return answer
