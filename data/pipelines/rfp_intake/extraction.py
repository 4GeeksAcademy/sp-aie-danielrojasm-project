"""Extracción de metadatos de una RFP válida (BRIEFING §2.2 y §2.3).

El modelo solo extrae lo que el documento dice. El código añade lo que no debe decidir un modelo:
- la moneda, a partir de `client_country` (US → USD, ES → EUR);
- la regla "nunca inventes": un volumen mensual que no aparece como cifra en el documento se descarta.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from data.pipelines.rfp_intake import llm
from data.pipelines.rfp_intake.departments import ClientCountry, Service, currency_for
from data.pipelines.rfp_intake.document import normalize_number, numbers_in


logger = logging.getLogger("trackflow.rfp_intake")

AGENT = "metadata_extractor"
MAX_EXTRACTION_CHARS = 40_000

SYSTEM_PROMPT = """Eres el agente de extracción de metadatos de RFPs de TrackFlow (3PL en EE. UU. y España).
Extrae del documento SOLO lo que dice de forma explícita. Si un dato no aparece, usa null (o [] en listas).
Nunca estimes ni completes cifras.

Campos:
- client_name: nombre de la empresa cliente que pide la propuesta.
- client_country: "US" si la operación o el cliente están en Estados Unidos, "ES" si están en España; null si no
  se sabe.
- client_reference: referencia de la RFP si el documento la da (p. ej. "RFP Reference No."); si no, null.
- services_requested: servicios que el cliente PIDE a TrackFlow, de entre "warehousing" (almacenamiento),
  "last_mile" (reparto de última milla, envíos o selección de transportistas) y "reverse_logistics"
  (devoluciones). No incluyas un servicio que el cliente dice expresamente que no necesita.
- monthly_volume: pedidos o envíos al mes como número entero, solo si el documento da esa cifra; si no, null.
  Un número de SKUs o de pallets NO es un volumen mensual de pedidos.
- deadline: fecha límite de la propuesta o, si no la hay, la fecha en la que el cliente pide empezar, en formato
  YYYY-MM-DD. Solo si el documento da día, mes y año (el año puede salir de otra fecha del mismo documento);
  si no, null.
- budget_range: presupuesto de referencia tal como lo escribe el documento; si no lo hay, null.

Responde solo con JSON con exactamente esas claves."""


class ExtractionOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    client_name: str | None = Field(default=None, max_length=200)
    client_country: ClientCountry | None = None
    client_reference: str | None = Field(default=None, max_length=120)
    services_requested: list[Service] = Field(default_factory=list)
    monthly_volume: int | None = Field(default=None, gt=0)
    deadline: date | None = None
    budget_range: str | None = Field(default=None, max_length=200)

    @field_validator("client_name", "client_reference", "budget_range", mode="before")
    @classmethod
    def _blank_is_none(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value.strip() if isinstance(value, str) else value

    @field_validator("client_country", mode="before")
    @classmethod
    def _country_code(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = COUNTRY_ALIASES.get(value.strip().lower(), value.strip().upper())
            return value if value in {country.value for country in ClientCountry} else None
        return value

    @field_validator("services_requested", mode="before")
    @classmethod
    def _known_services(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return value
        known = {service.value for service in Service}
        unknown = [item for item in value if item not in known]
        if unknown:
            logger.warning("metadata_extractor servicios fuera del catálogo descartados: %s", unknown)
        return [item for item in value if item in known]


COUNTRY_ALIASES = {
    "us": "US", "usa": "US", "united states": "US", "estados unidos": "US", "ee. uu.": "US", "eeuu": "US",
    "es": "ES", "spain": "ES", "españa": "ES", "espana": "ES",
}


def extract_metadata(markdown: str) -> dict[str, Any]:
    output = llm.ask_json(
        AGENT, SYSTEM_PROMPT, llm.as_document(markdown[:MAX_EXTRACTION_CHARS]), ExtractionOutput
    )
    return finalize(output, markdown)


def finalize(output: ExtractionOutput, markdown: str) -> dict[str, Any]:
    volume = output.monthly_volume
    if volume is not None and normalize_number(str(volume)) not in numbers_in(markdown):
        logger.warning("metadata_extractor volumen %s no aparece en el documento: se descarta.", volume)
        volume = None
    country = output.client_country.value if output.client_country else None
    return {
        "client_name": output.client_name,
        "client_country": country,
        "currency": currency_for(country),
        "client_reference": output.client_reference,
        "services_requested": list(dict.fromkeys(service.value for service in output.services_requested)),
        "monthly_volume": volume,
        "deadline": output.deadline.isoformat() if output.deadline else None,
        "budget_range": output.budget_range,
    }
