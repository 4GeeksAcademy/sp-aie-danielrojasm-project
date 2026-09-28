from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from services.api.database import get_db
from services.api.models import (
    Country,
    RateUpdate,
    StatusUpdate,
    Supplier,
    SupplierCategory,
    SupplierCreate,
)
from services.api.security import get_current_user


router = APIRouter(
    prefix="/suppliers",
    tags=["suppliers"],
    dependencies=[Depends(get_current_user)],
)


def supplier_from_document(document: Any) -> Supplier:
    return Supplier(id=int(document.doc_id), **dict(document))


@router.post("", response_model=Supplier, status_code=status.HTTP_201_CREATED)
def create_supplier(payload: SupplierCreate) -> Supplier:
    with get_db() as db:
        document_id = db.insert(
            {
                **payload.model_dump(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        document = db.get(doc_id=document_id)
    return supplier_from_document(document)


@router.get("", response_model=list[Supplier])
def list_suppliers(
    country: Country | None = None,
    category: SupplierCategory | None = Query(default=None),
) -> list[Supplier]:
    with get_db() as db:
        documents = db.all()
    suppliers = [supplier_from_document(document) for document in documents]
    if country is not None:
        suppliers = [supplier for supplier in suppliers if supplier.country == country]
    if category is not None:
        suppliers = [
            supplier for supplier in suppliers if category in supplier.categories
        ]
    return suppliers


@router.get("/{supplier_id}", response_model=Supplier)
def get_supplier(supplier_id: int) -> Supplier:
    with get_db() as db:
        document = db.get(doc_id=supplier_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")
    return supplier_from_document(document)


@router.patch("/{supplier_id}/rate", response_model=Supplier)
def update_supplier_rate(supplier_id: int, payload: RateUpdate) -> Supplier:
    return _update_supplier(
        supplier_id,
        {
            "rate_per_shipment": payload.rate_per_shipment,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )


@router.patch("/{supplier_id}/status", response_model=Supplier)
def update_supplier_status(supplier_id: int, payload: StatusUpdate) -> Supplier:
    return _update_supplier(supplier_id, {"status": payload.status})


def _update_supplier(supplier_id: int, updates: dict[str, object]) -> Supplier:
    with get_db() as db:
        if db.get(doc_id=supplier_id) is None:
            raise HTTPException(status_code=404, detail="Proveedor no encontrado")
        db.update(updates, doc_ids=[supplier_id])
        document = db.get(doc_id=supplier_id)
    return supplier_from_document(document)


@router.delete("/{supplier_id}")
def delete_supplier(supplier_id: int) -> dict[str, str]:
    with get_db() as db:
        if db.get(doc_id=supplier_id) is None:
            raise HTTPException(status_code=404, detail="Proveedor no encontrado")
        db.remove(doc_ids=[supplier_id])
    return {"message": "Proveedor eliminado"}