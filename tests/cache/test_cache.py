"""Caché TTL (`services/api/cache.py`) y su uso en inventario e incidencias.

Los handlers se llaman como funciones, igual que en `tests/inventory` y
`tests/backoffice`; el paso por HTTP (auth antes de la caché) va al final.
"""

import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from packages.shared.incidents.domain import IncidentStatus
from services.api.cache import TTLCache
from services.api.database import INCIDENTS_TABLE, get_incidents_db
from services.api.incident_models import IncidentCreate, IncidentStatusUpdate
from services.api.main import app
from services.api.models import StockEntry
from services.api.routes import incidents as incidents_routes
from services.api.routes import inventory as inventory_routes
from services.api.routes.incidents import (
    create_incident,
    incidents_summary,
    summary_cache,
    update_incident_status,
)
from services.api.routes.inventory import (
    create_inbound_order,
    create_outbound_order,
    create_product,
    list_products,
    products_cache,
)
from services.api.schemas import SKUCreate, StockEntryCreate, StockExitCreate


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


# --- TTLCache -----------------------------------------------------------------

def test_second_read_is_served_from_cache(clock):
    cache: TTLCache[str] = TTLCache("t", 30, clock=clock)
    calls = []
    compute = lambda: calls.append(1) or "valor"  # noqa: E731

    assert cache.get_or_compute("k", compute) == "valor"
    assert cache.get_or_compute("k", compute) == "valor"
    assert len(calls) == 1
    assert (cache.hits, cache.misses) == (1, 1)


def test_entry_expires_exactly_at_ttl(clock):
    cache: TTLCache[int] = TTLCache("t", 30, clock=clock)
    values = iter([1, 2])
    cache.get_or_compute("k", lambda: next(values))

    clock.now += 29.9
    assert cache.get_or_compute("k", lambda: next(values)) == 1
    clock.now += 0.1
    assert cache.get_or_compute("k", lambda: next(values)) == 2


def test_invalidate_drops_every_key(clock):
    cache: TTLCache[str] = TTLCache("t", 30, clock=clock)
    cache.get_or_compute("a", lambda: "a1")
    cache.get_or_compute("b", lambda: "b1")

    cache.invalidate("escritura")

    assert cache.get_or_compute("a", lambda: "a2") == "a2"
    assert cache.get_or_compute("b", lambda: "b2") == "b2"


def test_keys_are_independent(clock):
    cache: TTLCache[str] = TTLCache("t", 30, clock=clock)
    assert cache.get_or_compute("LA", lambda: "la") == "la"
    assert cache.get_or_compute("ZGZ", lambda: "zgz") == "zgz"


def test_maxsize_evicts_least_recently_used(clock):
    cache: TTLCache[str] = TTLCache("t", 30, maxsize=2, clock=clock)
    cache.get_or_compute("a", lambda: "a")
    cache.get_or_compute("b", lambda: "b")
    cache.get_or_compute("a", lambda: "no")  # "a" pasa a ser la más reciente
    cache.get_or_compute("c", lambda: "c")  # expulsa "b"

    assert cache.get_or_compute("a", lambda: "no") == "a"
    assert cache.get_or_compute("b", lambda: "b2") == "b2"


def test_ttl_is_mandatory():
    with pytest.raises(ValueError):
        TTLCache("t", 0)


def test_value_computed_during_an_invalidation_is_not_stored(clock):
    """Una lectura que empezó antes de un commit no deja en caché el dato viejo."""
    cache: TTLCache[str] = TTLCache("t", 30, clock=clock)

    def slow_read_racing_a_write() -> str:
        cache.invalidate("escritura concurrente")
        return "leído antes del commit"

    assert cache.get_or_compute("k", slow_read_racing_a_write) == "leído antes del commit"
    assert cache.get_or_compute("k", lambda: "fresco") == "fresco"


