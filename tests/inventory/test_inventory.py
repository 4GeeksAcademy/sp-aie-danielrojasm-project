"""Inventario (`routes/inventory.py`, `schemas.py`, `models.py`).

Los handlers se llaman como funciones con una sesión de SQLite en memoria: se
prueba la lógica de stock, no PostgreSQL. Las restricciones CHECK y las claves
foráneas de `models.py` también se aplican en SQLite.
"""

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from services.api.models import StockExit, Warehouse
from services.api.routes.inventory import (
    create_inbound_order,
    create_outbound_order,
    create_product,
    get_product,
    list_orders,
    list_products,
)
from services.api.schemas import SKUCreate, StockEntryCreate, StockExitCreate


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    # SQLite no aplica las claves foráneas si no se activan por conexión.
    event.listen(engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db_session:
        yield db_session
    engine.dispose()


@pytest.fixture
def operator(make_user):
    return make_user(email="almacen.la@example.com")


def new_sku(session, user, **overrides):
    data = {
        "name": "Zapatilla blanca clásica - Talla 42",
        "sku": "CLT-SNK-W-42",
        "client_name": "PureStep Footwear",
        "category": "fashion",
        "warehouse": "LA",
    }
    return create_product(SKUCreate(**{**data, **overrides}), session, user)


def receive(session, user, sku_id, quantity, warehouse="LA", reference="PO-2024-0098"):
    payload = StockEntryCreate(
        sku_id=sku_id, quantity=quantity, reference=reference, warehouse=warehouse
    )
    return create_inbound_order(payload, session, user)


def dispatch(session, user, sku_id, quantity, warehouse="LA", **overrides):
    data = {
        "sku_id": sku_id,
        "quantity": quantity,
        "exit_type": "dispatch",
        "tracking_number": "1Z999AA10123456784",
        "warehouse": warehouse,
    }
    return create_outbound_order(StockExitCreate(**{**data, **overrides}), session, user)


# --- Camino feliz -----------------------------------------------------------

def test_new_sku_starts_with_zero_stock(session, operator):
    created = new_sku(session, operator)
    assert created.current_stock == 0
    assert created.stock_by_warehouse == {"LA": 0, "ZGZ": 0}


def test_stock_is_entries_minus_exits(session, operator):
    sku = new_sku(session, operator)
    receive(session, operator, sku.id, 120)
    receive(session, operator, sku.id, 80, reference="GR-LA-0234")
    dispatch(session, operator, sku.id, 35)
    dispatch(session, operator, sku.id, 5, exit_type="loss", tracking_number=None)
    assert get_product(sku.id, session).current_stock == 160


def test_orders_store_the_authenticated_user_uuid(session, operator):
    sku = new_sku(session, operator)
    entry = receive(session, operator, sku.id, 10)
    exit_record = dispatch(session, operator, sku.id, 4)
    # Trazabilidad: el UUID viene de TinyDB, nunca del cuerpo de la petición.
    assert entry.user_uuid == exit_record.user_uuid == operator.id


def test_list_orders_includes_sku_data_newest_first(session, operator):
    sku = new_sku(session, operator)
    receive(session, operator, sku.id, 10)
    dispatch(session, operator, sku.id, 3)

    orders = list_orders(warehouse=None, session=session)
    assert [order.order_type for order in orders] == ["outbound", "inbound"]
    assert orders[0].sku_code == "CLT-SNK-W-42"
    assert orders[0].tracking_number == "1Z999AA10123456784"
    assert orders[1].reference == "PO-2024-0098"


def test_list_products_filters_by_warehouse(session, operator):
    new_sku(session, operator)
    new_sku(session, operator, sku="CSM-SRM-030", name="Sérum facial hidratante 30ml",
            client_name="GlowLab Cosmetics", category="cosmetics", warehouse="ZGZ")
    assert len(list_products(warehouse=None, session=session)) == 2
    # FastAPI entrega el filtro ya convertido a enum.
    assert [s.sku for s in list_products(warehouse=Warehouse.ZGZ, session=session)] == ["CSM-SRM-030"]


# --- Casos límite -----------------------------------------------------------

def test_stock_is_per_warehouse_not_aggregated(session, operator):
    sku = new_sku(session, operator)
    receive(session, operator, sku.id, 20, warehouse="LA")
    receive(session, operator, sku.id, 15, warehouse="ZGZ")

    product = get_product(sku.id, session)
    # 20 en LA y 15 en ZGZ son dos cifras, no 35.
    assert product.stock_by_warehouse == {"LA": 20, "ZGZ": 15}
    assert product.current_stock == 20


def test_exit_can_take_exactly_the_available_stock(session, operator):
    sku = new_sku(session, operator)
    receive(session, operator, sku.id, 12)
    dispatch(session, operator, sku.id, 12)
    assert get_product(sku.id, session).current_stock == 0


def test_stock_in_another_warehouse_does_not_cover_an_exit(session, operator):
    sku = new_sku(session, operator)
    receive(session, operator, sku.id, 50, warehouse="ZGZ")
    with pytest.raises(HTTPException) as raised:
        dispatch(session, operator, sku.id, 1, warehouse="LA")
    assert raised.value.status_code == 400
    assert raised.value.detail == (
        "Insufficient stock for SKU 'CLT-SNK-W-42'. Available: 0, requested: 1."
    )


def test_text_fields_are_trimmed(session, operator):
    created = new_sku(session, operator, sku="  TEC-EAR-001 ", name=" Auriculares inalámbricos Pro ")
    assert created.sku == "TEC-EAR-001"
    assert created.name == "Auriculares inalámbricos Pro"


# --- Modos de fallo ---------------------------------------------------------

def test_exit_above_stock_is_rejected_before_writing(session, operator):
    sku = new_sku(session, operator)
    receive(session, operator, sku.id, 10)
    with pytest.raises(HTTPException) as raised:
        dispatch(session, operator, sku.id, 11)
    assert raised.value.status_code == 400
    assert raised.value.detail == (
        "Insufficient stock for SKU 'CLT-SNK-W-42'. Available: 10, requested: 11."
    )
    # No se ha guardado ninguna salida y el stock sigue intacto.
    assert session.exec(select(StockExit)).all() == []
    assert get_product(sku.id, session).current_stock == 10


def test_dispatch_requires_tracking_number():
    with pytest.raises(ValidationError, match="necesita tracking_number"):
        StockExitCreate(sku_id=1, quantity=1, exit_type="dispatch", warehouse="LA")
    with pytest.raises(ValidationError):
        StockExitCreate(sku_id=1, quantity=1, exit_type="dispatch", tracking_number="  ", warehouse="LA")


def test_loss_must_not_carry_tracking_number():
    with pytest.raises(ValidationError, match="no lleva tracking_number"):
        StockExitCreate(
            sku_id=1, quantity=1, exit_type="loss", tracking_number="1Z999", warehouse="LA"
        )


@pytest.mark.parametrize("quantity", [0, -5])
def test_quantities_must_be_positive(quantity):
    # Una entrada negativa sería una forma encubierta de restar stock.
    with pytest.raises(ValidationError):
        StockEntryCreate(sku_id=1, quantity=quantity, reference="PO-1", warehouse="LA")


def test_stock_and_user_cannot_be_sent_by_the_client():
    with pytest.raises(ValidationError):
        SKUCreate(name="X", sku="X-1", client_name="Y", category="fashion",
                  warehouse="LA", current_stock=500)
    with pytest.raises(ValidationError):
        StockEntryCreate(sku_id=1, quantity=1, reference="PO-1", warehouse="LA",
                         user_uuid="otro-usuario")


@pytest.mark.parametrize(
    "field, value", [("category", "food"), ("warehouse", "MAD")], ids=["categoria", "almacen"]
)
def test_unknown_category_or_warehouse_is_rejected(field, value):
    data = {"name": "X", "sku": "X-1", "client_name": "Y", "category": "fashion", "warehouse": "LA"}
    with pytest.raises(ValidationError):
        SKUCreate(**{**data, field: value})


def test_duplicate_sku_code_is_409(session, operator):
    new_sku(session, operator)
    with pytest.raises(HTTPException) as raised:
        new_sku(session, operator, warehouse="ZGZ")
    assert raised.value.status_code == 409


def test_orders_for_unknown_sku_are_404(session, operator):
    with pytest.raises(HTTPException) as raised:
        receive(session, operator, 999, 5)
    assert raised.value.status_code == 404
    with pytest.raises(HTTPException) as raised:
        get_product(999, session)
    assert raised.value.status_code == 404


def test_database_rejects_inconsistent_rows(session, operator):
    # Última barrera si alguien escribe sin pasar por la API.
    sku = new_sku(session, operator)
    session.add(StockExit(sku_id=sku.id, quantity=1, exit_type="dispatch",
                          tracking_number=None, warehouse="LA", user_uuid=operator.id))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    session.add(StockExit(sku_id=12345, quantity=1, exit_type="loss",
                          warehouse="LA", user_uuid=operator.id))
    with pytest.raises(IntegrityError):
        session.commit()
