"""CLI del flujo de RFPs (no es un segundo API: la recepción normal es `POST /rfps` desde el backoffice).

    uv run --env-file .env python scripts/rfp_intake.py smoke <ruta.pdf>
        Ejecuta el grafo de la Parte 1 sobre un PDF local e imprime el resultado en JSON. No toca la base de datos.

    uv run --env-file .env python scripts/rfp_intake.py reprocess <ticket_id> [--force]
        Vuelve a ejecutar el análisis de un ticket en este proceso (p. ej. tras agotar los reintentos del worker).
        Solo procesa tickets en `analizando`; `--force` borra antes el resultado de un ticket ya cerrado.

    uv run --env-file .env python scripts/rfp_intake.py generate <ticket_id> [--max-iterations N]
        Ejecuta la Parte 2 (generación y evaluación por departamento) de un ticket en `analisis_completo`, o de uno
        que se quedó en `generando_borrador` / `en_evaluación` tras agotar los reintentos del worker.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data.pipelines.rfp_intake import graph, response_runner, runner  # noqa: E402


def smoke(pdf_path: Path) -> int:
    state = graph.run_graph("smoke", str(pdf_path))
    result = {
        "classification": state["classification"],
        "metadata": state.get("metadata"),
        "readability": state.get("readability"),
        "assignments": state.get("assignments"),
        "synthesis": state.get("synthesis"),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def reprocess(ticket_id: str, force: bool) -> int:
    engine = runner.intake_engine()
    if force:
        runner.reset_ticket(engine, ticket_id)
    status = runner.process_ticket(engine, ticket_id)
    print(f"ticket {ticket_id}: {status}")
    return 0


def generate(ticket_id: str, max_iterations: int | None) -> int:
    status = response_runner.generate_responses(runner.intake_engine(), ticket_id, max_iterations)
    print(f"ticket {ticket_id}: {status}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    smoke_parser = commands.add_parser("smoke", help="Ejecuta el grafo sobre un PDF sin tocar la base de datos.")
    smoke_parser.add_argument("pdf", type=Path)
    reprocess_parser = commands.add_parser("reprocess", help="Reprocesa un ticket existente.")
    reprocess_parser.add_argument("ticket_id")
    reprocess_parser.add_argument("--force", action="store_true", help="Reabre un ticket ya cerrado.")
    generate_parser = commands.add_parser("generate", help="Genera y evalúa las secciones de un ticket (Parte 2).")
    generate_parser.add_argument("ticket_id")
    generate_parser.add_argument("--max-iterations", type=int, default=None, help="Límite del ciclo por sección.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    if args.command == "smoke":
        if not args.pdf.is_file():
            parser.error(f"No existe el PDF {args.pdf}.")
        return smoke(args.pdf)
    if args.command == "generate":
        return generate(args.ticket_id, args.max_iterations)
    return reprocess(args.ticket_id, args.force)


if __name__ == "__main__":
    raise SystemExit(main())
