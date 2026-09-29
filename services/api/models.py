"""Modelos ORM del inventario (tablas de Supabase).

El stock no es una columna: se deriva siempre de `StockEntry` − `StockExit`
por SKU y almacén (ver `routes/inventory.py`). Los usuarios viven en TinyDB,
así que `user_uuid` es una cadena sin clave foránea.
"""

from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import CheckConstraint, Column, DateTime
from sqlmodel import Field, Relationship, SQLModel


class Warehouse(str, Enum):
    LA = "LA"
    ZGZ = "ZGZ"


class SKUCategory(str, Enum):
    FASHION = "fashion"
    ELECTRONICS = "electronics"
    COSMETICS = "cosmetics"


class ExitType(str, Enum):
    DISPATCH = "dispatch"
    LOSS = "loss"


def _one_of(column: str, values: type[Enum]) -> str:
    allowed = ", ".join(f"'{value.value}'" for value in values)
    return f"{column} IN ({allowed})"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _created_at_column() -> Column:
    return Column(DateTime(timezone=True), nullable=False)


class SKU(SQLModel, table=True):
    __tablename__ = "skus"
    __table_args__ = (
        CheckConstraint(_one_of("category", SKUCategory), name="ck_skus_category"),
        CheckConstraint(_one_of("warehouse", Warehouse), name="ck_skus_warehouse"),
    )

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=200)
    # Código del cliente; único en toda la red (cada almacén usa su propio código).
    sku: str = Field(max_length=64, unique=True, index=True)
    client_name: str = Field(max_length=120)
    category: str = Field(max_length=20)
    warehouse: str = Field(max_length=3, index=True)

    entries: list["StockEntry"] = Relationship(back_populates="sku")
    exits: list["StockExit"] = Relationship(back_populates="sku")


class StockEntry(SQLModel, table=True):
    """Recepción de mercancía de una marca cliente."""

    __tablename__ = "stock_entries"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_stock_entries_quantity"),
        CheckConstraint(_one_of("warehouse", Warehouse), name="ck_stock_entries_warehouse"),
    )

    id: int | None = Field(default=None, primary_key=True)
    sku_id: int = Field(foreign_key="skus.id", index=True, ondelete="RESTRICT")
    quantity: int
    reference: str = Field(max_length=100)
    warehouse: str = Field(max_length=3)
    created_at: datetime = Field(default_factory=_utc_now, sa_column=_created_at_column())
    user_uuid: str = Field(max_length=36, index=True)

    sku: SKU = Relationship(back_populates="entries")


class StockExit(SQLModel, table=True):
    """Despacho a cliente final o baja por pérdida."""

    __tablename__ = "stock_exits"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_stock_exits_quantity"),
        CheckConstraint(_one_of("warehouse", Warehouse), name="ck_stock_exits_warehouse"),
        CheckConstraint(_one_of("exit_type", ExitType), name="ck_stock_exits_exit_type"),
        # Un despacho lleva número de seguimiento; una pérdida, no.
        CheckConstraint(
            "(exit_type = 'dispatch' AND tracking_number IS NOT NULL)"
            " OR (exit_type = 'loss' AND tracking_number IS NULL)",
            name="ck_stock_exits_tracking_number",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    sku_id: int = Field(foreign_key="skus.id", index=True, ondelete="RESTRICT")
    quantity: int
    exit_type: str = Field(max_length=10)
    tracking_number: str | None = Field(default=None, max_length=64)
    warehouse: str = Field(max_length=3)
    created_at: datetime = Field(default_factory=_utc_now, sa_column=_created_at_column())
    user_uuid: str = Field(max_length=36, index=True)

    sku: SKU = Relationship(back_populates="exits")
