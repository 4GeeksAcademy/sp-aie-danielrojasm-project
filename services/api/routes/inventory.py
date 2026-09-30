"""Inventario unificado de SKUs en los almacenes de Los Ángeles y Zaragoza.

El stock nunca se escribe: se calcula por SKU y almacén como
SUMA(StockEntry.quantity) − SUMA(StockExit.quantity). La única forma de
cambiarlo es registrar una recepción o una salida, y cada una guarda el
`user_uuid` (TinyDB) de quien la registró.
"""

import logging
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from services.api import inventory_telemetry, telemetry
from services.api.auth_models import User
from services.api.cache import TTLCache
from services.api.database import get_db
from services.api.models import SKU, InventoryCount, StockEntry, StockExit, Warehouse
from services.api.schemas import (
    DirectStockEditRejected,
    InventoryCountCreate,
    InventoryCountRead,
    InventoryOrderRead,
    SKUCreate,
    SKUListItem,
    SKURead,
    StockEntryCreate,
    StockEntryRead,
    StockExitCreate,
    StockExitRead,
)
from services.api.security import get_current_user


logger = logging.getLogger("trackflow.inventory")

INVENTORY_PREFIX = "/inventory"

# Todas las rutas exigen sesión: el inventario es información contractual de
# las marcas cliente, no un dato público.
router = APIRouter(
    prefix=INVENTORY_PREFIX,
    tags=["inventory"],
    dependencies=[Depends(get_current_user)],
)

StockTable = dict[int, dict[Warehouse, int]]

# Listado de stock: lo piden la tabla de stock y los selectores de SKU de los dos
# formularios de movimientos, y en Supabase cuesta tres idas y vueltas (~375 ms).
# Las escrituras de esta API lo invalidan al momento; el TTL solo acota lo que
# tarda en verse un cambio hecho fuera de este proceso (seed, SQL directo u
# otra réplica). El stock que decide una salida nunca sale de aquí: se vuelve a
# calcular con la fila bloqueada en `create_outbound_order`.
PRODUCTS_CACHE_TTL_SECONDS = 30
products_cache: TTLCache[list[SKUListItem]] = TTLCache(
    "inventory.products", PRODUCTS_CACHE_TTL_SECONDS
)


# ---------------------------------------------------------------------------
# Cálculo de stock
# ---------------------------------------------------------------------------

def _sum_by_sku_and_warehouse(
    session: Session, model: type[StockEntry] | type[StockExit], sku_ids: list[int] | None
) -> Iterable[tuple[int, str, int]]:
    query = select(model.sku_id, model.warehouse, func.sum(model.quantity)).group_by(
        model.sku_id, model.warehouse
    )
    if sku_ids is not None:
        query = query.where(model.sku_id.in_(sku_ids))
    return session.exec(query).all()


def stock_by_warehouse(session: Session, sku_ids: list[int] | None = None) -> StockTable:
    """Stock de cada SKU en cada almacén con dos consultas agregadas (sin N+1)."""
    stock: StockTable = defaultdict(lambda: {warehouse: 0 for warehouse in Warehouse})
    for sku_id, warehouse, total in _sum_by_sku_and_warehouse(session, StockEntry, sku_ids):
        stock[sku_id][Warehouse(warehouse)] += int(total)
    for sku_id, warehouse, total in _sum_by_sku_and_warehouse(session, StockExit, sku_ids):
        stock[sku_id][Warehouse(warehouse)] -= int(total)
    return stock


def _sku_list_item(sku: SKU, stock: StockTable) -> SKUListItem:
    return SKUListItem(
        id=sku.id,
        name=sku.name,
        sku=sku.sku,
        client_name=sku.client_name,
        category=sku.category,
        warehouse=sku.warehouse,
        # Un SKU se da de alta en un almacén; su stock "actual" es el de ese almacén.
        current_stock=stock[sku.id][Warehouse(sku.warehouse)],
    )


def _sku_read(sku: SKU, stock: StockTable) -> SKURead:
    return SKURead(
        **_sku_list_item(sku, stock).model_dump(), stock_by_warehouse=stock[sku.id]
    )


def _get_sku(session: Session, sku_id: int, *, lock: bool = False) -> SKU:
    query = select(SKU).where(SKU.id == sku_id)
    if lock:
        # Serializa las salidas del mismo SKU: dos despachos simultáneos no
        # pueden leer el mismo stock disponible y dejarlo en negativo.
        query = query.with_for_update()
    sku = session.exec(query).first()
    if sku is None:
        raise HTTPException(status_code=404, detail=f"No existe ningún SKU con id {sku_id}.")
    return sku


# ---------------------------------------------------------------------------
# SKUs
# ---------------------------------------------------------------------------

