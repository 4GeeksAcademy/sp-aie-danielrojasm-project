"""Carga volumen realista para medir la API (inventario e incidencias).

Uso, desde la raíz del monorepo:

    uv run python scripts/seed_load_test.py \\
        --database-url sqlite:///C:/tmp/trackflow-load.db \\
        --incidents-db C:/tmp/trackflow-load-incidents.json

Con pocos registros casi todo responde en milisegundos y el middleware de timing
no distingue qué merece caché. Este script llena una base **local y vacía** con
un catálogo de SKUs, un histórico de movimientos de 18 meses y miles de
incidencias, con datos variados (clientes, categorías, almacenes, fechas y
cantidades) para que los GROUP BY, los JOIN y las agregaciones cuesten de verdad.

Solo acepta SQLite o PostgreSQL en localhost: nunca escribe en Supabase. Es
determinista (`--seed`) y se niega a sembrar sobre datos existentes.
"""

import argparse
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from sqlalchemy import func, insert  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402
from sqlmodel import Session, SQLModel, create_engine, select  # noqa: E402
from tinydb import TinyDB  # noqa: E402

from packages.shared.incidents.domain import (  # noqa: E402
    Branch,
    IncidentCategory,
    IncidentOrigin,
    IncidentStatus,
)
from services.api.database import INCIDENTS_TABLE  # noqa: E402
from services.api.models import SKU, StockEntry, StockExit  # noqa: E402


LOCAL_HOSTS = {None, "", "localhost", "127.0.0.1", "::1"}
# UUID fijo y reconocible: estos movimientos no son de ningún usuario real.
LOAD_TEST_USER = "00000000-0000-4000-8000-000000000001"
HISTORY_DAYS = 540

# (marca cliente, categoría, prefijo del SKU, productos)
CATALOG = [
    ("PureStep Footwear", "fashion", "CLT-SNK", ["Zapatilla urbana", "Zapatilla running", "Bota chelsea"]),
    ("UrbanThread", "fashion", "CLT-CHN", ["Chino slim fit", "Camisa oxford", "Sudadera con capucha"]),
    ("Nordic Knit", "fashion", "CLT-KNT", ["Jersey de lana merino", "Bufanda de punto", "Gorro trenzado"]),
    ("SoundWave Electronics", "electronics", "TEC-EAR", ["Auriculares inalámbricos", "Altavoz portátil", "Barra de sonido"]),
    ("VoltCore", "electronics", "TEC-CHG", ["Cargador USB-C 65W", "Batería externa 20000mAh", "Hub USB-C 7 en 1"]),
    ("PixelHome", "electronics", "TEC-CAM", ["Cámara de seguridad Wi-Fi", "Timbre inteligente", "Enchufe inteligente"]),
    ("GlowLab Cosmetics", "cosmetics", "CSM-SRM", ["Sérum hidratante", "Crema de noche", "Contorno de ojos"]),
    ("Terra Botanica", "cosmetics", "CSM-SHP", ["Champú sólido", "Acondicionador vegano", "Aceite capilar"]),
    ("Solaris Skin", "cosmetics", "CSM-SPF", ["Protector solar SPF50", "After sun calmante", "Bruma facial"]),
]
VARIANTS = ["XS", "S", "M", "L", "XL", "Negro", "Blanco", "Azul", "Verde", "30ml", "50ml", "100ml"]

INCIDENT_TEMPLATES = {
    IncidentCategory.LOST_PARCEL: "Paquete sin movimiento en el tracking desde hace {n} días",
    IncidentCategory.DELIVERY_FAILURE: "Entrega fallida: destinatario ausente en {n} intentos",
    IncidentCategory.INVENTORY_DISCREPANCY: "Diferencia de {n} unidades entre WMS y recuento físico",
    IncidentCategory.CARRIER_ISSUE: "El transportista no recogió {n} bultos en la franja acordada",
    IncidentCategory.RETURNS_ISSUE: "Devolución recibida con {n} artículos que no coinciden con el RMA",
    IncidentCategory.WAREHOUSE_INCIDENT: "Muelle {n} bloqueado por palés sin ubicar",
    IncidentCategory.SYSTEM_FAILURE: "Caída de la integración de pedidos durante {n} minutos",
    IncidentCategory.CLIENT_COMPLAINT: "Reclamación por embalaje dañado en {n} pedidos",
    IncidentCategory.OTHER: "Consulta interna pendiente de clasificar ({n})",
}
# Pesos aproximados de la muestra real de TrackFlow: más carrier y entregas que sistema.
CATEGORY_WEIGHTS = [14, 19, 8, 45, 17, 6, 3, 10, 4]
STATUS_WEIGHTS = [29, 10, 52, 14]


class LoadSeedError(Exception):
    """Entrada no válida o base de destino no vacía."""


def _require_local(database_url: str) -> None:
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite":
        return
    if url.get_backend_name() != "postgresql" or url.host not in LOCAL_HOSTS:
        raise LoadSeedError(
            "Solo se siembra en SQLite o en PostgreSQL de localhost; nunca en Supabase."
        )


def _random_moment(rng: random.Random, now: datetime) -> datetime:
    return now - timedelta(days=rng.uniform(0, HISTORY_DAYS), seconds=rng.randint(0, 86_399))


