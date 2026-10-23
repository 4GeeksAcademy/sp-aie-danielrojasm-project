"""CLI del flujo de RFPs (no es un segundo API: la recepción normal es `POST /rfps` desde el backoffice).

    uv run --env-file .env python scripts/rfp_intake.py smoke <ruta.pdf>
        Ejecuta el grafo de la Parte 1 sobre un PDF local e imprime el resultado en JSON. No toca la base de datos.

    uv run --env-file .env python scripts/rfp_intake.py reprocess <ticket_id> [--force]
        Vuelve a ejecutar el análisis de un ticket en este proceso (p. ej. tras agotar los reintentos del worker).
        Solo procesa tickets en `analizando`; `--force` borra antes el resultado de un ticket ya cerrado (las tres
        partes, incluido el hilo de checkpoints de la aprobación).

    uv run --env-file .env python scripts/rfp_intake.py generate <ticket_id> [--max-iterations N]
        Ejecuta la Parte 2 (generación y evaluación por departamento) de un ticket en `analisis_completo`, o de uno
        que se quedó en `generando_borrador` / `en_evaluación` tras agotar los reintentos del worker.

    uv run --env-file .env python scripts/rfp_intake.py approval start <ticket_id> [--max-rounds N]
    uv run --env-file .env python scripts/rfp_intake.py approval status <ticket_id>
    uv run --env-file .env python scripts/rfp_intake.py approval decide <ticket_id> <department_id> \\
            approve|request_changes|reject [--comment TEXTO] [--capacity N]
        Parte 3: abre la aprobación (o la continúa tras un fallo), muestra las revisiones pendientes o registra la
        decisión de un responsable con el mismo `resume` que ejecuta el worker (`rfp_intake.resume_approval`).

    uv run --env-file .env python scripts/rfp_intake.py e2e <ruta.pdf> [--decisions <fixture.json>]
        Ruta E2E reproducible: recibe el PDF como lo haría `POST /rfps`, ejecuta las Partes 1 y 2, abre la Parte 3 y
        aplica las aprobaciones simuladas del fixture (por defecto `tests/fixtures/rfp/simulated_approvals.json`)
        hasta el documento final. Imprime cada transición de estado y guarda el documento en
        `data/raw/rfp_intake/<ticket_id>-final.md`.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data.pipelines.rfp_intake import approval_runner, graph, response_runner, runner  # noqa: E402

DEFAULT_DECISIONS = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "rfp" / "simulated_approvals.json"
CLI_USER = "scripts/rfp_intake.py"


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
        approval_runner.forget(engine, ticket_id)
        runner.reset_ticket(engine, ticket_id)
    status = runner.process_ticket(engine, ticket_id)
    print(f"ticket {ticket_id}: {status}")
    return 0


def generate(ticket_id: str, max_iterations: int | None) -> int:
    status = response_runner.generate_responses(runner.intake_engine(), ticket_id, max_iterations)
    print(f"ticket {ticket_id}: {status}")
    return 0


def approval_status(ticket_id: str) -> int:
    engine = runner.intake_engine()
    print(f"ticket {ticket_id}: {approval_runner.ticket_status(engine, ticket_id)}")
    for department_id, review in approval_runner.pending_reviews(engine, ticket_id).items():
        print(
            f"  {department_id}: espera a {review['approver']} · revisión {review['review_round']} · "
            f"decisiones {', '.join(review['allowed_decisions'])}"
        )
    return 0


def decide(ticket_id: str, department_id: str, decision: dict, decided_by: str = CLI_USER) -> str:
    engine = runner.intake_engine()
    review = approval_runner.pending_reviews(engine, ticket_id).get(department_id)
    if review is None:
        raise approval_runner.NoPendingReviewError(f"{department_id} no tiene ninguna revisión pendiente.")
    payload = {"review_round": review["review_round"], "decided_by": decided_by, **decision}
    return approval_runner.submit_decision(engine, ticket_id, department_id, payload)


def e2e(pdf_path: Path, decisions_path: Path) -> int:
    """Partes 1 → 3 en este proceso, con las aprobaciones del fixture."""
    fixture = json.loads(decisions_path.read_text(encoding="utf-8"))
    engine = runner.intake_engine()
    ticket = runner.receive_upload(
        engine, content=pdf_path.read_bytes(), filename=pdf_path.name, uploaded_by=fixture["decided_by"]
    )
    ticket_id = ticket.ticket_id
    print(f"[recepción] ticket {ticket_id}: {ticket.status}")
    status = runner.process_ticket(engine, ticket_id)
    print(f"[parte 1] {status}")
    if status != "analisis_completo":
        return 0
    print(f"[parte 2] {response_runner.generate_responses(engine, ticket_id)}")
    print(f"[parte 3] {approval_runner.start_approval(engine, ticket_id)}")
    for step in fixture["steps"]:
        department_id = step["department_id"]
        pending = approval_runner.pending_reviews(engine, ticket_id)
        if department_id not in pending:
            print(f"  · {department_id}: sin revisión pendiente en este ticket, se omite.")
            continue
        others = sorted(set(pending) - {department_id})
        decision = {key: value for key, value in step.items() if key != "department_id"}
        status = decide(ticket_id, department_id, decision, fixture["decided_by"])
        print(
            f"  · {department_id} revisión {pending[department_id]['review_round']}: {decision['decision']} → "
            f"ticket {status}; siguen esperando: {', '.join(others) or 'nadie'}"
        )
    detail = runner.get_ticket_detail(engine, ticket_id)
    print(f"[final] ticket {ticket_id}: {detail.ticket.status} · pasos en la traza: {len(detail.ticket.trace)}")
    for record in detail.ticket.arbitrations:
        print(f"  arbitraje ronda {record['round']}: {record['trigger_id']} ({record['arbiter']}) → {record['action']}")
    if detail.final_document is None:
        print("Sin documento final: alguna sección sigue pendiente o fue rechazada.")
        return 1
    target = runner.raw_dir() / f"{ticket_id}-final.md"
    target.write_text(detail.final_document.content, encoding="utf-8")
    print(f"Documento final: {target}")
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
    approval_parser = commands.add_parser("approval", help="Aprobación por departamento (Parte 3).")
    approval_commands = approval_parser.add_subparsers(dest="action", required=True)
    start_parser = approval_commands.add_parser("start", help="Abre o continúa la aprobación de un ticket.")
    start_parser.add_argument("ticket_id")
    start_parser.add_argument("--max-rounds", type=int, default=None, help="Revisiones por sección y de arbitraje.")
    status_parser = approval_commands.add_parser("status", help="Muestra las revisiones pendientes.")
    status_parser.add_argument("ticket_id")
    decide_parser = approval_commands.add_parser("decide", help="Registra la decisión de un responsable.")
    decide_parser.add_argument("ticket_id")
    decide_parser.add_argument("department_id", choices=["warehouse", "lastmile", "reverse"])
    decide_parser.add_argument("decision", choices=["approve", "request_changes", "reject"])
    decide_parser.add_argument("--comment", default="")
    decide_parser.add_argument("--capacity", type=int, default=None, help="Solo warehouse: pedidos/mes.")
    e2e_parser = commands.add_parser("e2e", help="Partes 1 → 3 con aprobaciones simuladas.")
    e2e_parser.add_argument("pdf", type=Path)
    e2e_parser.add_argument("--decisions", type=Path, default=DEFAULT_DECISIONS)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    if args.command in ("smoke", "e2e") and not args.pdf.is_file():
        parser.error(f"No existe el PDF {args.pdf}.")
    if args.command == "smoke":
        return smoke(args.pdf)
    if args.command == "e2e":
        return e2e(args.pdf, args.decisions)
    if args.command == "generate":
        return generate(args.ticket_id, args.max_iterations)
    if args.command == "approval":
        if args.action == "start":
            status = approval_runner.start_approval(runner.intake_engine(), args.ticket_id, args.max_rounds)
            print(f"ticket {args.ticket_id}: {status}")
            return 0
        if args.action == "status":
            return approval_status(args.ticket_id)
        decision = {"decision": args.decision, "comment": args.comment}
        if args.capacity is not None:
            decision["committed_monthly_capacity"] = args.capacity
        print(f"ticket {args.ticket_id}: {decide(args.ticket_id, args.department_id, decision)}")
        return 0
    return reprocess(args.ticket_id, args.force)


if __name__ == "__main__":
    raise SystemExit(main())
