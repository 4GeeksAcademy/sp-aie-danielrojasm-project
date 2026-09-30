"""Eventos de inventario: identificadores de negocio, umbral mínimo y rechazos.

Traduce el modelo del inventario al vocabulario del plan de telemetría
(sección 2): `warehouse` (`los_angeles`/`zaragoza`), `country`, `client_id`
(slug de `SKU.client_name`), `product_id` (código SKU) y `product_category`.
Todos los eventos de inventario los construye este módulo para que las
propiedades se calculen de una sola forma.
"""

import json
import logging
import os
import re
import unicodedata
from typing import Any, Literal

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from sqlmodel import Session, select

from services.api import telemetry
from services.api.auth_models import User
from services.api.database import get_engine
from services.api.models import SKU, SKUCategory, Warehouse
from services.api.security import user_from_token


logger = logging.getLogger("trackflow.telemetry")

TELEMETRY_WAREHOUSES: dict[Warehouse, str] = {Warehouse.LA: "los_angeles", Warehouse.ZGZ: "zaragoza"}
WAREHOUSE_COUNTRIES: dict[Warehouse, str] = {Warehouse.LA: "US", Warehouse.ZGZ: "ES"}

StockLevel = Literal["low", "out"]
ThresholdSource = Literal["client_config", "default"]

# Mismo valor que `LOW_STOCK_THRESHOLD` del backoffice (riesgo R2 del plan).
DEFAULT_STOCK_MIN_THRESHOLD = 50

DIRECT_EDIT_DETAIL = "El stock solo cambia con órdenes de entrada o salida."
STOCK_FIELDS = ("current_stock", "stock", "stock_by_warehouse")
USER_FIELD = "user_uuid"

# Rutas POST cuyos 422 son `inventory_validation_failed` (operación del plan).
VALIDATED_OPERATIONS = {
    "/inventory/products": "product_create",
    "/inventory/orders/inbound": "inbound_order",
    "/inventory/orders/outbound": "outbound_order",
}


# ---------------------------------------------------------------------------
# Identificadores de negocio
# ---------------------------------------------------------------------------