@router.get("/products", response_model=list[SKUListItem])
def list_products(
    warehouse: Warehouse | None = Query(
        default=None, description="Solo los SKUs dados de alta en este almacén."
    ),
    session: Session = Depends(get_db),
) -> list[SKUListItem]:
    # Mismo resultado para cualquier usuario autenticado: la clave es solo el filtro.
    key = warehouse.value if warehouse is not None else "all"
    return list(products_cache.get_or_compute(key, lambda: _load_products(session, warehouse)))


def _load_products(session: Session, warehouse: Warehouse | None) -> list[SKUListItem]:
    query = select(SKU).order_by(SKU.id)
    if warehouse is not None:
        query = query.where(SKU.warehouse == warehouse.value)
    skus = session.exec(query).all()
    stock = stock_by_warehouse(session, [sku.id for sku in skus])
    return [_sku_list_item(sku, stock) for sku in skus]


@router.post("/products", response_model=SKURead, status_code=status.HTTP_201_CREATED)
def create_product(
    payload: SKUCreate,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SKURead:
    existing = session.exec(select(SKU).where(SKU.sku == payload.sku)).first()
    if existing is not None:
        _emit_creation_rejected(payload, existing, current_user)
        raise HTTPException(status_code=409, detail=f"El SKU '{payload.sku}' ya está registrado.")
    sku = SKU(**payload.model_dump(mode="json"))
    session.add(sku)
    try:
        session.commit()
    except IntegrityError as error:
        # Otra petición registró el mismo código entre la comprobación y el commit.
        session.rollback()
        existing = session.exec(select(SKU).where(SKU.sku == payload.sku)).first()
        if existing is not None:
            _emit_creation_rejected(payload, existing, current_user)
        raise HTTPException(
            status_code=409, detail=f"El SKU '{payload.sku}' ya está registrado."
        ) from error
    products_cache.invalidate("alta de SKU")
    session.refresh(sku)
    logger.info(
        "SKU %s (%s) registrado en %s por %s", sku.id, sku.sku, sku.warehouse, current_user.id
    )
    telemetry.emit(
        "product_created", inventory_telemetry.movement(sku, sku.warehouse), user_id=current_user.id
    )
    # Un SKU nuevo empieza sin stock: solo una recepción puede añadirlo.
    return _sku_read(sku, stock_by_warehouse(session, [sku.id]))


def _emit_creation_rejected(payload: SKUCreate, existing: SKU, user: User) -> None:
    telemetry.emit(
        "product_creation_rejected",
        {
            "warehouse": inventory_telemetry.location(payload.warehouse)["warehouse"],
            "client_id": inventory_telemetry.client_id(payload.client_name),
            "product_id": payload.sku,
            "product_category": payload.category.value,
            "existing_warehouse": inventory_telemetry.location(existing.warehouse)["warehouse"],
        },
        user_id=user.id,
    )


@router.get("/products/{sku_id}", response_model=SKURead)
def get_product(sku_id: int, session: Session = Depends(get_db)) -> SKURead:
    sku = _get_sku(session, sku_id)
    return _sku_read(sku, stock_by_warehouse(session, [sku.id]))


# ---------------------------------------------------------------------------
# Movimientos
# ---------------------------------------------------------------------------

@router.post(
    "/orders/inbound", response_model=StockEntryRead, status_code=status.HTTP_201_CREATED
)
def create_inbound_order(
    payload: StockEntryCreate,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StockEntryRead:
    sku = _get_sku(session, payload.sku_id)
    # Antes del commit: después, leer el SKU costaría otra consulta.
    identity = inventory_telemetry.movement(sku, payload.warehouse)
    entry = StockEntry(**payload.model_dump(mode="json"), user_uuid=current_user.id)
    session.add(entry)
    session.commit()
    products_cache.invalidate("recepción")
    session.refresh(entry)
    logger.info(
        "Recepción %s: +%s de %s en %s (ref. %s) por %s",
        entry.id,
        entry.quantity,
        sku.sku,
        entry.warehouse,
        entry.reference,
        current_user.id,
    )
    # Solo tras un commit confirmado: si falla, no hay evento.
    telemetry.emit(
        "inbound_order_created",
        {
            "order_id": entry.id,
            **identity,
            "quantity": entry.quantity,
            "user_role": current_user.role,
        },
        user_id=current_user.id,
    )
    return StockEntryRead.model_validate(entry, from_attributes=True)


@router.post(
    "/orders/outbound", response_model=StockExitRead, status_code=status.HTTP_201_CREATED
)
def create_outbound_order(
    payload: StockExitCreate,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StockExitRead:
    sku = _get_sku(session, payload.sku_id, lock=True)
    # El stock se comprueba en el almacén de la salida, nunca sumando almacenes.
    available = stock_by_warehouse(session, [sku.id])[sku.id][payload.warehouse]
    identity = inventory_telemetry.movement(sku, payload.warehouse)
    if payload.quantity > available:
        session.rollback()  # libera el bloqueo sin haber escrito nada
        telemetry.emit(
            "outbound_order_rejected",
            {
                **identity,
                "quantity": payload.quantity,
                "available_quantity": max(available, 0),
                "exit_type": payload.exit_type.value,
            },
            user_id=current_user.id,
        )
        logger.warning(
            "Salida rechazada por stock insuficiente: %s en %s (disponible %s, pedido %s) por %s",
            sku.sku,
            payload.warehouse.value,
            available,
            payload.quantity,
            current_user.id,
        )
        raise HTTPException(
            status_code=400,
            detail=(
                f"Insufficient stock for SKU '{sku.sku}'. "
                f"Available: {available}, requested: {payload.quantity}."
            ),
        )
    exit_record = StockExit(**payload.model_dump(mode="json"), user_uuid=current_user.id)
    session.add(exit_record)
    session.commit()
    products_cache.invalidate("salida")
    session.refresh(exit_record)
    logger.info(
        "Salida %s (%s): -%s de %s en %s por %s",
        exit_record.id,
        exit_record.exit_type,
        exit_record.quantity,
        sku.sku,
        exit_record.warehouse,
        current_user.id,
    )
    _emit_outbound_events(exit_record, identity, available, current_user)
    return StockExitRead.model_validate(exit_record, from_attributes=True)


def _emit_outbound_events(
    exit_record: StockExit, identity: dict[str, str], available: int, user: User
) -> None:
    """`outbound_order_created` y, si la salida cruza el mínimo del cliente,
    `stock_threshold_triggered`. El stock resultante sale del disponible ya
    calculado con la fila bloqueada: sin consultas extra."""
    stock_after = available - exit_record.quantity
    telemetry.emit(
        "outbound_order_created",
        {
            "order_id": exit_record.id,
            **identity,
            "quantity": exit_record.quantity,
            "exit_type": exit_record.exit_type,
            "stock_after": stock_after,
            "user_role": user.role,
        },
        user_id=user.id,
    )
    threshold, source = inventory_telemetry.min_stock_threshold(identity["client_id"])
    for level in inventory_telemetry.threshold_crossings(available, stock_after, threshold):
        logger.warning(
            "Umbral mínimo cruzado (%s): %s en %s queda en %s (mínimo %s)",
            level,
            identity["product_id"],
            exit_record.warehouse,
            stock_after,
            threshold,
        )
        telemetry.emit(
            "stock_threshold_triggered",
            {
                **identity,
                "quantity": stock_after,
                "threshold": threshold,
                "threshold_source": source,
                "stock_level": level,
                "previous_quantity": available,
                "triggering_order_id": exit_record.id,
            },
            user_id=user.id,
        )


@router.get("/orders", response_model=list[InventoryOrderRead])
def list_orders(
    warehouse: Warehouse | None = Query(default=None, description="Solo este almacén."),
    session: Session = Depends(get_db),
) -> list[InventoryOrderRead]:
    # Cada consulta trae el SKU en el mismo JOIN: nada de una consulta por movimiento.
    entries_query = select(StockEntry, SKU).join(SKU)
    exits_query = select(StockExit, SKU).join(SKU)
    if warehouse is not None:
        entries_query = entries_query.where(StockEntry.warehouse == warehouse.value)
        exits_query = exits_query.where(StockExit.warehouse == warehouse.value)

    orders = [
        InventoryOrderRead(
            order_type="inbound",
            id=entry.id,
            sku_code=sku.sku,
            sku_name=sku.name,
            client_name=sku.client_name,
            quantity=entry.quantity,
            warehouse=entry.warehouse,
            created_at=entry.created_at,
            user_uuid=entry.user_uuid,
            reference=entry.reference,
        )
        for entry, sku in session.exec(entries_query).all()
    ]
    orders += [
        InventoryOrderRead(
            order_type="outbound",
            id=exit_record.id,
            sku_code=sku.sku,
            sku_name=sku.name,
            client_name=sku.client_name,
            quantity=exit_record.quantity,
            warehouse=exit_record.warehouse,
            created_at=exit_record.created_at,
            user_uuid=exit_record.user_uuid,
            exit_type=exit_record.exit_type,
            tracking_number=exit_record.tracking_number,
        )
        for exit_record, sku in session.exec(exits_query).all()
    ]
    return sorted(orders, key=lambda order: order.created_at, reverse=True)


# ---------------------------------------------------------------------------
# Conteos físicos
# ---------------------------------------------------------------------------

@router.post("/counts", response_model=InventoryCountRead, status_code=status.HTTP_201_CREATED)
def create_inventory_count(
    payload: InventoryCountCreate,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InventoryCountRead:
    """Registra un conteo físico y lo compara con el stock calculado.

    No modifica el stock: si hay descuadre, se corrige después con una
    recepción o una salida `loss`, trazables al usuario que las registra.
    """
    # Con la fila bloqueada, ninguna salida cambia el stock mientras se compara.
    sku = _get_sku(session, payload.sku_id, lock=True)
    system_quantity = stock_by_warehouse(session, [sku.id])[sku.id][payload.warehouse]
    identity = inventory_telemetry.movement(sku, payload.warehouse)
    count = InventoryCount(
        **payload.model_dump(mode="json"),
        system_quantity=system_quantity,
        user_uuid=current_user.id,
    )
    session.add(count)
    session.commit()
    session.refresh(count)
    difference = count.counted_quantity - system_quantity
    logger.info(
        "Conteo %s (%s): %s en %s contado %s, sistema %s (diferencia %+d) por %s",
        count.id,
        count.detection_method,
        identity["product_id"],
        count.warehouse,
        count.counted_quantity,
        system_quantity,
        difference,
        current_user.id,
    )
    if difference != 0:
        telemetry.emit(
            "inventory_discrepancy_detected",
            {
                "count_id": count.id,
                **identity,
                "quantity": difference,
                "system_quantity": system_quantity,
                "counted_quantity": count.counted_quantity,
                "detection_method": count.detection_method,
                "discrepancy_ratio": round(abs(difference) / max(system_quantity, 1), 4),
            },
            user_id=current_user.id,
        )
    return InventoryCountRead(
        id=count.id,
        sku_id=count.sku_id,
        warehouse=count.warehouse,
        counted_quantity=count.counted_quantity,
        system_quantity=system_quantity,
        difference=difference,
        detection_method=count.detection_method,
        created_at=count.created_at,
        user_uuid=count.user_uuid,
    )


# ---------------------------------------------------------------------------
# Edición directa del stock: siempre 405 (vector 1 de direct_stock_edit_rejected)
# ---------------------------------------------------------------------------

DIRECT_EDIT_METHODS = ["PUT", "PATCH", "DELETE"]
DIRECT_EDIT_RESPONSES: dict[int | str, dict[str, Any]] = {
    405: {"model": DirectStockEditRejected, "description": inventory_telemetry.DIRECT_EDIT_DETAIL}
}


async def _json_body(request: Request) -> Any:
    try:
        return await request.json()
    except ValueError:  # sin cuerpo o cuerpo que no es JSON
        return None


def _find_sku(session: Session, value: Any) -> SKU | None:
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    return session.get(SKU, value)


async def _reject_direct_edit(
    request: Request, route: str, allow: str, sku_ref: Any, session: Session, user: User
) -> JSONResponse:
    body = await _json_body(request)
    if sku_ref is None and isinstance(body, dict):
        sku_ref = body.get("sku_id")
    sku = _find_sku(session, sku_ref)
    logger.warning(
        "Edición directa del stock rechazada: %s %s por %s", request.method, route, user.id
    )
    inventory_telemetry.emit_method_not_allowed(request, route, sku, body, user)
    return JSONResponse(
        status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        content={"detail": inventory_telemetry.DIRECT_EDIT_DETAIL},
        headers={"Allow": allow},
    )


async def reject_product_edit(
    sku_id: str,
    request: Request,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    return await _reject_direct_edit(
        request, "/inventory/products/{sku_id}", "GET", sku_id, session, current_user
    )


async def reject_stock_edit(
    sku_id: str,
    request: Request,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    return await _reject_direct_edit(
        request, "/inventory/products/{sku_id}/stock", "", sku_id, session, current_user
    )


async def reject_orders_edit(
    request: Request,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    return await _reject_direct_edit(
        request, "/inventory/orders", "GET", None, session, current_user
    )


async def reject_order_edit(
    order_path: str,
    request: Request,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    return await _reject_direct_edit(
        request, "/inventory/orders/{order_path}", "POST", None, session, current_user
    )


# Una ruta por método: con varios métodos en una misma ruta, OpenAPI repetiría
# el operationId.
for _path, _endpoint in (
    ("/products/{sku_id}", reject_product_edit),
    ("/products/{sku_id}/stock", reject_stock_edit),
    ("/orders", reject_orders_edit),
    ("/orders/{order_path:path}", reject_order_edit),
):
    for _method in DIRECT_EDIT_METHODS:
        router.add_api_route(
            _path,
            _endpoint,
            methods=[_method],
            status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
            response_model=None,
            responses=DIRECT_EDIT_RESPONSES,
        )
