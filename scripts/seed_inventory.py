"""Carga el inventario inicial (SKUs, recepciones y salidas) en PostgreSQL.

Uso, desde la raíz del monorepo:

    uv run --env-file .env python scripts/seed_inventory.py --user-email operaciones@example.com

`--user-email` es un usuario activo de TinyDB: su UUID queda en `user_uuid` de
cada movimiento sembrado, igual que si los hubiera registrado desde la API.
Es idempotente: los SKUs se identifican por su código y, si ya existen, no se
vuelven a crear ni se repiten sus movimientos. Todo va en una transacción.
"""

import argparse
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from sqlalchemy.exc import OperationalError, SQLAlchemyError  # noqa: E402
from sqlmodel import Session, SQLModel, select  # noqa: E402

from services.api.database import DatabaseNotConfiguredError, get_engine  # noqa: E402
from services.api.models import SKU, StockEntry, StockExit, Warehouse  # noqa: E402
from services.api.routes.inventory import stock_by_warehouse  # noqa: E402
from services.api.schemas import SKUCreate, StockEntryCreate, StockExitCreate  # noqa: E402
from services.api.user_service import get_user_by_email  # noqa: E402


SKUS = [
    ("Zapatilla blanca clásica - Talla 42", "CLT-SNK-W-42", "PureStep Footwear", "fashion", "LA"),
    ("Zapatilla blanca clásica - Talla 42", "CLT-SNK-W-42-Z", "PureStep Footwear", "fashion", "ZGZ"),
    ("Auriculares inalámbricos Pro", "TEC-EAR-001", "SoundWave Electronics", "electronics", "LA"),
    ("Sérum facial hidratante 30ml", "CSM-SRM-030", "GlowLab Cosmetics", "cosmetics", "ZGZ"),
    ("Chino slim fit - marino 32/32", "CLT-CHN-N-32", "UrbanThread", "fashion", "LA"),
    ("Cargador rápido USB-C 65W", "TEC-CHG-065", "SoundWave Electronics", "electronics", "ZGZ"),
]

# (código SKU, cantidad, referencia, almacén)
ENTRIES = [
    ("CLT-SNK-W-42", 120, "PO-2024-0098", "LA"),
    ("CLT-SNK-W-42", 80, "GR-LA-0234", "LA"),
    ("TEC-EAR-001", 60, "PO-2024-0112", "LA"),
    ("CLT-CHN-N-32", 45, "GR-LA-0241", "LA"),
    ("CLT-SNK-W-42-Z", 90, "PO-2024-0105", "ZGZ"),
    ("CSM-SRM-030", 150, "GR-ZGZ-0117", "ZGZ"),
    ("TEC-CHG-065", 40, "PO-2024-0120", "ZGZ"),
]

# (código SKU, cantidad, tipo, tracking, almacén)
EXITS = [
    ("CLT-SNK-W-42", 35, "dispatch", "1Z999AA10123456784", "LA"),
    ("TEC-EAR-001", 2, "loss", None, "LA"),
    ("CSM-SRM-030", 24, "dispatch", "JJD000390007775512", "ZGZ"),
    ("CLT-SNK-W-42-Z", 3, "loss", None, "ZGZ"),
]


class SeedError(Exception):
    """Fallo crítico del seed con un mensaje apto para la consola."""


def expected_stock() -> dict[str, int]:
    """Stock neto que deben dar las semillas: entradas − salidas por SKU."""
    stock = {code: 0 for _, code, *_ in SKUS}
    for code, quantity, *_ in ENTRIES:
        stock[code] += quantity
    for code, quantity, *_ in EXITS:
        stock[code] -= quantity
    return stock


def seed(session: Session, user_uuid: str) -> list[str]:
    """Inserta los SKUs que falten y sus movimientos. Devuelve los códigos creados."""
    existing = set(session.exec(select(SKU.sku)).all())
    created: dict[str, SKU] = {}
    for name, code, client_name, category, warehouse in SKUS:
        if code in existing:
            continue
        # Mismas validaciones que la API.
        payload = SKUCreate(
            name=name, sku=code, client_name=client_name, category=category, warehouse=warehouse
        )
        created[code] = SKU(**payload.model_dump(mode="json"))
        session.add(created[code])
    session.flush()  # asigna los id de los SKUs nuevos

    for code, quantity, reference, warehouse in ENTRIES:
        if code in created:
            payload = StockEntryCreate(
                sku_id=created[code].id, quantity=quantity, reference=reference, warehouse=warehouse
            )
            session.add(StockEntry(**payload.model_dump(mode="json"), user_uuid=user_uuid))
    for code, quantity, exit_type, tracking_number, warehouse in EXITS:
        if code in created:
            payload = StockExitCreate(
                sku_id=created[code].id,
                quantity=quantity,
                exit_type=exit_type,
                tracking_number=tracking_number,
                warehouse=warehouse,
            )
            session.add(StockExit(**payload.model_dump(mode="json"), user_uuid=user_uuid))
    session.commit()
    return list(created)


def check_stock(session: Session) -> dict[str, int]:
    """Compara el stock calculado de cada SKU sembrado con el esperado."""
    skus = session.exec(select(SKU).where(SKU.sku.in_([code for _, code, *_ in SKUS]))).all()
    stock = stock_by_warehouse(session, [sku.id for sku in skus])
    actual = {sku.sku: stock[sku.id][Warehouse(sku.warehouse)] for sku in skus}
    expected = expected_stock()
    mismatches = {code: (actual.get(code), value) for code, value in expected.items() if actual.get(code) != value}
    if mismatches:
        details = ", ".join(f"{code}: {got} en vez de {want}" for code, (got, want) in mismatches.items())
        raise SeedError(
            f"El stock no coincide con las semillas ({details}). "
            "¿Hay movimientos registrados a mano sobre estos SKUs?"
        )
    return actual


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--user-email", required=True, help="Usuario de TinyDB que firma los movimientos.")
    args = parser.parse_args(argv)

    try:
        user = get_user_by_email(args.user_email)
        if user is None or not user.is_active:
            raise SeedError(f"No hay ningún usuario activo con el email {args.user_email} en TinyDB.")
        engine = get_engine()
        SQLModel.metadata.create_all(engine)
        with Session(engine) as session:
            created = seed(session, user.id)
            stock = check_stock(session)
    except (SeedError, DatabaseNotConfiguredError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except OperationalError:
        print("Error: no se pudo conectar con PostgreSQL. Revisa DATABASE_URL en .env.", file=sys.stderr)
        return 1
    except SQLAlchemyError as error:
        print(f"Error de base de datos: {error.__class__.__name__}", file=sys.stderr)
        return 1

    print(f"SKUs creados: {len(created)} ({', '.join(created) or 'ninguno, ya existían'})")
    for code, units in stock.items():
        print(f"  {code}: {units} unidades")
    return 0


if __name__ == "__main__":
    sys.exit(main())
