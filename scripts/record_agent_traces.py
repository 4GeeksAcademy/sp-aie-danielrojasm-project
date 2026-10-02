"""Graba los traces que evalúan los evals del agente LangGraph.

Uso (desde la raíz del monorepo, con Qdrant en marcha, `setup()` ya ejecutado y el `.env` con el gateway LLM):

    uv run python scripts/record_agent_traces.py

Ejecuta el grafo compilado de `services/support_agent` una vez por caso de `data/eval/agent/eval-cases.json` y
escribe cada trace en `data/eval/agent/traces/<id>.json` (`run_id` = id del caso). Después, los evals se ejecutan
contra esos traces sin volver a llamar a Qdrant ni al modelo:

    uv run pytest tests/pipelines/test_agent_evals.py -v
"""

import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=False)

from services.support_agent.runner import AgentRunError, run_agent  # noqa: E402


CASES_PATH = ROOT / "data" / "eval" / "agent" / "eval-cases.json"
TRACES_DIR = ROOT / "data" / "eval" / "agent" / "traces"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]
    failed = 0
    for case in cases:
        try:
            run = run_agent(case["question"], run_id=case["id"], directory=TRACES_DIR)
        except AgentRunError as error:
            failed += 1
            print(f"{case['id']}: FALLÓ en {error.node} (trace: {error.trace_path.relative_to(ROOT)})")
            continue
        print(f"{case['id']}: {run.trace_path.relative_to(ROOT)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
