from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


class Country(str, Enum):
    USA = "USA"
    SPAIN = "Spain"


class Currency(str, Enum):
    USD = "USD"
    EUR = "EUR"


class SupplierCategory(str, Enum):
    CARRIER_LAST_MILE = "carrier_last_mile"
    CARRIER_INTERNATIONAL = "carrier_international"
    WAREHOUSE_SUPPLIES = "warehouse_supplies"
    PACKAGING_MATERIALS = "packaging_materials"
    REVERSE_LOGISTICS = "reverse_logistics"
    FLEET_MAINTENANCE = "fleet_maintenance"
    IT_AND_WMS_SOFTWARE = "it_and_wms_software"
    CLEANING_AND_FACILITIES = "cleaning_and_facilities"


class SupplierStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class SupplierFields(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    name: str = Field(min_length=1)
    country: Country
    categories: list[SupplierCategory] = Field(min_length=1)
    rate_per_shipment: float = Field(gt=0)
    currency: Currency
    status: SupplierStatus
    service_zone: str | None = None
    contact_email: EmailStr | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def validate_currency_for_country(self) -> "SupplierFields":
        expected_currency = Currency.USD if self.country == Country.USA else Currency.EUR
        if self.currency != expected_currency:
            raise ValueError(
                f"Los proveedores de {self.country} deben usar {expected_currency}"
            )
        return self


class SupplierCreate(SupplierFields):
    pass


class Supplier(SupplierFields):
    id: int
    updated_at: datetime


class RateUpdate(BaseModel):
    rate_per_shipment: float = Field(gt=0)


class StatusUpdate(BaseModel):
    status: SupplierStatus