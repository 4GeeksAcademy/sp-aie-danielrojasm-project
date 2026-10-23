"""Triggers de conflicto entre departamentos y árbitro fijo de la Parte 3 (BRIEFING §7).

El arbitraje no es una negociación entre agentes: el nodo `arbitrate` del grafo de aprobación aplica estas reglas a
hechos estructurados que el código extrae de cada sección (`SectionFacts`), nunca a la opinión de un modelo.

| `trigger_id` | Cuándo dispara | Árbitro | Resolución |
| --- | --- | --- | --- |
| `volume-vs-capacity` | La capacidad comprometida de `warehouse` < volumen mensual asumido por `lastmile` | Miguel Torres | `lastmile` revisa volumen y costo a la baja, limitado a la capacidad |
| `returns-sla-breach` | Una sección promete devoluciones en menos de 48 h (§5) | Sofía Ramos en `reverse`; Miguel Torres en otra sección | `request_changes` en cada sección que lo diga |
| `currency-mismatch` | Dos secciones cotizan monedas distintas o una moneda ≠ la del país del cliente | Miguel Torres | Reescribir las secciones ofensoras a la moneda del país |

Hechos estructurados por sección:

- `currencies`: la moneda de la cabecera `**Moneda:**` y las de los importes cotizados (`compliance.MONEY` +
  `CURRENCY_PATTERNS`), no las de cualquier mención.
- `returns_promises`: frases con un plazo de devoluciones < 48 h (misma regla que `returns-min-48h` del §5).
- `monthly_capacity` (`warehouse`): la línea `**Capacidad comprometida:** N pedidos/mes` del borrador o, si lo
  indica, la capacidad que registra Ana Whitfield al aprobar (manda la del responsable).
- `assumed_monthly_volume` (`lastmile`): la línea `**Volumen asumido:** N pedidos/mes` del borrador.

Dentro del límite de rondas, el árbitro fuerza `request_changes` con una instrucción concreta; al agotarlo, la
sección ofensora queda `rechazada` y no se genera documento final (BRIEFING §7: "rechazar si no se resuelve tras el
límite de iteraciones", "sin documento final hasta cumplir").
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from data.pipelines.rfp_intake import compliance
from data.pipelines.rfp_intake.departments import DEPARTMENTS


VOLUME_VS_CAPACITY = "volume-vs-capacity"
RETURNS_SLA_BREACH = "returns-sla-breach"
CURRENCY_MISMATCH = "currency-mismatch"

COMMERCIAL_DIRECTOR = "Miguel Torres"
RETURNS_OWNER = DEPARTMENTS["reverse"].responsible

TRIGGER_RULES: dict[str, str] = {
    VOLUME_VS_CAPACITY: (
        "Limitar el volumen de la propuesta a la capacidad de warehouse; lastmile revisa volumen y costo a la baja."
    ),
    RETURNS_SLA_BREACH: (
        "Forzar request_changes en toda sección que prometa devoluciones en menos de 48 h; sin documento final hasta "
        "cumplir."
    ),
    CURRENCY_MISMATCH: (
        "Reescribir las secciones ofensoras a la moneda del país del cliente; rechazar si no se resuelve tras el "
        "límite de iteraciones."
    ),
}

_NUMBER = r"(?P<value>\d{1,3}(?:[.,\s]\d{3})+|\d+)"
CAPACITY_LINE = re.compile(rf"capacidad comprometida\W*{_NUMBER}\s*(?:pedidos|[oó]rdenes|env[ií]os)", re.IGNORECASE)
VOLUME_LINE = re.compile(rf"volumen asumido\W*{_NUMBER}\s*(?:pedidos|[oó]rdenes|env[ií]os)", re.IGNORECASE)
CAPACITY_HEADER = re.compile(r"^\s*\*\*Capacidad comprometida:\*\*", re.IGNORECASE)
DECLARED_CURRENCY = re.compile(r"\*\*Moneda:\*\*\s*(?P<currency>USD|EUR)\b", re.IGNORECASE)


@dataclass(frozen=True)
class SectionFacts:
    department_id: str
    currencies: list[str] = field(default_factory=list)
    returns_promises: list[str] = field(default_factory=list)
    monthly_capacity: int | None = None
    assumed_monthly_volume: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Conflict:
    trigger_id: str
    arbiter: str
    # Secciones que tienen que cambiar (las ofensoras) y la instrucción concreta para cada una.
    instructions: dict[str, str]
    evidence: str

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "rule": TRIGGER_RULES[self.trigger_id]}


def extract_facts(department_id: str, draft: str, committed_capacity: int | None = None) -> SectionFacts:
    capacity = committed_capacity
    if capacity is None and department_id == "warehouse":
        capacity = _number(CAPACITY_LINE.search(draft))
    volume = _number(VOLUME_LINE.search(draft)) if department_id == "lastmile" else None
    return SectionFacts(
        department_id=department_id,
        currencies=quoted_currencies(draft),
        returns_promises=[violation.evidence for violation in compliance.check_returns_turnaround(draft)],
        monthly_capacity=capacity,
        assumed_monthly_volume=volume,
    )


def with_committed_capacity(draft: str, capacity: int) -> str:
    """Escribe en la sección de Warehouse la capacidad que compromete Ana Whitfield al aprobarla.

    Sustituye la línea `**Capacidad comprometida:**` (o la añade bajo la cabecera) para que el texto aprobado diga lo
    mismo que el dato estructurado con el que se arbitra.
    """
    line = f"**Capacidad comprometida:** {capacity:,} pedidos/mes".replace(",", ".")
    lines = draft.splitlines()
    for index, current in enumerate(lines):
        if CAPACITY_HEADER.match(current):
            lines[index] = line
            return "\n".join(lines)
    insert_at = next((i + 1 for i, current in enumerate(lines) if current.startswith("**Responsable:**")), 1)
    return "\n".join([*lines[:insert_at], line, *lines[insert_at:]])


def quoted_currencies(draft: str) -> list[str]:
    """Moneda declarada en la cabecera (`**Moneda:** EUR`) y monedas de los importes (`120 USD`, `€ 3,50`…).

    No cuenta una mención suelta de la palabra: lo que importa es en qué moneda cotiza la sección.
    """
    found = {match.group("currency").upper() for match in DECLARED_CURRENCY.finditer(draft)}
    found |= {
        currency
        for amount in compliance.MONEY.finditer(draft)
        for currency, pattern in compliance.CURRENCY_PATTERNS.items()
        if pattern.search(amount.group())
    }
    return sorted(found)


def detect(facts: dict[str, SectionFacts], expected_currency: str | None) -> list[Conflict]:
    """Conflictos entre las secciones activas, en el orden de la tabla del BRIEFING §7."""
    return [
        *_volume_vs_capacity(facts),
        *_returns_sla_breach(facts),
        *_currency_mismatch(facts, expected_currency),
    ]


def _volume_vs_capacity(facts: dict[str, SectionFacts]) -> list[Conflict]:
    warehouse, lastmile = facts.get("warehouse"), facts.get("lastmile")
    if not warehouse or not lastmile or warehouse.monthly_capacity is None or lastmile.assumed_monthly_volume is None:
        return []
    capacity, volume = warehouse.monthly_capacity, lastmile.assumed_monthly_volume
    if capacity >= volume:
        return []
    return [
        Conflict(
            VOLUME_VS_CAPACITY,
            COMMERCIAL_DIRECTOR,
            {
                "lastmile": (
                    f"Arbitraje {VOLUME_VS_CAPACITY} ({COMMERCIAL_DIRECTOR}): Warehouse solo compromete {capacity} "
                    f"pedidos/mes. Cambia el volumen asumido a {capacity} pedidos/mes en la línea "
                    f"'**Volumen asumido:**', explica en el Alcance que la RFP indica {volume} pedidos/mes y que "
                    f"esta propuesta se limita a {capacity} por la capacidad comprometida por Warehouse, y revisa a "
                    f"la baja el costo por envío y los tramos de descuento."
                )
            },
            f"Capacidad de warehouse {capacity} pedidos/mes < volumen asumido por lastmile {volume} pedidos/mes.",
        )
    ]


def _returns_sla_breach(facts: dict[str, SectionFacts]) -> list[Conflict]:
    conflicts = []
    for department_id, section in facts.items():
        if not section.returns_promises:
            continue
        arbiter = RETURNS_OWNER if department_id == "reverse" else COMMERCIAL_DIRECTOR
        conflicts.append(
            Conflict(
                RETURNS_SLA_BREACH,
                arbiter,
                {
                    department_id: (
                        f"Arbitraje {RETURNS_SLA_BREACH} ({arbiter}): "
                        f"{compliance.RULES[compliance.RETURNS_RULE].fix} Texto: \"{section.returns_promises[0]}\"."
                    )
                },
                section.returns_promises[0],
            )
        )
    return conflicts


def _currency_mismatch(facts: dict[str, SectionFacts], expected: str | None) -> list[Conflict]:
    quoted = {department_id: section.currencies for department_id, section in facts.items() if section.currencies}
    if expected:
        offending = {d: c for d, c in quoted.items() if any(currency != expected for currency in c)}
    elif len({currency for currencies in quoted.values() for currency in currencies}) > 1:
        # Sin país no hay moneda de referencia: si las secciones no coinciden, todas tienen que confirmarla.
        offending = quoted
    else:
        offending = {}
    if not offending:
        return []
    target = expected or "la moneda del país del cliente (Ventas tiene que confirmar el país)"
    evidence = "; ".join(f"{d}: {', '.join(c)}" for d, c in offending.items())
    return [
        Conflict(
            CURRENCY_MISMATCH,
            COMMERCIAL_DIRECTOR,
            {
                department_id: (
                    f"Arbitraje {CURRENCY_MISMATCH} ({COMMERCIAL_DIRECTOR}): cotiza todos los importes en {target} y "
                    f"elimina los importes en {', '.join(c for c in currencies if c != expected)}; no conviertas: si "
                    f"un precio no existe en {target}, déjalo como 'a confirmar'."
                )
                for department_id, currencies in offending.items()
            },
            f"Moneda esperada {expected or 'sin definir'}; secciones con otra moneda: {evidence}.",
        )
    ]


def _number(match: re.Match[str] | None) -> int | None:
    if match is None:
        return None
    return int(re.sub(r"[.,\s]", "", match.group("value")))
