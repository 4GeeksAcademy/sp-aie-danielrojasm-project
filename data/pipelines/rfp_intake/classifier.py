"""Agente clasificador: ¿es el documento una RFP de un cliente para TrackFlow?

Criterio (BRIEFING §1, §2.2 y §4): una RFP es una petición de propuesta de una marca (normalmente e-commerce) que
quiere tercerizar con TrackFlow almacenamiento, última milla, devoluciones o una combinación, en EE. UU. o España.
Puede ser formal (documento con referencia, plazos y criterios) o informal (un correo). No lo es lo que ofrece algo
a TrackFlow (el pitch de tarifas de un transportista), ni facturas, CVs, newsletters o documentos internos.

Falsos negativos: descartar una RFP real hace perder una venta y nadie la vuelve a mirar; aceptar un documento que
no lo es solo cuesta un análisis que Ventas ve enseguida. Por eso el código solo descarta cuando el modelo dice que
no es una RFP con confianza suficiente (`DISCARD_MIN_CONFIDENCE`); con dudas, el documento sigue y la confianza queda
guardada en el ticket.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from data.pipelines.rfp_intake import llm


logger = logging.getLogger("trackflow.rfp_intake")

AGENT = "classifier"
DISCARD_MIN_CONFIDENCE = 0.6
# El tipo de documento se decide con el principio: no hace falta pagar tokens por un anexo de 40 páginas.
MAX_CLASSIFIER_CHARS = 12_000

SYSTEM_PROMPT = """Eres el agente clasificador de RFPs de TrackFlow, operador logístico (3PL) con almacenes en
Los Angeles (EE. UU.) y Zaragoza (España). TrackFlow ofrece almacenamiento (warehousing), última milla y gestión de
transportistas (last mile) y logística inversa o devoluciones (reverse logistics) a marcas de e-commerce.

Decide si el documento es una RFP para TrackFlow: un cliente o prospecto que pide a TrackFlow una propuesta o
cotización para alguno de esos servicios. Puede ser formal (documento con referencia, fechas y criterios) o
informal (un correo que pide "una propuesta").

NO es una RFP para TrackFlow:
- un proveedor o transportista que ofrece sus servicios o tarifas a TrackFlow (pitch comercial entrante);
- facturas, CVs, newsletters, documentos internos o cualquier petición que no sea de servicios logísticos.

Responde solo con JSON:
{"is_rfp": true|false,
 "document_type": "rfp_formal" | "rfp_informal" | "vendor_pitch" | "other",
 "confidence": número entre 0 y 1,
 "reason": "una frase en español que explique la decisión citando lo que pide el documento"}"""


class ClassifierOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    is_rfp: bool
    document_type: Literal["rfp_formal", "rfp_informal", "vendor_pitch", "other"]
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=600)


@dataclass(frozen=True)
class Classification:
    is_rfp: bool
    document_type: str
    confidence: float
    reason: str


def classify(markdown: str) -> Classification:
    output = llm.ask_json(AGENT, SYSTEM_PROMPT, llm.as_document(markdown[:MAX_CLASSIFIER_CHARS]), ClassifierOutput)
    return decide(output)


def decide(output: ClassifierOutput) -> Classification:
    reason = output.reason.strip()
    if not output.is_rfp and output.confidence < DISCARD_MIN_CONFIDENCE:
        logger.warning(
            "classifier no-RFP con confianza %.2f < %.2f: se procesa igual para no perder una RFP real.",
            output.confidence,
            DISCARD_MIN_CONFIDENCE,
        )
        return Classification(
            True,
            output.document_type,
            output.confidence,
            f"Aceptado con dudas (confianza {output.confidence:.2f}): {reason}",
        )
    return Classification(output.is_rfp, output.document_type, output.confidence, reason)
