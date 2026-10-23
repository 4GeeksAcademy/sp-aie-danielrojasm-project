"""Departamentos que participan en una propuesta de TrackFlow y vocabulario del dominio de RFPs.

Fuente: el BRIEFING del Hito 9 (§2.1 y §2.2). Los identificadores son exactamente los del BRIEFING; cualquier otro
departamento que proponga un agente se descarta en código (ver `orchestrator.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TicketStatus(str, Enum):
    """Estados del ticket que usa la Parte 1. Las Partes 2 y 3 continúan el mismo ticket."""

    ANALIZANDO = "analizando"
    DESCARTADO = "descartado"
    ANALISIS_COMPLETO = "analisis_completo"


class ClientCountry(str, Enum):
    US = "US"
    ES = "ES"


class Currency(str, Enum):
    USD = "USD"
    EUR = "EUR"


class Service(str, Enum):
    WAREHOUSING = "warehousing"
    LAST_MILE = "last_mile"
    REVERSE_LOGISTICS = "reverse_logistics"


@dataclass(frozen=True)
class Department:
    department_id: str
    name: str
    responsible: str
    contribution: str
    service: Service


DEPARTMENTS: dict[str, Department] = {
    department.department_id: department
    for department in (
        Department(
            "warehouse",
            "Warehouse Operations",
            "Ana Whitfield",
            "Capacidad de almacenamiento, costo por pallet/SKU y tiempo de onboarding.",
            Service.WAREHOUSING,
        ),
        Department(
            "lastmile",
            "Last Mile and Carrier Management",
            "Carlos Vega",
            "Costo por envío, transportistas disponibles según destino y SLA de entrega.",
            Service.LAST_MILE,
        ),
        Department(
            "reverse",
            "Reverse Logistics",
            "Sofía Ramos",
            "Costo y tiempo de procesamiento de devoluciones (si el cliente lo solicita).",
            Service.REVERSE_LOGISTICS,
        ),
    )
}

# El volumen mensual condiciona la capacidad de almacén y el costo de envío; sin él, el worker abre una pregunta.
VOLUME_DEPENDENT_DEPARTMENTS = frozenset({"warehouse", "lastmile"})

# La moneda de la propuesta sale del país del cliente (BRIEFING §5), nunca del modelo.
CURRENCY_BY_COUNTRY: dict[ClientCountry, Currency] = {
    ClientCountry.US: Currency.USD,
    ClientCountry.ES: Currency.EUR,
}


def currency_for(country: str | None) -> str | None:
    if country is None:
        return None
    return CURRENCY_BY_COUNTRY[ClientCountry(country)].value


def department_catalog() -> str:
    """Catálogo para los prompts: una línea por departamento."""
    return "\n".join(
        f"- {d.department_id}: {d.name} (responsable {d.responsible}). Servicio: {d.service.value}. "
        f"Aporta: {d.contribution}"
        for d in DEPARTMENTS.values()
    )