def test_concurrent_reads_return_consistent_values(clock):
    cache: TTLCache[int] = TTLCache("t", 30, clock=clock)
    results: list[int] = []
    threads = [
        threading.Thread(target=lambda: results.append(cache.get_or_compute("k", lambda: 7)))
        for _ in range(20)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results == [7] * 20


# --- GET /inventory/products ---------------------------------------------------

@pytest.fixture
def session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    event.listen(engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db_session:
        yield db_session
    engine.dispose()


@pytest.fixture
def operator(make_user):
    return make_user(email="almacen.la@example.com")


def new_sku(session, user, code="CLT-SNK-W-42", warehouse="LA"):
    payload = SKUCreate(
        name="Zapatilla blanca clásica - Talla 42",
        sku=code,
        client_name="PureStep Footwear",
        category="fashion",
        warehouse=warehouse,
    )
    return create_product(payload, session, user)


def stock_of(session, code):
    return {item.sku: item.current_stock for item in list_products(warehouse=None, session=session)}[code]


def test_products_list_is_cached_between_reads(session, operator, monkeypatch):
    new_sku(session, operator)
    list_products(warehouse=None, session=session)

    calls = []
    original = inventory_routes.stock_by_warehouse
    monkeypatch.setattr(
        inventory_routes, "stock_by_warehouse", lambda *a, **k: calls.append(1) or original(*a, **k)
    )
    list_products(warehouse=None, session=session)
    assert calls == []


def test_inbound_order_invalidates_products(session, operator):
    sku = new_sku(session, operator)
    assert stock_of(session, sku.sku) == 0

    create_inbound_order(
        StockEntryCreate(sku_id=sku.id, quantity=120, reference="PO-1", warehouse="LA"), session, operator
    )
    assert stock_of(session, sku.sku) == 120


def test_outbound_order_invalidates_products(session, operator):
    sku = new_sku(session, operator)
    create_inbound_order(
        StockEntryCreate(sku_id=sku.id, quantity=120, reference="PO-1", warehouse="LA"), session, operator
    )
    assert stock_of(session, sku.sku) == 120

    create_outbound_order(
        StockExitCreate(
            sku_id=sku.id, quantity=35, exit_type="dispatch", tracking_number="1Z9", warehouse="LA"
        ),
        session,
        operator,
    )
    assert stock_of(session, sku.sku) == 85


def test_new_sku_invalidates_every_warehouse_filter(session, operator):
    new_sku(session, operator)
    assert len(list_products(warehouse=None, session=session)) == 1
    assert len(list_products(warehouse=inventory_routes.Warehouse.ZGZ, session=session)) == 0

    new_sku(session, operator, code="CSM-SRM-030", warehouse="ZGZ")

    assert len(list_products(warehouse=None, session=session)) == 2
    assert len(list_products(warehouse=inventory_routes.Warehouse.ZGZ, session=session)) == 1


def test_write_outside_the_api_is_visible_after_ttl(session, operator, monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(products_cache, "_clock", clock)
    sku = new_sku(session, operator)
    assert stock_of(session, sku.sku) == 0

    # Un seed o una réplica escriben sin pasar por esta instancia: no hay invalidación.
    session.add(StockEntry(sku_id=sku.id, quantity=50, reference="SEED", warehouse="LA", user_uuid="seed"))
    session.commit()
    assert stock_of(session, sku.sku) == 0

    clock.now += inventory_routes.PRODUCTS_CACHE_TTL_SECONDS
    assert stock_of(session, sku.sku) == 50


def test_exit_checks_live_stock_not_the_cached_list(session, operator):
    """La caché no interviene en la regla de stock: la salida recalcula con la fila bloqueada."""
    sku = new_sku(session, operator)
    create_inbound_order(
        StockEntryCreate(sku_id=sku.id, quantity=10, reference="PO-1", warehouse="LA"), session, operator
    )
    stock_of(session, sku.sku)  # deja 10 en caché
    session.add(StockEntry(sku_id=sku.id, quantity=5, reference="SEED", warehouse="LA", user_uuid="seed"))
    session.commit()

    exit_record = create_outbound_order(
        StockExitCreate(sku_id=sku.id, quantity=15, exit_type="loss", warehouse="LA"), session, operator
    )
    assert exit_record.quantity == 15  # con la lista en caché (10) se habría rechazado


# --- GET /api/incidents/summary -------------------------------------------------

def incident() -> IncidentCreate:
    return IncidentCreate(
        title="Paquete perdido en reparto",
        description="El cliente no recibió el pedido 4411.",
        category="lost_parcel",
        origin="customer",
        branch="la_warehouse",
    )


def test_summary_is_cached_between_reads(operator, monkeypatch):
    create_incident(incident(), operator)
    incidents_summary()

    monkeypatch.setattr(
        incidents_routes, "get_incidents_db", lambda: pytest.fail("no debe leer TinyDB")
    )
    assert incidents_summary().total == 1


def test_new_incident_invalidates_summary(operator):
    create_incident(incident(), operator)
    assert incidents_summary().total == 1

    create_incident(incident(), operator)
    assert incidents_summary().total == 2


def test_status_change_invalidates_summary(operator):
    created = create_incident(incident(), operator)
    assert incidents_summary().by_status[IncidentStatus.OPEN] == 1

    update_incident_status(created.id, IncidentStatusUpdate(status="in_progress"), operator)

    summary = incidents_summary()
    assert summary.by_status[IncidentStatus.OPEN] == 0
    assert summary.by_status[IncidentStatus.IN_PROGRESS] == 1


def test_seed_outside_the_api_is_visible_after_ttl(operator, monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(summary_cache, "_clock", clock)
    assert incidents_summary().total == 0

    with get_incidents_db() as db:
        db.table(INCIDENTS_TABLE).insert(
            {**incident().model_dump(), "reported_by": None, "created_at": "2024-01-01T00:00:00+00:00",
             "updated_at": "2024-01-01T00:00:00+00:00"}
        )
    assert incidents_summary().total == 0

    clock.now += incidents_routes.SUMMARY_CACHE_TTL_SECONDS
    assert incidents_summary().total == 1


# --- HTTP: la autenticación va antes que la caché ------------------------------

def test_cached_endpoints_still_require_a_token(operator):
    create_incident(incident(), operator)
    incidents_summary()  # resumen ya en caché

    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/api/incidents/summary").status_code == 401
    assert client.get("/inventory/products").status_code == 401
