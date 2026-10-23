"""Documento final de la propuesta económica (BRIEFING §2.3, `FinalDocument`): el "ultimate document synthesizer".

Se genera solo cuando todas las secciones activas están aprobadas. Consolida el texto **aprobado** de cada sección
sin reescribirlo (lo que firmó cada responsable es lo que recibe el cliente) y añade en código la cabecera con los
datos de la RFP y la tabla de aprobaciones. No interviene ningún modelo.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from data.pipelines.rfp_intake.departments import DEPARTMENTS


COUNTRY_LABELS = {"US": "Estados Unidos", "ES": "España"}
SERVICE_LABELS = {"warehousing": "Almacenamiento", "last_mile": "Última milla", "reverse_logistics": "Devoluciones"}


def build(
    ticket_id: str,
    rfp_id: str | None,
    shared: dict[str, Any],
    sections: list[dict[str, Any]],
    generated_at: datetime,
) -> dict[str, Any]:
    """`FinalDocument` como dict: `ticket_id`, `rfp_id`, `currency`, `sections`, `content` y `generated_at`."""
    order = list(DEPARTMENTS)
    approved = sorted(sections, key=lambda section: order.index(section["department_id"]))
    if not approved or any(section["approval_status"] != "aprobada" for section in approved):
        raise ValueError("El documento final solo se genera con todas las secciones activas aprobadas.")
    currency = shared["currency"]
    document_sections = [
        {
            "department_id": section["department_id"],
            "department_name": DEPARTMENTS[section["department_id"]].name,
            "approver": section["approver"],
            "approved_at": section["approved_at"],
            "review_round": section["review_round"],
            "content": section["draft_content"].strip(),
        }
        for section in approved
    ]
    return {
        "ticket_id": ticket_id,
        "rfp_id": rfp_id,
        "currency": currency,
        "sections": document_sections,
        "content": render(ticket_id, shared, document_sections, generated_at),
        "generated_at": generated_at.isoformat(),
    }


def render(ticket_id: str, shared: dict[str, Any], sections: list[dict[str, Any]], generated_at: datetime) -> str:
    client = shared.get("client_name") or "el cliente"
    volume = shared.get("monthly_volume")
    rows = [
        ("Cliente", shared.get("client_name") or "No indicado"),
        ("País de operación", COUNTRY_LABELS.get(shared.get("client_country") or "", "No indicado")),
        ("Moneda", shared["currency"]),
        (
            "Servicios",
            ", ".join(SERVICE_LABELS.get(service, service) for service in shared.get("services_requested", []))
            or "No indicados",
        ),
        ("Volumen mensual de referencia", f"{_thousands(volume)} pedidos/mes" if volume else "A confirmar"),
        ("Fecha límite de la RFP", _long_date(shared.get("deadline")) or "No indicada"),
    ]
    lines = [
        f"# Propuesta económica de TrackFlow para {client}",
        "",
        "| Dato | Valor |",
        "| --- | --- |",
        *(f"| {label} | {value} |" for label, value in rows),
        "",
        "## Aprobaciones",
        "",
        "| Sección | Responsable | Aprobada el | Revisión |",
        "| --- | --- | --- | --- |",
        *(
            f"| {s['department_name']} | {s['approver']} | {_long_date(s['approved_at'])} | {s['review_round']} |"
            for s in sections
        ),
    ]
    for section in sections:
        lines += ["", section["content"]]
    lines += [
        "",
        "---",
        "",
        f"Documento generado automáticamente el {_long_date(generated_at.isoformat())} con las secciones aprobadas "
        f"por cada responsable (ticket {ticket_id}). Todos los importes están en {shared['currency']}.",
    ]
    return "\n".join(lines) + "\n"


MONTHS = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)


def _long_date(value: str | None) -> str | None:
    if not value:
        return None
    day = date.fromisoformat(value[:10])
    return f"{day.day} de {MONTHS[day.month - 1]} de {day.year}"


def _thousands(value: int) -> str:
    return f"{value:,}".replace(",", ".")
