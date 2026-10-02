"""Qué puede recordar el agente de soporte de TrackFlow y qué nunca, sin depender del criterio del modelo.

Se puede recordar (CONTEXT de TrackFlow), y nada más:

- `carrier_rule`: cobertura o rutas corregidas de uno de los transportistas con los que opera TrackFlow, por país.
- `incident_context`: causa conocida de incidencias recurrentes en una zona o ruta.
- `client_preference`: preferencia de un cliente B2B recurrente sobre su reporte mensual.

Nunca se guarda, lo pida quien lo pida (`forbidden_content`): ubicaciones exactas de clientes B2C o B2B (direcciones,
códigos postales, coordenadas), rutas o ubicaciones internas de un almacén, datos de un solo paquete o ticket, ni
contratos comerciales activos o en negociación. Además, el hecho tiene que estar respaldado por una cita del mensaje
del usuario (el modelo no puede proponer algo que sacó de la base de conocimiento o que dedujo él).

La consolidación agrupa por sujeto (transportista + país, zona + país, cliente), no por ticket, para que las reglas
no queden fragmentadas en decenas de entradas sueltas.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone

from services.support_agent.memory.models import MemoryCategory, MemoryDraft, MemoryProposal


CATEGORIES: tuple[MemoryCategory, ...] = ("carrier_rule", "incident_context", "client_preference")
CATEGORY_LABELS: dict[MemoryCategory, str] = {
    "carrier_rule": "Transportistas",
    "incident_context": "Incidencias recurrentes",
    "client_preference": "Preferencias de cliente B2B",
}

# Una propuesta sin respuesta caduca y se descarta: nunca se aprueba por silencio.
PENDING_TTL = timedelta(minutes=30)
# Las incidencias son coyunturales ("esta semana"); las reglas de transportista se revisan cada semestre.
FACT_TTL: dict[MemoryCategory, timedelta] = {
    "carrier_rule": timedelta(days=180),
    "incident_context": timedelta(days=14),
    "client_preference": timedelta(days=365),
}
MAX_FACTS_PER_SUBJECT = 3
# carrier_rule ya está acotada por las parejas transportista + país de `CARRIERS` (8).
MAX_SUBJECTS: dict[MemoryCategory, int] = {"carrier_rule": 8, "incident_context": 20, "client_preference": 50}
MAX_FACT_LENGTH = 300
MAX_RECALLED = 5
# Por debajo de esta confianza, la decisión del usuario se trata como ambigua y la propuesta se descarta.
DECISION_CONFIDENCE = 0.75
# Dos hechos del mismo sujeto con este solapamiento de palabras son el mismo hecho: el nuevo sustituye al anterior.
DUPLICATE_SIMILARITY = 0.6
# Parte de las palabras de `cita_usuario` que tiene que aparecer en el mensaje del usuario.
QUOTE_COVERAGE = 0.8

# Transportistas de TrackFlow y países donde operan (base de conocimiento: cobertura de transportistas).
CARRIERS: dict[str, tuple[str, frozenset[str]]] = {
    "ups": ("UPS", frozenset({"US"})),
    "fedex": ("FedEx", frozenset({"US"})),
    "dhl": ("DHL", frozenset({"US", "ES"})),
    "mrw": ("MRW", frozenset({"ES"})),
    "seur": ("SEUR", frozenset({"ES"})),
    "local": ("Transportista local de Zaragoza", frozenset({"ES"})),
}
COUNTRIES = {
    "us": "US", "usa": "US", "eeuu": "US", "ee uu": "US", "estados unidos": "US", "los angeles": "US",
    "es": "ES", "espana": "ES", "spain": "ES", "zaragoza": "ES",
}

_ADDRESS_ES = (
    r"\b(?:calle|c/|avda|avenida|plaza|pza|paseo|ronda|carretera|ctra|camino|travesia|poligono|urbanizacion|"
    r"barrio)\b[^.;\n]{0,40}?\d+"
)
_ADDRESS_EN = (
    r"\b\d{1,6}\s+(?:[a-z0-9]+\s+){0,4}(?:street|st|avenue|ave|road|rd|boulevard|blvd|drive|dr|lane|ln|way|"
    r"court|ct|place|pl|terrace|highway|hwy)\b"
)
FORBIDDEN_PATTERNS: dict[str, re.Pattern[str]] = {
    # Ubicación de clientes B2C (destinatarios) y B2B (marcas): direcciones, códigos postales, pisos, coordenadas.
    "customer_location": re.compile(
        "|".join(
            [
                _ADDRESS_ES,
                _ADDRESS_EN,
                r"\b\d{5}(?:-\d{4})?\b",
                r"\b(?:piso|planta|puerta|portal|escalera|apt|apartment|suite|unit)\s*\.?\s*\d",
                r"-?\d{1,3}\.\d{3,}\s*,\s*-?\d{1,3}\.\d{3,}",
                # "dirección" no entra: también es la Dirección de la empresa.
                r"\b(?:domicilio|address|codigo postal|zip code)\b",
            ]
        )
    ),
    # Rutas y ubicaciones internas del almacén: información de seguridad física.
    "warehouse_internal": re.compile(
        r"\b(?:pasillo|estanteria|estante|rack|muelle|hueco|ubicacion interna|zona de picking|ruta interna|"
        r"recorrido interno|plano del almacen|codigo de acceso|codigo de la puerta|alarma|camara de seguridad|"
        r"aisle|shelf|bin location|loading dock|dock door)\w*"
    ),
    # Un solo paquete o ticket: tracking, número de pedido o de ticket concreto.
    "single_parcel": re.compile(
        r"\b[a-z]{1,4}-?\d{4,}(?:-\d+)*\b|\b\d[a-z0-9]{9,}\b|"
        r"\b(?:tracking|seguimiento|pedido|paquete|envio|ticket|incidencia|order)\s*(?:n[o.]*\s*)?#?\s*\d+|#\d+"
    ),
    # Contratos activos o en negociación: los gestiona el CRM del equipo comercial.
    "commercial_contract": re.compile(
        r"\b(?:contrato|negociacion|negociando|negociar|renovacion|descuento|tarifa (?:especial|preferencial|"
        r"negociada|pactada)|precio pactado|propuesta comercial|oferta comercial|clausula|licitacion|rfp|"
        r"contract|negotiation|discount)\w*"
    ),
}
VIOLATION_MESSAGES = {
    "customer_location": "ubicación exacta de un cliente B2C o B2B",
    "warehouse_internal": "ruta o ubicación interna de un almacén",
    "single_parcel": "datos de un solo paquete o ticket",
    "commercial_contract": "contrato comercial activo o en negociación",
}

STOPWORDS = frozenset(
    "para pero porque como cuando donde desde hasta sobre entre esta este esto estos estas esos esas aquel "
    "tiene tienen hacer hace hemos habia sido estan estamos todo todos toda todas otra otro otros mismo misma "
    "solo cada mucho muchos poco mismo ahora antes despues siempre nunca tambien ademas segun quiere quieren "
    "cual cuales cuanto cuanta tengo tenemos usar usamos uso envio envios hay".split()
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize(text: str) -> str:
    """Minúsculas, sin tildes y con los espacios colapsados (para comparar y buscar patrones)."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return " ".join("".join(char for char in decomposed if not unicodedata.combining(char)).split())


