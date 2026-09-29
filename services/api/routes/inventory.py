"""Inventario unificado de SKUs en los almacenes de Los Ángeles y Zaragoza.

El stock nunca se escribe: se calcula por SKU y almacén como
SUMA(StockEntry.quantity) − SUMA(StockExit.quantity). La única forma de
cambiarlo es registrar una recepción o una salida, y cada una guarda el
`user_uuid` (TinyDB) de quien la registró.
"""

import logging
from collections import defaultdict
from collections.abc import Iterable

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from services.api.auth_models import User
from services.api.database import get_db
from services.api.models import SKU, StockEntry, StockExit, Warehouse
from services.api.schemas import (
    InventoryOrderRead,
    SKUCreate,
    SKURead,
    SKUSummary,
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


def _sku_read(sku: SKU, stock: StockTable) -> SKURead:
    by_warehouse = stock[sku.id]
    return SKURead(
        id=sku.id,
        name=sku.name,
        sku=sku.sku,
        client_name=sku.client_name,
        category=sku.category,
        warehouse=sku.warehouse,
        # Un SKU se da de alta en un almacén; su stock "actual" es el de ese almacén.
        current_stock=by_warehouse[Warehouse(sku.warehouse)],
        stock_by_warehouse=by_warehouse,
    )


def _sku_summary(sku: SKU) -> SKUSummary:
    return SKUSummary(
        id=sku.id,
        name=sku.name,
        sku=sku.sku,
        client_name=sku.client_name,
        warehouse=sku.warehouse,
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

@router.get("/products", response_model=list[SKURead])
def list_products(
    warehouse: Warehouse | None = Query(
        default=None, description="Solo los SKUs dados de alta en este almacén."
    ),
    session: Session = Depends(get_db),
) -> list[SKURead]:
    query = select(SKU).order_by(SKU.id)
    if warehouse is not None:
        query = query.where(SKU.warehouse == warehouse.value)
    skus = session.exec(query).all()
    stock = stock_by_warehouse(session, [sku.id for sku in skus])
    return [_sku_read(sku, stock) for sku in skus]


@router.post("/products", response_model=SKURead, status_code=status.HTTP_201_CREATED)
def create_product(
    payload: SKUCreate,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SKURead:
    if session.exec(select(SKU.id).where(SKU.sku == payload.sku)).first() is not None:
        raise HTTPException(status_code=409, detail=f"El SKU '{payload.sku}' ya está registrado.")
    sku = SKU(**payload.model_dump(mode="json"))
    session.add(sku)
    try:
        session.commit()
    except IntegrityError as error:
        # Otra petición registró el mismo código entre la comprobación y el commit.
        session.rollback()
        raise HTTPException(
            status_code=409, detail=f"El SKU '{payload.sku}' ya está registrado."
        ) from error
    session.refresh(sku)
    logger.info(
        "SKU %s (%s) registrado en %s por %s", sku.id, sku.sku, sku.warehouse, current_user.id
    )
    # Un SKU nuevo empieza sin stock: solo una recepción puede añadirlo.
    return _sku_read(sku, stock_by_warehouse(session, [sku.id]))


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
    entry = StockEntry(**payload.model_dump(mode="json"), user_uuid=current_user.id)
    session.add(entry)
    session.commit()
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
    if payload.quantity > available:
        session.rollback()  # libera el bloqueo sin haber escrito nada
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
    return StockExitRead.model_validate(exit_record, from_attributes=True)


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
            sku=_sku_summary(sku),
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
            sku=_sku_summary(sku),
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
