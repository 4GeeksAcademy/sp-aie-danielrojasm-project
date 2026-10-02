"""Graba la evidencia de la memoria del agente (auto-evaluación y ciclos completos de propuesta → decisión).

Uso (desde la raíz del monorepo, con Qdrant indexado, Redis en `REDIS_URL` y el `.env` con el gateway LLM):

    uv run python scripts/record_memory_evidence.py

Ejecuta el agente real (mismo grafo que `POST /agent/query`) con los casos de `data/eval/agent/memory-cases.json`.
La memoria usa un espacio de nombres propio en Redis (`trackflow:agent_memory:evidence`), que se vacía antes de
cada caso: nunca toca la memoria real del agente. Escribe `data/eval/agent/memory/<id>.json` con cada turno
(mensaje, respuesta, propuesta, decisión, memoria recordada y entradas después del turno) y el registro de auditoría.
Después, los evals se ejecutan contra esos ficheros sin volver a llamar al modelo:

    uv run pytest tests/pipelines/test_agent_memory_evals.py -v
"""

import json
import logging
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=False)

import redis  # noqa: E402

from services.support_agent.memory.store import DEFAULT_REDIS_URL, NAMESPACE, MemoryStore, use_memory_store  # noqa: E402
from services.support_agent.runner import run_agent  # noqa: E402
from services.support_agent.tracing import executed_nodes, load_trace  # noqa: E402


CASES_PATH = ROOT / "data" / "eval" / "agent" / "memory-cases.json"
OUTPUT_DIR = ROOT / "data" / "eval" / "agent" / "memory"
EVIDENCE_USER = "cx-agent-1"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    client = redis.Redis.from_url(os.getenv("REDIS_URL") or DEFAULT_REDIS_URL, decode_responses=True)
    store = MemoryStore(client, namespace=f"{NAMESPACE}:evidence")
    use_memory_store(store)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for case in cases["self_evaluation"]:
        turns = [{"conversation": "a", "user": EVIDENCE_USER, "message": case["message"]}]
        record(store, case["id"], turns, {"expect_proposal": case["expect_proposal"], "category": case.get("category")})
    for case in cases["conversations"]:
        record(store, case["id"], case["turns"], {"description": case["description"]})
    store.clear()
    return 0


def record(store: MemoryStore, case_id: str, turns: list[dict], extra: dict) -> None:
    store.clear()
    conversations: dict[str, str] = {}
    recorded = []
    for turn in turns:
        conversation_id = conversations.setdefault(turn["conversation"], uuid.uuid4().hex)
        run = run_agent(turn["message"], conversation_id=conversation_id, user_id=turn["user"])
        trace = load_trace(run.trace_path)
        recorded.append(
            {
                "conversation": turn["conversation"],
                "user": turn["user"],
                "message": turn["message"],
                "answer": run.state["answer"],
                "nodes": executed_nodes(trace),
                "sources_used": trace["sources_used"],
                "memory_candidate": run.state.get("memory_candidate"),
                "memory_proposal": run.state.get("memory_proposal"),
                "memory_decision": run.state.get("memory_decision"),
                "memories_recalled": run.state.get("memories", []),
                "memory_after": [entry.model_dump(mode="json") for entry in store.entries()],
            }
        )
    evidence = {"id": case_id, **extra, "turns": recorded, "audit": store.audit_log()}
    path = OUTPUT_DIR / f"{case_id}.json"
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    proposals = sum(1 for turn in recorded if turn["memory_proposal"])
    decisions = [turn["memory_decision"]["outcome"] for turn in recorded if turn["memory_decision"]]
    print(f"{case_id}: propuestas={proposals} decisiones={decisions} -> {path.relative_to(ROOT)}")


if __name__ == "__main__":
    raise SystemExit(main())
