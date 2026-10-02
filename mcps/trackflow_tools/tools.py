"""Tools del servidor y el scope OAuth que exige cada una (mínimo privilegio).

| Tool | Scope | Llamada a la API |
| --- | --- | --- |
| `create_ticket` | `incidents:write` | `POST /api/incidents` |
| `update_ticket_status` | `incidents:write` | `PATCH /api/incidents/{id}/status` (ciclo de vida) |
| `get_ticket_status` | `incidents:read` | `GET /api/incidents/{id}` |
| `query_inventory` | `inventory:read` | solo `GET /inventory/*` |

No existe ningún scope de escritura de inventario. `query_inventory` reconoce las operaciones de escritura de la API
de inventario solo para rechazarlas con `INVENTORY_READ_ONLY`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field, PositiveInt

from mcps.trackflow_tools import backend
from mcps.trackflow_tools.errors import ErrorCode, ToolFailure
from packages.shared.incidents.domain import TITLE_MAX_LENGTH, Branch, IncidentCategory, IncidentOrigin, IncidentStatus
from services.api.models import Warehouse
from services.api.schemas import InventoryOrderRead, SKUListItem, SKURead


SCOPE_INCIDENTS_READ = "incidents:read"
SCOPE_INCIDENTS_WRITE = "incidents:write"
SCOPE_INVENTORY_READ = "inventory:read"
SCOPES_SUPPORTED = [SCOPE_INCIDENTS_READ, SCOPE_INCIDENTS_WRITE, SCOPE_INVENTORY_READ]

TOOL_SCOPES = {
    "create_ticket": SCOPE_INCIDENTS_WRITE,
    "update_ticket_status": SCOPE_INCIDENTS_WRITE,
    "get_ticket_status": SCOPE_INCIDENTS_READ,
    "query_inventory": SCOPE_INVENTORY_READ,
}

READ_OPERATIONS = ("list_products", "get_product", "list_movements")
# Escrituras que expone la API de inventario: se nombran para rechazarlas de forma explícita, nunca se ejecutan.
WRITE_OPERATIONS = (
    "create_product",
    "update_product",
    "delete_product",
    "update_stock",
    "create_inbound_order",
    "create_outbound_order",
    "create_inventory_count",
)


class Ticket(BaseModel):
    """Ticket del gestor de incidencias (`GET /api/incidents/{id}` sin `reported_by`, que es un email interno)."""

    id: int = Field(description="Id del ticket en el gestor de incidencias.")
    title: str
    description: str
    status: IncidentStatus = Field(
        description="Estado del ciclo de vida: open → in_progress | discarded; in_progress → resolved | discarded. "
        "resolved y discarded son finales."
    )
    category: IncidentCategory
    origin: IncidentOrigin
    branch: Branch
    created_at: datetime
    updated_at: datetime


class InventoryQueryResult(BaseModel):
    """Resultado de `query_inventory`: solo se rellena el campo de la operación pedida."""

    operation: Literal["list_products", "get_product", "list_movements"]
    products: list[SKUListItem] | None = Field(default=None, description="Para list_products.")
    product: SKURead | None = Field(default=None, description="Para get_product.")
    movements: list[InventoryOrderRead] | None = Field(default=None, description="Para list_movements.")


TicketId = Annotated[PositiveInt, Field(description="Id del ticket en el gestor de incidencias.")]


def _ticket(payload: dict[str, Any]) -> Ticket:
    return Ticket.model_validate({key: payload[key] for key in Ticket.model_fields})


def register_tools(mcp: FastMCP) -> None:
    @mcp.tool(
        title="Crear ticket",
        description=(
            "Crea un ticket en el gestor de incidencias de TrackFlow. Nace siempre en estado 'open'. "
            f"Requiere el scope OAuth '{SCOPE_INCIDENTS_WRITE}'."
        ),
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
    )
    async def create_ticket(
        title: Annotated[str, Field(min_length=1, max_length=TITLE_MAX_LENGTH, description="Resumen breve del problema.")],
        description: Annotated[str, Field(min_length=1, max_length=5000, description="Qué ocurrió y a quién afecta.")],
        category: Annotated[IncidentCategory, Field(description="Tipo de incidencia.")],
        origin: Annotated[IncidentOrigin, Field(description="Quién la detectó: customer, branch o internal.")],
        branch: Annotated[Branch, Field(description="Sede afectada.")],
    ) -> Ticket:
        payload = {
            "title": title,
            "description": description,
            "category": category.value,
            "origin": origin.value,
            "branch": branch.value,
        }
        return _ticket(await backend.request("POST", backend.INCIDENTS_PATH, json=payload))

    @mcp.tool(
        title="Cambiar estado de un ticket",
        description=(
            "Cambia el estado de un ticket por el endpoint de ciclo de vida del gestor "
            "(PATCH /api/incidents/{id}/status). Transiciones permitidas: open → in_progress | discarded; "
            "in_progress → resolved | discarded; resolved y discarded son finales. Una transición no permitida "
            f"devuelve VALIDATION_ERROR. Requiere el scope OAuth '{SCOPE_INCIDENTS_WRITE}'."
        ),
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    )
    async def update_ticket_status(
        ticket_id: TicketId,
        status: Annotated[IncidentStatus, Field(description="Estado de destino.")],
    ) -> Ticket:
        path = f"{backend.INCIDENTS_PATH}/{ticket_id}/status"
        return _ticket(await backend.request("PATCH", path, json={"status": status.value}))

    @mcp.tool(
        title="Consultar estado de un ticket",
        description=(
            "Devuelve un ticket del gestor de incidencias en tiempo real: estado, categoría, origen, sede y fechas. "
            f"Solo lectura. Requiere el scope OAuth '{SCOPE_INCIDENTS_READ}'."
        ),
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    )
    async def get_ticket_status(ticket_id: TicketId) -> Ticket:
        return _ticket(await backend.request("GET", f"{backend.INCIDENTS_PATH}/{ticket_id}"))

    inventory = backend.InventoryReader()

    @mcp.tool(
        title="Consultar inventario (solo lectura)",
        description=(
            "Consulta el inventario de TrackFlow (almacenes LA y ZGZ). SOLO LECTURA: el stock se calcula a partir de "
            "entradas y salidas y este servidor nunca lo modifica. Operaciones: "
            "'list_products' (SKUs con su stock actual; filtro opcional 'warehouse'), "
            "'get_product' (un SKU con el stock por almacén; requiere 'sku_id'), "
            "'list_movements' (entradas y salidas; filtro opcional 'warehouse'). "
            f"Cualquier operación de escritura ({', '.join(WRITE_OPERATIONS)}) se rechaza con INVENTORY_READ_ONLY. "
            f"Requiere el scope OAuth '{SCOPE_INVENTORY_READ}'."
        ),
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    )
    async def query_inventory(
        operation: Annotated[
            str,
            Field(description=f"Una de: {', '.join(READ_OPERATIONS)}. Las escrituras se rechazan."),
        ],
        sku_id: Annotated[PositiveInt | None, Field(description="Id del SKU (obligatorio en get_product).")] = None,
        warehouse: Annotated[Warehouse | None, Field(description="Filtro de almacén: LA o ZGZ.")] = None,
    ) -> InventoryQueryResult:
        if operation in WRITE_OPERATIONS:
            raise ToolFailure(
                ErrorCode.INVENTORY_READ_ONLY,
                f"El inventario es de solo lectura en este servidor: la operación '{operation}' no está permitida "
                "para ningún cliente. Las altas, entradas, salidas y conteos se registran en el backoffice.",
            )
        params = {"warehouse": warehouse.value} if warehouse else None
        if operation == "list_products":
            return InventoryQueryResult(operation=operation, products=await inventory.get("/products", params))
        if operation == "get_product":
            if sku_id is None:
                raise ToolFailure(
                    ErrorCode.VALIDATION_ERROR,
                    "get_product necesita 'sku_id'.",
                    [{"field": "sku_id", "message": "Obligatorio en get_product."}],
                )
            return InventoryQueryResult(operation=operation, product=await inventory.get(f"/products/{sku_id}"))
        if operation == "list_movements":
            return InventoryQueryResult(operation=operation, movements=await inventory.get("/orders", params))
        raise ToolFailure(
            ErrorCode.VALIDATION_ERROR,
            f"Operación desconocida '{operation}'. Operaciones disponibles: {', '.join(READ_OPERATIONS)}.",
            [{"field": "operation", "message": f"Debe ser una de: {', '.join(READ_OPERATIONS)}."}],
        )
