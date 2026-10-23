"""Grafo `rfp_intake` de punta a punta y ciclo de vida del ticket en una base SQLite temporal.

El PDF es real (se convierte con MarkItDown); los agentes devuelven salidas fijas según su nombre, así que no hace
falta el gateway LLM.
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlmodel import SQLModel

from data.pipelines.rfp_intake import document, graph, llm, runner


def minimal_pdf(lines: list[str]) -> bytes:
    """PDF de una página con texto Helvetica, sin dependencias para generarlo."""
    text = " ".join(f"({line}) Tj T*" for line in lines)
    stream = f"BT /F1 12 Tf 14 TL 72 720 Td {text} ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    body = b"%PDF-1.4\n"
    offsets = []
    for number, content in enumerate(objects, start=1):
        offsets.append(len(body))
        body += b"%d 0 obj\n" % number + content + b"\nendobj\n"
    xref = len(body)
    body += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    body += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    body += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return body


RFP_LINES = [
    "Luna Cosmetics - Los Angeles, CA, USA",
    "We just crossed 5,000 orders a month.",
    "We need warehousing and shipping across the US. Could you send over a proposal?",
]
PITCH_LINES = ["This is Jake from RapidShip Carriers.", "We offer aggressive rates to TrackFlow."]

AGENT_OUTPUTS = {
    "metadata_extractor": {
        "client_name": "Luna Cosmetics",
        "client_country": "US",
        "services_requested": ["warehousing", "last_mile"],
        "monthly_volume": 5000,
    },
    "orchestrator": {
        "departments": [
            {"department_id": "lastmile", "focus": "Envíos en EE. UU.", "paragraph_ids": [1]},
            {"department_id": "warehouse", "focus": "Almacenaje.", "paragraph_ids": [1]},
        ],
        "out_of_scope": [],
    },
    "warehouse_worker": {
        "key_aspects": ["5,000 pedidos al mes"],
        "requested_inputs": ["Capacidad en Los Angeles"],
        "open_questions": [],
    },
    "lastmile_worker": {
        "key_aspects": ["Envíos en todo EE. UU."],
        "requested_inputs": ["Costo por envío"],
        "open_questions": ["¿Peso medio?"],
    },
    "synthesizer": {
        "summary": "Luna Cosmetics (EE. UU., USD) pide almacenamiento y última milla para 5,000 pedidos al mes.",
        "next_steps": ["Pedir a Ana Whitfield la capacidad.", "Pedir a Carlos Vega el costo por envío."],
        "conflicts": [],
    },
}


@pytest.fixture
def fake_agents(monkeypatch):
    calls: list[str] = []
    classification = {"is_rfp": True, "document_type": "rfp_informal", "confidence": 0.93, "reason": "Pide una propuesta."}

    def ask_json(agent, system_prompt, user_prompt, schema):
        calls.append(agent)
        if agent == "classifier":
            is_pitch = "RapidShip" in user_prompt
            response = (
                {"is_rfp": False, "document_type": "vendor_pitch", "confidence": 0.97, "reason": "Pitch de un transportista."}
                if is_pitch
                else classification
            )
            return schema.model_validate(response)
        return schema.model_validate(AGENT_OUTPUTS[agent])

    monkeypatch.setattr(llm, "ask_json", ask_json)
    return calls


@pytest.fixture
def engine(tmp_path, monkeypatch) -> Iterator[Engine]:
    monkeypatch.setenv("RFP_RAW_DIR", str(tmp_path / "raw"))
    engine = create_engine(f"sqlite:///{(tmp_path / 'rfps.db').as_posix()}")
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


def test_pdf_is_converted_to_markdown_before_any_agent(tmp_path):
    pdf = tmp_path / "rfp.pdf"
    pdf.write_bytes(minimal_pdf(RFP_LINES))

    markdown = document.pdf_to_markdown(pdf)

    assert "Luna Cosmetics" in markdown and "5,000 orders a month" in markdown


def test_unreadable_pdf_raises_a_conversion_error(tmp_path):
    pdf = tmp_path / "broken.pdf"
    pdf.write_bytes(b"%PDF-1.4 esto no es un PDF")

    with pytest.raises(document.DocumentConversionError):
        document.pdf_to_markdown(pdf)


def test_readability_reports_cost_even_for_short_documents():
    metrics = document.readability_metrics("Hola, necesitamos una propuesta de almacenamiento.")

    assert metrics.word_count == 6
    assert metrics.estimated_tokens > 0
    assert metrics.flesch_kincaid_grade is None


def test_graph_runs_workers_in_parallel_and_synthesizes_in_briefing_order(tmp_path, fake_agents):
    pdf = tmp_path / "rfp.pdf"
    pdf.write_bytes(minimal_pdf(RFP_LINES))

    state = graph.run_graph("ticket-1", str(pdf))

    assert fake_agents[:3] == ["classifier", "metadata_extractor", "orchestrator"]
    assert sorted(fake_agents[3:5]) == ["lastmile_worker", "warehouse_worker"]
    assert fake_agents[5:] == ["synthesizer"]
    assert state["metadata"]["currency"] == "USD"
    workstreams = state["synthesis"]["workstreams"]
    assert [w["department_id"] for w in workstreams] == ["warehouse", "lastmile"]
    assert [w["responsible"] for w in workstreams] == ["Ana Whitfield", "Carlos Vega"]


def test_graph_stops_after_the_classifier_for_a_non_rfp(tmp_path, fake_agents):
    pdf = tmp_path / "pitch.pdf"
    pdf.write_bytes(minimal_pdf(PITCH_LINES))

    state = graph.run_graph("ticket-2", str(pdf))

    assert fake_agents == ["classifier"]
    assert state["classification"]["is_rfp"] is False
    assert "synthesis" not in state


def test_rfp_ticket_ends_in_analisis_completo_with_handoff(engine, fake_agents):
    ticket = runner.receive_upload(engine, content=minimal_pdf(RFP_LINES), filename="luna.pdf", uploaded_by="user-1")
    assert ticket.status == "analizando"
    assert runner.resolve_pdf_path(ticket.raw_pdf_path).read_bytes().startswith(b"%PDF-")

    assert runner.process_ticket(engine, ticket.ticket_id) == "analisis_completo"

    detail = runner.get_ticket_detail(engine, ticket.ticket_id)
    assert detail.ticket.attempts == 1 and detail.ticket.last_error is None
    assert detail.metadata.client_country == "US" and detail.metadata.currency == "USD"
    assert detail.metadata.monthly_volume == 5000
    assert detail.metadata.departments_needed == ["warehouse", "lastmile"]
    assert "Luna Cosmetics" in detail.metadata.document_markdown
    assert {s.department_id: s.key_aspects for s in detail.sections} == {
        "warehouse": ["5,000 pedidos al mes"],
        "lastmile": ["Envíos en todo EE. UU."],
    }
    handoff = detail.ticket.handoff
    assert handoff["version"] == "rfp_intake.handoff.v1"
    assert handoff["ticket_id"] == ticket.ticket_id and handoff["rfp_id"] == detail.metadata.rfp_id
    assert handoff["next_stage"] == "generando_borrador"
    assert [w["department_id"] for w in handoff["workstreams"]] == ["warehouse", "lastmile"]


def test_non_rfp_ticket_is_discarded_with_its_reason(engine, fake_agents):
    ticket = runner.receive_upload(engine, content=minimal_pdf(PITCH_LINES), filename="pitch.pdf", uploaded_by="user-1")

    assert runner.process_ticket(engine, ticket.ticket_id) == "descartado"

    detail = runner.get_ticket_detail(engine, ticket.ticket_id)
    assert detail.ticket.is_rfp is False
    assert detail.ticket.classification_reason == "Pitch de un transportista."
    assert detail.metadata is None and detail.sections == []
    assert detail.ticket.handoff is None


def test_a_failure_keeps_the_ticket_analizando_with_the_error_and_without_partial_results(engine, monkeypatch, fake_agents):
    ticket = runner.receive_upload(engine, content=minimal_pdf(RFP_LINES), filename="luna.pdf", uploaded_by="user-1")

    def gateway_down(*args, **kwargs):
        raise llm.RfpAgentError("El agente synthesizer no pudo llamar al modelo (APIConnectionError).")

    monkeypatch.setattr(graph.synthesizer, "synthesize", gateway_down)

    with pytest.raises(llm.RfpAgentError):
        runner.process_ticket(engine, ticket.ticket_id)

    detail = runner.get_ticket_detail(engine, ticket.ticket_id)
    assert detail.ticket.status == "analizando"
    assert detail.ticket.attempts == 1
    assert detail.ticket.last_error == "RfpAgentError: El agente synthesizer no pudo llamar al modelo (APIConnectionError)."
    assert detail.metadata is None and detail.sections == []


def test_a_closed_ticket_is_not_processed_twice(engine, fake_agents):
    ticket = runner.receive_upload(engine, content=minimal_pdf(PITCH_LINES), filename="pitch.pdf", uploaded_by="user-1")
    runner.process_ticket(engine, ticket.ticket_id)
    fake_agents.clear()

    assert runner.process_ticket(engine, ticket.ticket_id) == "descartado"
    assert fake_agents == []


def test_reset_reopens_a_ticket_for_manual_reprocessing(engine, fake_agents):
    ticket = runner.receive_upload(engine, content=minimal_pdf(RFP_LINES), filename="luna.pdf", uploaded_by="user-1")
    runner.process_ticket(engine, ticket.ticket_id)

    runner.reset_ticket(engine, ticket.ticket_id)

    detail = runner.get_ticket_detail(engine, ticket.ticket_id)
    assert detail.ticket.status == "analizando" and detail.ticket.handoff is None
    assert detail.metadata is None and detail.sections == []
    assert runner.process_ticket(engine, ticket.ticket_id) == "analisis_completo"


def test_cancel_upload_removes_the_ticket_and_the_pdf(engine):
    ticket = runner.receive_upload(engine, content=minimal_pdf(RFP_LINES), filename="luna.pdf", uploaded_by="user-1")
    pdf_path = runner.resolve_pdf_path(ticket.raw_pdf_path)

    runner.cancel_upload(engine, ticket.ticket_id)

    assert not pdf_path.exists()
    with pytest.raises(runner.TicketNotFoundError):
        runner.get_ticket_detail(engine, ticket.ticket_id)