def content_words(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", normalize(text)) if len(word) >= 4 and word not in STOPWORDS}


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalize(text)).strip("-")


def forbidden_content(*texts: str | None) -> list[str]:
    """Códigos de lo que nunca puede entrar en la memoria y aparece en alguno de los textos."""
    normalized = normalize(" ".join(text for text in texts if text))
    return [code for code, pattern in FORBIDDEN_PATTERNS.items() if pattern.search(normalized)]


def redact(text: str) -> str:
    """El texto sin lo que nunca debe guardarse; es lo que llega al registro de auditoría."""
    normalized = normalize(text)
    for pattern in FORBIDDEN_PATTERNS.values():
        normalized = pattern.sub("[redactado]", normalized)
    return normalized[:500]


def canonical_carrier(name: str | None) -> str | None:
    value = normalize(name or "").replace(" ", "")
    if not value:
        return None
    if "local" in value:
        return "local"
    return next((key for key in CARRIERS if key == value or value.startswith(key)), None)


def canonical_country(name: str | None) -> str | None:
    return COUNTRIES.get(normalize(name or ""))


def similarity(first: str, second: str) -> float:
    a, b = content_words(first), content_words(second)
    return len(a & b) / len(a | b) if a and b else 0.0


def build_proposal(
    draft: MemoryDraft,
    *,
    message: str,
    user_id: str,
    conversation_id: str,
    run_id: str,
    now: datetime,
) -> MemoryProposal | list[str]:
    """La propuesta lista para preguntar al usuario, o los motivos por los que no se puede proponer."""
    violations: list[str] = []
    category = draft.category if draft.category in CATEGORIES else None
    fact = " ".join(draft.fact.split())
    if category is None:
        violations.append("category_not_allowed")
    if len(fact) > MAX_FACT_LENGTH:
        violations.append("fact_too_long")
    violations += forbidden_content(fact, draft.zone, draft.client, draft.reason)
    if not _quoted_from(draft.user_quote, message):
        violations.append("not_stated_by_user")

    subject = _subject(category, draft, violations) if category else None
    if violations or subject is None:
        return violations or ["missing_subject"]
    subject_key, label, keywords = subject
    return MemoryProposal(
        proposal_id=uuid.uuid4().hex,
        category=category,
        subject_key=subject_key,
        subject=label,
        keywords=keywords,
        fact=fact,
        reason=" ".join(draft.reason.split())[:MAX_FACT_LENGTH],
        user_id=user_id,
        conversation_id=conversation_id,
        run_id=run_id,
        source_message=redact(message),
        proposed_at=now,
        expires_at=now + PENDING_TTL,
    )