def client_id(client_name: str) -> str:
    """Slug determinista de la marca: `PureStep Footwear` → `purestep-footwear` (riesgo R1)."""
    ascii_name = unicodedata.normalize("NFKD", client_name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
    return slug or "unknown"


def location(warehouse: Warehouse | str) -> dict[str, str]:
    code = Warehouse(warehouse)
    return {"warehouse": TELEMETRY_WAREHOUSES[code], "country": WAREHOUSE_COUNTRIES[code]}


def product(sku: SKU) -> dict[str, str]:
    return {
        "client_id": client_id(sku.client_name),
        "product_id": sku.sku,
        "product_category": sku.category,
    }


def movement(sku: SKU, warehouse: Warehouse | str) -> dict[str, str]:
    """Los cinco campos mínimos de todo evento de inventario, salvo `quantity`."""
    return {**location(warehouse), **product(sku)}


# ---------------------------------------------------------------------------
# Umbral mínimo por cliente
# ---------------------------------------------------------------------------

def min_stock_threshold(client: str) -> tuple[int, ThresholdSource]:
    """Mínimo del cliente desde `STOCK_MIN_THRESHOLDS` (JSON `{"client_id": unidades}`)."""
    raw = os.getenv("STOCK_MIN_THRESHOLDS", "").strip()
    if raw:
        try:
            configured = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("STOCK_MIN_THRESHOLDS no es un JSON válido; se usa el mínimo por defecto.")
            configured = {}
        value = configured.get(client) if isinstance(configured, dict) else None
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value, "client_config"
    return DEFAULT_STOCK_MIN_THRESHOLD, "default"


def threshold_crossings(previous: int, current: int, threshold: int) -> list[StockLevel]:
    """Niveles que una salida cruza hacia abajo (disparo por flanco).

    Solo cruza quien estaba por encima: con el SKU ya bajo mínimo, las salidas
    siguientes no repiten la alerta. Pasar de ≥ mínimo a 0 cruza los dos.
    """
    levels: list[StockLevel] = []
    if previous >= threshold > current:
        levels.append("low")
    if previous > 0 and current == 0:
        levels.append("out")
    return levels


# ---------------------------------------------------------------------------
# Rechazos: edición directa del stock y validación del servidor
# ---------------------------------------------------------------------------

def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _resolve_sku(session: Session, body: dict[str, Any]) -> SKU | None:
    sku_id = _int_or_none(body.get("sku_id"))
    if sku_id is not None:
        return session.get(SKU, sku_id)
    code = body.get("sku")
    if isinstance(code, str) and code.strip():
        return session.exec(select(SKU).where(SKU.sku == code.strip())).first()
    return None


def _sku_from_new_product(body: dict[str, Any]) -> SKU | None:
    """Un alta rechazada identifica su SKU por el cuerpo si este es coherente."""
    code = body.get("sku")
    if not isinstance(code, str) or not code.strip():
        return None
    try:
        return SKU(
            sku=code.strip()[:64],
            name="",
            client_name=str(body["client_name"]),
            category=SKUCategory(body["category"]).value,
            warehouse=Warehouse(body["warehouse"]).value,
        )
    except (KeyError, ValueError):
        return None


def _body_warehouse(body: dict[str, Any]) -> Warehouse | None:
    try:
        return Warehouse(body.get("warehouse"))
    except ValueError:
        return None


def direct_edit_properties(
    sku: SKU | None,
    warehouse: Warehouse | None,
    *,
    attempt_type: str,
    http_method: str,
    route: str,
    http_status: int,
    rejected_field: str | None,
    quantity: int | None,
    user: User,
) -> dict[str, Any]:
    target = warehouse or (Warehouse(sku.warehouse) if sku is not None else None)
    return {
        **(location(target) if target is not None else {"warehouse": None, "country": None}),
        **(product(sku) if sku is not None else dict.fromkeys(("client_id", "product_id", "product_category"))),
        "quantity": quantity,
        "attempt_type": attempt_type,
        "http_method": http_method,
        "route": route,
        "http_status": http_status,
        "rejected_field": rejected_field,
        "target_resolved": sku is not None,
        "user_role": user.role,
    }


def emit_method_not_allowed(
    request: Request, route: str, sku: SKU | None, body: Any, user: User
) -> None:
    """Vector 1: `PUT`/`PATCH`/`DELETE` sobre un recurso de stock → 405."""
    payload = body if isinstance(body, dict) else {}
    stock_value = next((payload[field] for field in STOCK_FIELDS if field in payload), None)
    telemetry.emit(
        "direct_stock_edit_rejected",
        direct_edit_properties(
            sku,
            _body_warehouse(payload),
            attempt_type="method_not_allowed",
            http_method=request.method,
            route=route,
            http_status=405,
            rejected_field=None,
            quantity=_int_or_none(stock_value),
            user=user,
        ),
        user_id=user.id,
    )


def report_validation_error(request: Request, error: RequestValidationError) -> None:
    """Vectores 2 y 3 (`direct_stock_edit_rejected`) o `inventory_validation_failed`.

    Solo mira los `POST /inventory/*`. Nunca copia el cuerpo: usa los nombres
    de campo y, del campo de stock prohibido, su valor si es un entero.
    """
    path = request.url.path
    if request.method != "POST" or not path.startswith("/inventory/"):
        return
    errors = error.errors()
    body = error.body if isinstance(error.body, dict) else {}
    forbidden = [
        str(item["loc"][-1])
        for item in errors
        if item.get("type") == "extra_forbidden" and item["loc"][-1] in (*STOCK_FIELDS, USER_FIELD)
    ]
    operation = VALIDATED_OPERATIONS.get(path)
    if not forbidden and operation is None:
        return

    try:
        with Session(get_engine()) as session:
            sku = _resolve_sku(session, body)
    except Exception:  # noqa: BLE001 - sin base de datos el evento sale sin producto
        sku = None
    if sku is None and operation == "product_create":
        sku = _sku_from_new_product(body)
    warehouse = _body_warehouse(body)

    if forbidden:
        user = _request_user(request)
        if user is None:
            return
        field = next((name for name in forbidden if name in STOCK_FIELDS), forbidden[0])
        telemetry.emit(
            "direct_stock_edit_rejected",
            direct_edit_properties(
                sku,
                warehouse,
                attempt_type="user_field_in_payload" if field == USER_FIELD else "stock_field_in_payload",
                http_method="POST",
                route=path,
                http_status=422,
                rejected_field=field,
                quantity=_int_or_none(body.get(field)) if field != USER_FIELD else None,
                user=user,
            ),
            user_id=user.id,
        )
        return

    fields = [
        ".".join(str(part) for part in item["loc"] if part != "body") or "body" for item in errors
    ]
    user = _request_user(request)
    telemetry.emit(
        "inventory_validation_failed",
        {
            "layer": "server",
            "operation": operation,
            "product_id": sku.sku if sku is not None else None,
            "warehouse": location(warehouse)["warehouse"] if warehouse is not None else None,
            "client_id": client_id(sku.client_name) if sku is not None else None,
            "error_fields": [field[:60] for field in fields][:10],
            "error_types": [str(item.get("type", "value_error"))[:40] for item in errors][:10],
            "error_count": len(errors),
        },
        user_id=user.id if user is not None else None,
    )


def _request_user(request: Request) -> User | None:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    return user_from_token(token) if scheme.lower() == "bearer" and token else None
