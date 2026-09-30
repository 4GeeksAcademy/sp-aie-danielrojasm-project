"""Schemas Pydantic de request y response del inventario.

Son independientes de los modelos ORM de `models.py`: ningún endpoint devuelve
una fila de SQLModel. Los schemas de entrada prohíben campos extra, así que no
hay forma de enviar `current_stock` ni `user_uuid` desde el cliente.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from services.api.models import DetectionMethod, ExitType, SKUCategory, Warehouse


def _text(max_length: int) -> StringConstraints:
    return StringConstraints(strip_whitespace=True, min_length=1, max_length=max_length)


SKUName = Annotated[str, _text(200)]
SKUCode = Annotated[str, _text(64)]
ClientName = Annotated[str, _text(120)]
Reference = Annotated[str, _text(100)]
TrackingNumber = Annotated[str, _text(64)]
Quantity = Annotated[int, Field(gt=0, description="Unidades; siempre positivas.")]


# ---------------------------------------------------------------------------
# SKU
# ---------------------------------------------------------------------------

class SKUCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: SKUName
    sku: SKUCode
    client_name: ClientName
    category: SKUCategory
    warehouse: Warehouse


class SKUListItem(BaseModel):
    """Fila de la tabla de stock y opción de los selectores de SKU.

    Solo el stock del almacén del SKU: el desglose por almacén queda en el
    detalle (`SKURead`), que es donde se consulta.
    """

    id: int
    name: str
    sku: str
    client_name: str
    category: SKUCategory
    warehouse: Warehouse
    current_stock: int = Field(
        description="Stock calculado (entradas − salidas) en el almacén del SKU."
    )


class SKURead(SKUListItem):
    """Detalle de un SKU: añade el stock desglosado por almacén."""

    stock_by_warehouse: dict[Warehouse, int] = Field(
        description="Stock calculado en cada almacén; nunca se suman entre sí."
    )


# ---------------------------------------------------------------------------
# Movimientos de stock
# ---------------------------------------------------------------------------

class StockEntryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku_id: int
    quantity: Quantity
    reference: Reference
    warehouse: Warehouse


class StockExitCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku_id: int
    quantity: Quantity
    exit_type: ExitType
    tracking_number: TrackingNumber | None = None
    warehouse: Warehouse

    @model_validator(mode="after")
    def tracking_number_matches_exit_type(self) -> "StockExitCreate":
        if self.exit_type == ExitType.DISPATCH and self.tracking_number is None:
            raise ValueError("Un despacho (dispatch) necesita tracking_number.")
        if self.exit_type == ExitType.LOSS and self.tracking_number is not None:
            raise ValueError("Una pérdida (loss) no lleva tracking_number.")
        return self


class StockEntryRead(BaseModel):
    id: int
    sku_id: int
    quantity: int
    reference: str
    warehouse: Warehouse
    created_at: datetime
    user_uuid: str


class StockExitRead(BaseModel):
    id: int
    sku_id: int
    quantity: int
    exit_type: ExitType
    tracking_number: str | None
    warehouse: Warehouse
    created_at: datetime
    user_uuid: str


class DirectStockEditRejected(BaseModel):
    """405 de las rutas que intentan editar el stock fuera de una orden."""

    detail: str


class InventoryOrderRead(BaseModel):
    """Un movimiento del historial, sea recepción o salida.

    El SKU va aplanado (`sku_code`, `sku_name`, `client_name`): el historial
    solo muestra esos tres datos, y su almacén ya es el del movimiento.
    """

    order_type: Literal["inbound", "outbound"]
    id: int
    sku_code: str
    sku_name: str
    client_name: str
    quantity: int
    warehouse: Warehouse
    created_at: datetime
    user_uuid: str
    reference: str | None = None
    exit_type: ExitType | None = None
    tracking_number: str | None = None


# ---------------------------------------------------------------------------
# Conteos físicos
# ---------------------------------------------------------------------------

class InventoryCountCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku_id: int
    warehouse: Warehouse
    counted_quantity: int = Field(ge=0, description="Unidades contadas; 0 si no queda ninguna.")
    detection_method: DetectionMethod


class InventoryCountRead(BaseModel):
    id: int
    sku_id: int
    warehouse: Warehouse
    counted_quantity: int
    system_quantity: int = Field(description="Stock calculado por el sistema al contar.")
    difference: int = Field(description="counted_quantity − system_quantity; negativo = falta mercancía.")
    detection_method: DetectionMethod
    created_at: datetime
    user_uuid: str