def build_skus(count: int, rng: random.Random) -> list[dict[str, str]]:
    skus: list[dict[str, str]] = []
    for index in range(count):
        client, category, prefix, products = CATALOG[index % len(CATALOG)]
        warehouse = "LA" if rng.random() < 0.55 else "ZGZ"
        variant = rng.choice(VARIANTS)
        skus.append(
            {
                "name": f"{rng.choice(products)} - {variant}",
                "sku": f"{prefix}-{index:05d}{'-Z' if warehouse == 'ZGZ' else ''}",
                "client_name": client,
                "category": category,
                "warehouse": warehouse,
            }
        )
    return skus


def build_movements(
    sku_rows: list[tuple[int, str]], movements_per_sku: int, rng: random.Random, now: datetime
) -> tuple[list[dict], list[dict]]:
    """Recepciones y salidas por SKU; las salidas nunca dejan el stock en negativo."""
    entries: list[dict] = []
    exits: list[dict] = []
    for sku_id, warehouse in sku_rows:
        received = 0
        for number in range(max(1, int(movements_per_sku * 0.6))):
            quantity = rng.randint(10, 400)
            received += quantity
            entries.append(
                {
                    "sku_id": sku_id,
                    "quantity": quantity,
                    "reference": f"PO-{now.year - 1}-{sku_id:05d}-{number:03d}",
                    "warehouse": warehouse,
                    "created_at": _random_moment(rng, now),
                    "user_uuid": LOAD_TEST_USER,
                }
            )
        remaining = int(received * rng.uniform(0.4, 0.95))
        for _ in range(max(1, movements_per_sku - int(movements_per_sku * 0.6))):
            if remaining <= 0:
                break
            quantity = min(remaining, rng.randint(1, 60))
            remaining -= quantity
            is_loss = rng.random() < 0.07
            exits.append(
                {
                    "sku_id": sku_id,
                    "quantity": quantity,
                    "exit_type": "loss" if is_loss else "dispatch",
                    "tracking_number": None if is_loss else f"1Z{rng.randrange(10**15):015d}",
                    "warehouse": warehouse,
                    "created_at": _random_moment(rng, now),
                    "user_uuid": LOAD_TEST_USER,
                }
            )
    return entries, exits


def build_incidents(count: int, rng: random.Random, now: datetime) -> list[dict]:
    categories = list(IncidentCategory)
    incidents = []
    for _ in range(count):
        category = rng.choices(categories, weights=CATEGORY_WEIGHTS)[0]
        created = _random_moment(rng, now)
        title = INCIDENT_TEMPLATES[category].format(n=rng.randint(2, 12))
        incidents.append(
            {
                "title": title,
                "description": f"{title}. Registrada para seguimiento del equipo de operaciones.",
                "category": category.value,
                "status": rng.choices(list(IncidentStatus), weights=STATUS_WEIGHTS)[0].value,
                "origin": rng.choice(list(IncidentOrigin)).value,
                "branch": rng.choice(list(Branch)).value,
                "reported_by": None,
                "created_at": created.isoformat(),
                "updated_at": (created + timedelta(hours=rng.randint(0, 96))).isoformat(),
            }
        )
    return incidents


def seed_inventory(database_url: str, sku_count: int, movements_per_sku: int, rng: random.Random) -> tuple[int, int, int]:
    _require_local(database_url)
    engine = create_engine(database_url)
    SQLModel.metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        if session.exec(select(func.count()).select_from(SKU)).one() > 0:
            raise LoadSeedError("La base de inventario ya tiene SKUs: usa una base vacía.")
        session.execute(insert(SKU), build_skus(sku_count, rng))
        sku_rows = [(sku_id, warehouse) for sku_id, warehouse in session.exec(select(SKU.id, SKU.warehouse)).all()]
        entries, exits = build_movements(sku_rows, movements_per_sku, rng, now)
        session.execute(insert(StockEntry), entries)
        session.execute(insert(StockExit), exits)
        session.commit()
    engine.dispose()
    return len(sku_rows), len(entries), len(exits)


def seed_incidents(path: Path, count: int, rng: random.Random) -> int:
    with TinyDB(path) as db:
        table = db.table(INCIDENTS_TABLE)
        if len(table) > 0:
            raise LoadSeedError(f"{path} ya tiene incidencias: usa un fichero nuevo.")
        table.insert_multiple(build_incidents(count, rng, datetime.now(timezone.utc)))
        return len(table)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database-url", required=True, help="SQLite o PostgreSQL local (nunca Supabase).")
    parser.add_argument("--incidents-db", required=True, type=Path, help="Fichero TinyDB nuevo para incidencias.")
    parser.add_argument("--skus", type=int, default=1200)
    parser.add_argument("--movements-per-sku", type=int, default=60)
    parser.add_argument("--incidents", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    try:
        skus, entries, exits = seed_inventory(args.database_url, args.skus, args.movements_per_sku, rng)
        incidents = seed_incidents(args.incidents_db, args.incidents, rng)
    except LoadSeedError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except SQLAlchemyError as error:
        print(f"Error de base de datos: {error.__class__.__name__}", file=sys.stderr)
        return 1

    print(f"Inventario: {skus} SKUs, {entries} recepciones, {exits} salidas.")
    print(f"Incidencias: {incidents}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
