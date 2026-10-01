"""Evaluación de la recuperación del RAG comercial: Recall@3 y umbral `min_score`.

Uso (desde la raíz del monorepo, con Qdrant en marcha y `setup()` ya ejecutado):

    uv run python scripts/evaluate_rag_retrieval.py

1. Por cada pregunta de `data/eval/test-queries.json`, embebe la pregunta una sola vez y pide a Qdrant los 3
   vecinos más cercanos (`search_chunks`, el mismo camino que `retrieve()`).
2. Recall@3 = preguntas cuyo chunk esperado (`source_document` + `chunk_index`) está entre esos 3 / total.
   Se calcula sin umbral (calidad del ranking) y aplicando `MIN_SCORE` (lo que de verdad llega al prompt).
3. Las preguntas `out_of_scope` no tienen respuesta en los documentos: su mejor puntuación debería quedar por
   debajo de `MIN_SCORE`, para que el modelo diga que no hay información en lugar de recibir contexto malo.

Escribe `data/eval/rag/retrieval_report.json` y sale con código 1 si Recall@3 (con umbral) no llega al objetivo.
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

from data.pipelines.rag import MIN_SCORE, search_chunks  # noqa: E402
from data.process.rag import embed  # noqa: E402


QUERIES_PATH = ROOT / "data" / "eval" / "test-queries.json"
REPORT_PATH = ROOT / "data" / "eval" / "rag" / "retrieval_report.json"


def chunk_key(payload: dict) -> str:
    return f"{payload['source_document']}#{payload['chunk_index']}"


def evaluate(spec: dict, min_score: float) -> dict:
    k = spec["k"]
    rows = []
    for item in spec["queries"]:
        hits = search_chunks(embed(item["question"]), k)
        expected = chunk_key(item["expected"])
        ranked = [(chunk_key(hit.payload), round(hit.score, 4)) for hit in hits]
        rank = next((position for position, (key, _) in enumerate(ranked, start=1) if key == expected), None)
        expected_score = ranked[rank - 1][1] if rank else None
        rows.append(
            {
                "id": item["id"],
                "expected": expected,
                "rank": rank,
                "expected_score": expected_score,
                "hit_at_k": rank is not None,
                "hit_at_k_with_threshold": rank is not None and expected_score >= min_score,
                "top_k": [{"chunk": key, "score": score} for key, score in ranked],
            }
        )
    out_of_scope = []
    for item in spec.get("out_of_scope", []):
        hits = search_chunks(embed(item["question"]), 1)
        best = round(hits[0].score, 4) if hits else None
        out_of_scope.append(
            {
                "id": item["id"],
                "best_chunk": chunk_key(hits[0].payload) if hits else None,
                "best_score": best,
                "rejected_by_threshold": best is None or best < min_score,
            }
        )
    total = len(rows)
    covered = sorted({row["expected"].split("#")[0] for row in rows})
    expected_scores = [row["expected_score"] for row in rows if row["expected_score"] is not None]
    return {
        "collection": spec["collection"],
        "k": k,
        "min_score": min_score,
        "questions": total,
        "documents_covered": covered,
        "recall_at_k": round(sum(row["hit_at_k"] for row in rows) / total, 4),
        "recall_at_k_with_threshold": round(sum(row["hit_at_k_with_threshold"] for row in rows) / total, 4),
        "recall_target": spec["recall_target"],
        "lowest_expected_score": min(expected_scores) if expected_scores else None,
        "highest_out_of_scope_score": max(
            (row["best_score"] for row in out_of_scope if row["best_score"] is not None), default=None
        ),
        "out_of_scope_rejected": sum(row["rejected_by_threshold"] for row in out_of_scope),
        "out_of_scope_total": len(out_of_scope),
        "results": rows,
        "out_of_scope": out_of_scope,
    }


def main() -> int:
    logging.basicConfig(level=logging.WARNING)
    spec = json.loads(QUERIES_PATH.read_text(encoding="utf-8"))
    report = evaluate(spec, MIN_SCORE)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for row in report["results"]:
        status = "OK " if row["hit_at_k_with_threshold"] else "FALLO"
        print(f"{status} {row['id']:<24} esperado={row['expected']:<20} rank={row['rank']} score={row['expected_score']}")
    for row in report["out_of_scope"]:
        status = "OK " if row["rejected_by_threshold"] else "FALLO"
        print(f"{status} fuera de alcance {row['id']:<18} mejor={row['best_chunk']} score={row['best_score']}")
    print(
        f"\nRecall@{report['k']}: {report['recall_at_k']:.0%} sin umbral, "
        f"{report['recall_at_k_with_threshold']:.0%} con min_score={MIN_SCORE} "
        f"(objetivo {report['recall_target']:.0%}); fuera de alcance rechazadas: "
        f"{report['out_of_scope_rejected']}/{report['out_of_scope_total']}"
    )
    print(
        f"Peor score esperado: {report['lowest_expected_score']} · "
        f"mejor score fuera de alcance: {report['highest_out_of_scope_score']}"
    )
    print(f"Informe: {REPORT_PATH.relative_to(ROOT)}")
    return 0 if report["recall_at_k_with_threshold"] >= report["recall_target"] else 1


if __name__ == "__main__":
    sys.exit(main())
