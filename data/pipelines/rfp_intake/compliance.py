"""Lineamientos de empresa para el evaluador de cumplimiento (BRIEFING §5), como reglas con id.

El evaluador no da una opinión de estilo: cada violación cita una de estas reglas. Las comprobaciones de este módulo
son deterministas y miran el texto del borrador; el revisor con modelo de `evaluators.py` solo puede añadir
violaciones de las reglas que necesitan leer la intención (`LLM_REVIEWED_RULES`) y citando el texto literal.

| `rule_id` | Lineamiento (BRIEFING §5) |
| --- | --- |
| `currency-by-country` | USD para operación en EE. UU. y EUR para España, según `client_country`. |
| `on-time-sla` | La propuesta indica el SLA de entrega a tiempo (%) comprometido. |
| `returns-min-48h` | Nunca prometer procesamiento de devoluciones en menos de 48 horas. |
| `volume-discount-table` | Incluye una tabla de descuentos por volumen. |
| `no-carrier-rates` | No revelar tarifas negociadas con transportistas concretos, solo el costo final al cliente. |
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ComplianceRule:
    rule_id: str
    guideline: str
    # Qué tiene que cambiar el generador; va literal en `feedback_for_generator`.
    fix: str


CURRENCY_RULE = "currency-by-country"
SLA_RULE = "on-time-sla"
RETURNS_RULE = "returns-min-48h"
DISCOUNT_TABLE_RULE = "volume-discount-table"
CARRIER_RATES_RULE = "no-carrier-rates"

RULES: dict[str, ComplianceRule] = {
    rule.rule_id: rule
    for rule in (
        ComplianceRule(
            CURRENCY_RULE,
            "El precio se cotiza en USD para operación en Estados Unidos y en EUR para operación en España, según "
            "el país del cliente (client_country).",
            "Expresa todos los importes en la moneda del país del cliente y elimina cualquier importe en otra "
            "moneda (no conviertas: si un precio no existe en esa moneda, déjalo como 'a confirmar').",
        ),
        ComplianceRule(
            SLA_RULE,
            "Toda propuesta debe indicar el SLA de entrega a tiempo (%) que TrackFlow se compromete a cumplir.",
            "Añade una frase con el porcentaje de entregas a tiempo que TrackFlow se compromete a cumplir, con la "
            "cifra de la base de conocimiento (p. ej. 'SLA de entregas a tiempo: 90 % mensual, medido por país').",
        ),
        ComplianceRule(
            RETURNS_RULE,
            "Ninguna propuesta puede prometer procesamiento de devoluciones en menos de 48 horas.",
            "Quita esa promesa: el procesamiento de devoluciones se ofrece en 48 horas o más (p. ej. 'a partir de "
            "48 horas desde la recepción en almacén').",
        ),
        ComplianceRule(
            DISCOUNT_TABLE_RULE,
            "Toda propuesta debe incluir una tabla de descuentos por volumen.",
            "Añade una tabla Markdown (cabecera, separador |---| y al menos dos filas) con los tramos de volumen y "
            "el descuento de cada tramo.",
        ),
        ComplianceRule(
            CARRIER_RATES_RULE,
            "Ninguna propuesta puede revelar tarifas negociadas con transportistas específicos — solo el costo "
            "final ofrecido al cliente.",
            "Elimina las tarifas o descuentos de transportistas concretos; muestra solo el costo final para el "
            "cliente y, si nombras transportistas, hazlo sin precio al lado.",
        ),
    )
}

# Reglas en las que el revisor con modelo puede añadir violaciones (una promesa o una tarifa redactada de forma que
# los patrones no detectan). Moneda, SLA y tabla se verifican solo en código.
LLM_REVIEWED_RULES = frozenset({RETURNS_RULE, CARRIER_RATES_RULE})

CURRENCY_PATTERNS = {
    "USD": re.compile(r"\bUSD\b|US\$|\$|\bd[oó]lar(?:es)?\b|\bdollars?\b", re.IGNORECASE),
    "EUR": re.compile(r"\bEUR\b|€|\beuros?\b", re.IGNORECASE),
}
PERCENT = re.compile(r"\d+(?:[.,]\d+)?\s?%")
SLA_WORDS = re.compile(r"\bSLA\b|a tiempo|on[- ]time|puntualidad", re.IGNORECASE)
RETURN_WORDS = re.compile(r"devoluci|\breturns?\b|log[ií]stica inversa|reverse|reembols|\bRMA\b", re.IGNORECASE)
DURATION = re.compile(
    r"(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>h\b|hrs?\b|horas?\b|hours?\b|d[ií]as?\b|days?\b)", re.IGNORECASE
)
SAME_DAY = re.compile(r"mismo d[ií]a|same[- ]day|en el d[ií]a|en horas|inmediat", re.IGNORECASE)
BELOW_WORDS = re.compile(r"(menos de|por debajo de|inferior(?:es)? a|under|less than)\s*$", re.IGNORECASE)
NEGATION = re.compile(r"\b(no|nunca|jam[aá]s|never|not)\b", re.IGNORECASE)
CARRIERS = re.compile(
    r"\b(UPS|FedEx|DHL|USPS|OnTrac|MRW|SEUR|GLS|Correos|Nacex|CTT|Amazon Logistics)\b", re.IGNORECASE
)
MONEY = re.compile(
    r"\d+(?:[.,]\d+)?\s?(?:USD|EUR|€|\$|d[oó]lares|euros)|(?:US\$|\$|€)\s?\d", re.IGNORECASE
)
NEGOTIATED = re.compile(
    r"tarifa(?:s)? negociada|negotiated rate|descuento del transportista|precio del transportista", re.IGNORECASE
)
TABLE_SEPARATOR = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?$")
DISCOUNT_WORDS = re.compile(r"descuento|discount", re.IGNORECASE)
SENTENCE_BREAK = re.compile(r"(?<=[.;!?])\s+|\n+")


@dataclass(frozen=True)
class Violation:
    rule_id: str
    detail: str
    evidence: str
    source: str = "regla"  # `regla` (código) o `revisor` (modelo, con cita literal verificada)

    def as_dict(self) -> dict[str, str]:
        return {"rule_id": self.rule_id, "detail": self.detail, "evidence": self.evidence, "source": self.source}


def check(draft: str, currency: str | None) -> list[Violation]:
    """Violaciones deterministas del borrador frente a las cinco reglas."""
    return [
        *check_currency(draft, currency),
        *check_sla(draft),
        *check_returns_turnaround(draft),
        *check_discount_table(draft),
        *check_carrier_rates(draft),
    ]


def check_currency(draft: str, currency: str | None) -> list[Violation]:
    if currency not in CURRENCY_PATTERNS:
        return [
            Violation(
                CURRENCY_RULE,
                "La RFP no indica el país del cliente, así que no se puede fijar la moneda: Ventas tiene que "
                "confirmarlo antes de enviar la propuesta.",
                "",
            )
        ]
    violations: list[Violation] = []
    if not CURRENCY_PATTERNS[currency].search(draft):
        violations.append(Violation(CURRENCY_RULE, f"La sección no cotiza ningún importe en {currency}.", ""))
    for other, pattern in CURRENCY_PATTERNS.items():
        if other == currency:
            continue
        for line in _lines(draft):
            if pattern.search(line):
                violations.append(
                    Violation(CURRENCY_RULE, f"Aparece {other} y la moneda del cliente es {currency}.", line)
                )
                break
    return violations


def check_sla(draft: str) -> list[Violation]:
    if any(SLA_WORDS.search(line) and PERCENT.search(line) for line in _lines(draft)):
        return []
    return [Violation(SLA_RULE, "La sección no indica el porcentaje de entregas a tiempo comprometido.", "")]


def check_returns_turnaround(draft: str) -> list[Violation]:
    violations: list[Violation] = []
    for sentence in _sentences(draft):
        if not RETURN_WORDS.search(sentence):
            continue
        promise = _sub_48h_promise(sentence)
        if promise:
            violations.append(
                Violation(RETURNS_RULE, f"Promete un plazo de devoluciones inferior a 48 horas ({promise}).", sentence)
            )
    return violations


def check_discount_table(draft: str) -> list[Violation]:
    for table in markdown_tables(draft):
        if len(table) >= 4 and DISCOUNT_WORDS.search("\n".join(table)):
            return []
    return [
        Violation(
            DISCOUNT_TABLE_RULE,
            "No hay una tabla Markdown de descuentos por volumen (cabecera, separador y al menos dos tramos).",
            "",
        )
    ]


def check_carrier_rates(draft: str) -> list[Violation]:
    violations: list[Violation] = []
    for line in _lines(draft):
        carrier = CARRIERS.search(line)
        if carrier and (MONEY.search(line) or NEGOTIATED.search(line)):
            violations.append(
                Violation(
                    CARRIER_RATES_RULE,
                    f"Muestra un precio o tarifa junto al transportista {carrier.group()}.",
                    line,
                )
            )
    return violations


def markdown_tables(text: str) -> list[list[str]]:
    """Tablas Markdown del texto (líneas que empiezan por `|` con una línea separadora `|---|`)."""
    tables: list[list[str]] = []
    current: list[str] = []
    for line in [*text.splitlines(), ""]:
        stripped = line.strip()
        if stripped.startswith("|"):
            current.append(stripped)
            continue
        if len(current) >= 2 and TABLE_SEPARATOR.match(current[1]):
            tables.append(current)
        current = []
    return tables


def evidence_in(draft: str, evidence: str) -> bool:
    """La cita del revisor aparece literal en el borrador (sin contar espacios ni mayúsculas)."""
    normalized = _normalize(evidence)
    return bool(normalized) and normalized in _normalize(draft)


def _sub_48h_promise(sentence: str) -> str | None:
    """El plazo por debajo de 48 h que promete la frase (`24 horas`, `1 día`, `menos de 48 h`, `mismo día`)."""
    same_day = SAME_DAY.search(sentence)
    if same_day and not _negated(sentence, same_day.start()):
        return same_day.group()
    for match in DURATION.finditer(sentence):
        if _negated(sentence, match.start()):
            continue
        value = float(match.group("value").replace(",", "."))
        hours = value * 24 if match.group("unit").lower().startswith("d") else value
        if hours < 48 or (hours == 48 and BELOW_WORDS.search(sentence[: match.start()])):
            return match.group()
    return None


def _negated(sentence: str, position: int) -> bool:
    # "no prometemos devoluciones en menos de 48 horas" no es una promesa.
    window = sentence[max(0, position - 40) : position]
    return bool(NEGATION.search(window))


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in SENTENCE_BREAK.split(text) if part.strip()]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()
