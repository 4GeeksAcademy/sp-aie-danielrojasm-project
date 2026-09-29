import sys
from datetime import datetime, timezone

from pydantic import ValidationError

from services.api.database import get_suppliers_db
from services.api.supplier_models import SupplierCreate


SUPPLIERS_SEED = [
    {"name": "UPS Ground", "country": "USA", "categories": ["carrier_last_mile"], "rate_per_shipment": 7.45, "currency": "USD", "status": "active", "service_zone": "West Coast", "contact_email": "business@ups.com", "notes": "Carrier principal para entregas locales en Los Ángeles y alrededores."},
    {"name": "FedEx Ground", "country": "USA", "categories": ["carrier_last_mile"], "rate_per_shipment": 7.90, "currency": "USD", "status": "active", "service_zone": "Continental USA", "contact_email": "business.solutions@fedex.com"},
    {"name": "DHL Express USA", "country": "USA", "categories": ["carrier_last_mile", "carrier_international"], "rate_per_shipment": 14.20, "currency": "USD", "status": "active", "service_zone": "Continental USA + International", "contact_email": "business.us@dhl.com", "notes": "Usado para envíos urgentes y exportaciones a Europa."},
    {"name": "OnTrac", "country": "USA", "categories": ["carrier_last_mile"], "rate_per_shipment": 6.10, "currency": "USD", "status": "active", "service_zone": "West Coast", "contact_email": "solutions@ontrac.com", "notes": "Carrier regional. Mejor tarifa en la zona de Los Ángeles."},
    {"name": "Laser Ship", "country": "USA", "categories": ["carrier_last_mile"], "rate_per_shipment": 5.80, "currency": "USD", "status": "suspended", "service_zone": "East Coast", "contact_email": "business@lasership.com", "notes": "Suspendido. Tasa de incidencias superior al 8% en Q3."},
    {"name": "PackSource LA", "country": "USA", "categories": ["packaging_materials"], "rate_per_shipment": 0.42, "currency": "USD", "status": "active", "contact_email": "orders@packsource.com", "notes": "Cajas, relleno y precinto para el almacén de Los Ángeles."},
    {"name": "CleanTeam West", "country": "USA", "categories": ["cleaning_and_facilities"], "rate_per_shipment": 1800.0, "currency": "USD", "status": "active", "contact_email": "accounts@cleanteamwest.com", "notes": "Tarifa mensual por servicio de limpieza del almacén de LA."},
    {"name": "MRW España", "country": "Spain", "categories": ["carrier_last_mile"], "rate_per_shipment": 4.90, "currency": "EUR", "status": "active", "service_zone": "Península Ibérica", "contact_email": "clientes.empresa@mrw.es", "notes": "Carrier principal para entregas en España. Contrato negociado por volumen."},
    {"name": "SEUR", "country": "Spain", "categories": ["carrier_last_mile"], "rate_per_shipment": 5.20, "currency": "EUR", "status": "active", "service_zone": "Península Ibérica + Baleares", "contact_email": "grandes.cuentas@seur.com"},
    {"name": "DHL Express España", "country": "Spain", "categories": ["carrier_last_mile", "carrier_international"], "rate_per_shipment": 12.80, "currency": "EUR", "status": "active", "service_zone": "España + Internacional", "contact_email": "business.es@dhl.com", "notes": "Envíos urgentes y exportaciones desde Zaragoza."},
    {"name": "Nacex", "country": "Spain", "categories": ["carrier_last_mile"], "rate_per_shipment": 4.60, "currency": "EUR", "status": "active", "service_zone": "Aragón y zona norte", "contact_email": "empresas@nacex.es", "notes": "Carrier regional con buena cobertura en Aragón."},
    {"name": "Logística Inversa Iberia", "country": "Spain", "categories": ["reverse_logistics"], "rate_per_shipment": 6.30, "currency": "EUR", "status": "active", "contact_email": "operaciones@liiberia.es", "notes": "Gestión de devoluciones para el almacén de Zaragoza."},
    {"name": "Embalajes Zaragoza S.L.", "country": "Spain", "categories": ["packaging_materials"], "rate_per_shipment": 0.28, "currency": "EUR", "status": "active", "contact_email": "pedidos@embalajeszgz.es"},
    {"name": "SAP WM Cloud", "country": "USA", "categories": ["it_and_wms_software"], "rate_per_shipment": 2200.0, "currency": "USD", "status": "suspended", "contact_email": "enterprise@sap.com", "notes": "Suspendido. Andrés está evaluando alternativas más ligeras para el almacén de LA."},
    {"name": "ReturnBear", "country": "USA", "categories": ["reverse_logistics"], "rate_per_shipment": 4.15, "currency": "USD", "status": "active", "service_zone": "West Coast", "contact_email": "partnerships@returnbear.com", "notes": "Gestión de devoluciones para clientes de Los Ángeles."},
]


def _validated_suppliers() -> list[SupplierCreate] | None:
    """Valida todo el seed antes de tocar la base de datos."""
    suppliers: list[SupplierCreate] = []
    invalid = False
    for raw_supplier in SUPPLIERS_SEED:
        try:
            suppliers.append(SupplierCreate.model_validate(raw_supplier))
        except ValidationError as error:
            invalid = True
            fields = ", ".join(
                str(item["loc"][-1]) if item.get("loc") else "registro"
                for item in error.errors()
            )
            print(
                f"Error: el proveedor '{raw_supplier.get('name', '(sin nombre)')}' "
                f"del seed no es válido (campos: {fields}).",
                file=sys.stderr,
            )
    return None if invalid else suppliers


def main() -> int:
    suppliers = _validated_suppliers()
    if suppliers is None:
        print("No se ha insertado ningún proveedor. Corrige el seed y vuelve a ejecutarlo.", file=sys.stderr)
        return 1

    try:
        db = get_suppliers_db()
        existing = {(document["name"], document["country"]) for document in db.all()}
    except OSError as error:
        print(f"Error: no se pudo abrir la base de datos de proveedores ({error.strerror}).", file=sys.stderr)
        return 1
    except ValueError:
        print(
            "Error: la base de datos de proveedores está dañada (JSON no válido). "
            "Restáurala o elimínala antes de volver a ejecutar el seed.",
            file=sys.stderr,
        )
        return 1

    inserted = 0
    with db:
        for supplier in suppliers:
            identity = (supplier.name, supplier.country)
            if identity in existing:
                continue
            try:
                db.insert({
                    **supplier.model_dump(),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
            except OSError as error:
                print(
                    f"Error: no se pudo guardar '{supplier.name}' ({error.strerror}). "
                    f"Proveedores insertados antes del fallo: {inserted}.",
                    file=sys.stderr,
                )
                return 1
            existing.add(identity)
            inserted += 1
    print(f"Proveedores insertados: {inserted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