def check_edited_fact(fact: str) -> list[str]:
    """Un hecho editado por el usuario pasa por las mismas prohibiciones que una propuesta del modelo."""
    violations = forbidden_content(fact)
    if len(fact) > MAX_FACT_LENGTH:
        violations.append("fact_too_long")
    return violations


def _quoted_from(quote: str, message: str) -> bool:
    words = content_words(quote)
    if not words:
        return False
    return len(words & content_words(message)) / len(words) >= QUOTE_COVERAGE


def _subject(
    category: MemoryCategory, draft: MemoryDraft, violations: list[str]
) -> tuple[str, str, list[str]] | None:
    """Clave de consolidación, etiqueta legible y palabras clave de recuperación del sujeto de la propuesta."""
    country = canonical_country(draft.country)
    if category == "carrier_rule":
        carrier = canonical_carrier(draft.carrier)
        if carrier is None:
            violations.append("unknown_carrier")
            return None
        name, countries = CARRIERS[carrier]
        if country not in countries:
            violations.append("carrier_country_mismatch")
            return None
        return f"carrier_rule:{carrier}:{country}", f"{name} ({country})", [carrier]
    if category == "incident_context":
        zone = " ".join((draft.zone or "").split())
        if not zone or country is None:
            violations.append("missing_subject")
            return None
        return f"incident_context:{country}:{slug(zone)}", f"{zone} ({country})", sorted(content_words(zone))
    client = " ".join((draft.client or "").split())
    if not client:
        violations.append("missing_subject")
        return None
    return f"client_preference:{slug(client)}", client, sorted(content_words(client))
