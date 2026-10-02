"""Interfaz explícita de lectura/escritura de la memoria del agente, sobre Redis.

Claves (prefijo `trackflow:agent_memory`; nada se escribe en Qdrant ni en `trackflow_knowledge`):

- `:entries` (hash): una entrada consolidada por sujeto (`MemoryEntry` en JSON). Solo se escribe con
  `consolidate()`, después de una decisión explícita del usuario.
- `:pending` (hash): la propuesta pendiente de cada usuario (`MemoryProposal`), como mucho una por usuario.
- `:audit` (stream, solo se añade): una entrada por evento. Cada propuesta tiene un `proposed` y exactamente un
  `decision` (`approved`, `edited`, `rejected` o `discarded`, también cuando caduca sin respuesta). Además: `blocked`
  (el modelo propuso algo prohibido), `skipped` (ya había una pendiente o ya estaba recordado), `superseded`,
  `evicted` y `expired_memory` (consolidación y limpieza). No se recorta: es el rastro de quién autorizó cada escritura.

Redis corre con AOF y `noeviction` (`docker-compose.yml`), así que la memoria no desaparece por presión de memoria.
Cualquier fallo de Redis es un `MemoryUnavailableError`: el agente sigue respondiendo y avisa de que no puede recordar.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any, TypeVar

import redis

from services.support_agent.memory import policy
from services.support_agent.memory.models import (
    DecisionClassification,
    MemoryDraft,
    MemoryEntry,
    MemoryFact,
    MemoryProposal,
    Resolution,
)


logger = logging.getLogger("trackflow.agent.memory")

NAMESPACE = "trackflow:agent_memory"
DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/0"
WRITE_RETRIES = 5
# Un hecho casi idéntico a uno ya recordado no se vuelve a proponer.
ALREADY_REMEMBERED_SIMILARITY = 0.9

T = TypeVar("T")


class MemoryUnavailableError(RuntimeError):
    """Redis no respondió: la memoria no se puede leer ni escribir ahora mismo."""


class MemoryStore:
    def __init__(self, client: redis.Redis, namespace: str = NAMESPACE):
        self.client = client
        self.namespace = namespace
        self.entries_key = f"{namespace}:entries"
        self.pending_key = f"{namespace}:pending"
        self.audit_key = f"{namespace}:audit"

    # --- Lectura ------------------------------------------------------------------------------------

    def recall(self, question: str, now: datetime, limit: int = policy.MAX_RECALLED) -> list[MemoryEntry]:
        """Entradas relevantes para la pregunta: sujeto citado (transportista, zona, cliente) o palabras en común."""
        def alive(entries: dict[str, MemoryEntry], events: list[dict[str, Any]]) -> list[MemoryEntry]:
            self._expire(entries, now, events)
            return list(entries.values())

        entries = self._write(alive)
        normalized = policy.normalize(question)
        words = policy.content_words(question)
        scored = []
        for entry in entries:
            subject_hits = sum(1 for keyword in entry.keywords if re.search(rf"\b{re.escape(keyword)}\b", normalized))
            fact_words = set().union(*(policy.content_words(fact.fact) for fact in entry.facts))
            score = 2 * subject_hits + len(words & fact_words)
            if score >= 2:
                scored.append((score, entry.updated_at, entry))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [entry for _, _, entry in scored[:limit]]

    def entries(self) -> list[MemoryEntry]:
        with self._guard():
            raw = self.client.hgetall(self.entries_key)
        return sorted((MemoryEntry.model_validate_json(value) for value in raw.values()), key=lambda e: e.subject_key)

    def pending_for(self, user_id: str, conversation_id: str, now: datetime) -> MemoryProposal | None:
        """La propuesta pendiente del usuario en esta conversación. Antes descarta las caducadas (de cualquiera)."""
        with self._guard():
            self._discard_expired_pending(now)
            raw = self.client.hget(self.pending_key, user_id)
        if raw is None:
            return None
        pending = MemoryProposal.model_validate_json(raw)
        return pending if pending.conversation_id == conversation_id else None

    def already_remembered(self, proposal: MemoryProposal) -> bool:
        with self._guard():
            raw = self.client.hget(self.entries_key, proposal.subject_key)
        if raw is None:
            return False
        entry = MemoryEntry.model_validate_json(raw)
        return any(policy.similarity(fact.fact, proposal.fact) >= ALREADY_REMEMBERED_SIMILARITY for fact in entry.facts)

    def audit_log(self) -> list[dict[str, Any]]:
        with self._guard():
            records = self.client.xrange(self.audit_key)
        return [{"id": record_id, "event": fields["event"], "at": fields["at"], **json.loads(fields["data"])}
                for record_id, fields in records]

    # --- Escritura ----------------------------------------------------------------------------------

    def open_pending(self, proposal: MemoryProposal) -> bool:
        """Guarda la propuesta como pendiente. False si el usuario ya tiene una sin resolver (no se lanza otra)."""
        with self._guard():
            opened = self.client.hsetnx(self.pending_key, proposal.user_id, proposal.model_dump_json())
        if opened:
            self._audit("proposed", proposal.proposed_at, **_proposal_fields(proposal), reason=proposal.reason,
                        expires_at=proposal.expires_at.isoformat(), source_message=proposal.source_message)
        return bool(opened)

    def take_pending(self, user_id: str, proposal_id: str) -> bool:
        """Retira la propuesta para resolverla. False si otra petición ya la resolvió."""
        with self._guard():
            with self.client.pipeline() as pipe:
                try:
                    pipe.watch(self.pending_key)
                    raw = pipe.hget(self.pending_key, user_id)
                    if raw is None or MemoryProposal.model_validate_json(raw).proposal_id != proposal_id:
                        return False
                    pipe.multi()
                    pipe.hdel(self.pending_key, user_id)
                    pipe.execute()
                except redis.WatchError:
                    return False
        return True

    def consolidate(self, proposal: MemoryProposal, fact: str, now: datetime) -> MemoryEntry:
        """Escribe un hecho aprobado en la entrada de su sujeto: deduplica, acota y descarta lo caducado."""

        def mutate(entries: dict[str, MemoryEntry], events: list[dict[str, Any]]) -> MemoryEntry:
            self._expire(entries, now, events)
            entry = entries.get(proposal.subject_key) or MemoryEntry(
                subject_key=proposal.subject_key,
                category=proposal.category,
                subject=proposal.subject,
                keywords=proposal.keywords,
                facts=[],
                updated_at=now,
            )
            facts = []
            for previous in entry.facts:
                if policy.similarity(previous.fact, fact) >= policy.DUPLICATE_SIMILARITY:
                    events.append(_event("superseded", entry, previous, by=proposal.proposal_id))
                else:
                    facts.append(previous)
            facts.append(
                MemoryFact(
                    fact=fact,
                    proposal_id=proposal.proposal_id,
                    approved_by=proposal.user_id,
                    approved_at=now,
                    expires_at=now + policy.FACT_TTL[proposal.category],
                )
            )
            while len(facts) > policy.MAX_FACTS_PER_SUBJECT:
                events.append(_event("evicted", entry, facts.pop(0), reason="max_facts_per_subject"))
            entry = entry.model_copy(
                update={"facts": facts, "updated_at": now, "keywords": sorted({*entry.keywords, *proposal.keywords})}
            )
            entries[entry.subject_key] = entry
            others = sorted(
                (other for other in entries.values()
                 if other.category == entry.category and other.subject_key != entry.subject_key),
                key=lambda other: other.updated_at,
            )
            while len(others) + 1 > policy.MAX_SUBJECTS[entry.category]:
                oldest = others.pop(0)
                del entries[oldest.subject_key]
                events.extend(_event("evicted", oldest, old, reason="max_subjects") for old in oldest.facts)
            return entry

        return self._write(mutate, at=now)

    def record_decision(
        self,
        proposal: MemoryProposal,
        resolution: Resolution,
        *,
        classification: DecisionClassification | None,
        message: str,
        run_id: str,
        at: datetime,
    ) -> None:
        self._audit(
            "decision",
            at,
            **_proposal_fields(proposal),
            decision_run_id=run_id,
            outcome=resolution.outcome,
            reason=resolution.reason,
            stored_fact=resolution.fact,
            label=classification.decision if classification else None,
            confidence=classification.confidence if classification else None,
            decided_by=classification.decided_by if classification else "default",
            message=policy.redact(message),
        )

    def record_blocked(
        self,
        draft: MemoryDraft,
        violations: list[str],
        *,
        message: str,
        user_id: str,
        conversation_id: str,
        run_id: str,
        at: datetime,
    ) -> None:
        self._audit(
            "blocked",
            at,
            user_id=user_id,
            conversation_id=conversation_id,
            run_id=run_id,
            category=draft.category,
            fact=policy.redact(draft.fact),
            violations=violations,
            message=policy.redact(message),
        )

    def record_skipped(self, proposal: MemoryProposal, reason: str) -> None:
        self._audit("skipped", proposal.proposed_at, **_proposal_fields(proposal), reason=reason)

    def clear(self) -> None:
        """Borra la memoria, las pendientes y la auditoría de este espacio de nombres (scripts de evidencia)."""
        with self._guard():
            self.client.delete(self.entries_key, self.pending_key, self.audit_key)

    # --- Internos -----------------------------------------------------------------------------------

    def _write(
        self, mutate: Callable[[dict[str, MemoryEntry], list[dict[str, Any]]], T], at: datetime | None = None
    ) -> T:
        """Lee las entradas, aplica `mutate` y escribe solo lo que cambió, en una transacción optimista."""
        with self._guard():
            for _ in range(WRITE_RETRIES):
                with self.client.pipeline() as pipe:
                    try:
                        pipe.watch(self.entries_key)
                        raw = pipe.hgetall(self.entries_key)
                        entries = {key: MemoryEntry.model_validate_json(value) for key, value in raw.items()}
                        events: list[dict[str, Any]] = []
                        result = mutate(entries, events)
                        updates = {key: entry.model_dump_json() for key, entry in entries.items()
                                   if raw.get(key) != entry.model_dump_json()}
                        deletes = [key for key in raw if key not in entries]
                        if updates or deletes:
                            pipe.multi()
                            if deletes:
                                pipe.hdel(self.entries_key, *deletes)
                            if updates:
                                pipe.hset(self.entries_key, mapping=updates)
                            pipe.execute()
                    except redis.WatchError:
                        continue
                for event in events:
                    self._audit(event.pop("event"), event.pop("at", None) or at, **event)
                return result
        raise MemoryUnavailableError("La memoria cambió durante la escritura demasiadas veces seguidas.")

    @staticmethod
    def _expire(entries: dict[str, MemoryEntry], now: datetime, events: list[dict[str, Any]]) -> None:
        for key, entry in list(entries.items()):
            alive = [fact for fact in entry.facts if fact.expires_at > now]
            if len(alive) == len(entry.facts):
                continue
            events.extend(
                {**_event("expired_memory", entry, fact), "at": now} for fact in entry.facts if fact.expires_at <= now
            )
            if alive:
                entries[key] = entry.model_copy(update={"facts": alive})
            else:
                del entries[key]

    def _discard_expired_pending(self, now: datetime) -> None:
        for user_id, raw in self.client.hgetall(self.pending_key).items():
            pending = MemoryProposal.model_validate_json(raw)
            if pending.expires_at <= now and self.take_pending(user_id, pending.proposal_id):
                self.record_decision(
                    pending,
                    Resolution(outcome="discarded", reason="expired_without_answer"),
                    classification=None,
                    message="",
                    run_id="",
                    at=now,
                )

    def _audit(self, event: str, at: datetime, **fields: Any) -> None:
        with self._guard():
            self.client.xadd(
                self.audit_key,
                {"event": event, "at": at.isoformat(), "data": json.dumps(fields, ensure_ascii=False, default=str)},
            )
        logger.info(
            "agent_memory event=%s proposal_id=%s user_id=%s outcome=%s reason=%s",
            event,
            fields.get("proposal_id", "-"),
            fields.get("user_id", "-"),
            fields.get("outcome", "-"),
            fields.get("reason") or ",".join(fields.get("violations", [])) or "-",
        )

    @contextmanager
    def _guard(self) -> Iterator[None]:
        try:
            yield
        except redis.RedisError as error:
            logger.error("agent_memory Redis no disponible: %s", type(error).__name__)
            raise MemoryUnavailableError("La memoria del agente no está disponible.") from error


def _proposal_fields(proposal: MemoryProposal) -> dict[str, Any]:
    return {
        "proposal_id": proposal.proposal_id,
        "user_id": proposal.user_id,
        "conversation_id": proposal.conversation_id,
        "run_id": proposal.run_id,
        "category": proposal.category,
        "subject_key": proposal.subject_key,
        "proposed_fact": proposal.fact,
    }


def _event(event: str, entry: MemoryEntry, fact: MemoryFact, **extra: Any) -> dict[str, Any]:
    return {
        "event": event,
        "subject_key": entry.subject_key,
        "proposal_id": fact.proposal_id,
        "user_id": fact.approved_by,
        "fact": fact.fact,
        **extra,
    }


_store: MemoryStore | None = None


def get_memory_store() -> MemoryStore:
    """El almacén del proceso, sobre `REDIS_URL` (la conexión se abre con la primera operación)."""
    global _store
    if _store is None:
        client = redis.Redis.from_url(
            os.getenv("REDIS_URL") or DEFAULT_REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=2,
        )
        _store = MemoryStore(client)
    return _store


def use_memory_store(store: MemoryStore | None) -> None:
    """Sustituye el almacén del proceso (tests y scripts de evidencia con su propio espacio de nombres)."""
    global _store
    _store = store
