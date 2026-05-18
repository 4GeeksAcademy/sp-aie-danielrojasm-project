import { Carrier, Product, Shipment } from "../types/models";

type ValidationResult = {
	valid: boolean;
	errors: string[];
};

export function validateProduct(product: Product): ValidationResult {
	const errors: string[] = [];

	if (!product.sku || product.sku.trim() === "") {
		errors.push("SKU is required.");
	}

	if (product.weightKg <= 0 || product.weightKg > 100) {
		errors.push("weightKg must be greater than 0 and less than or equal to 100.");
	}

	if (
		product.dimensions.lengthCm <= 0 ||
		product.dimensions.lengthCm > 200 ||
		product.dimensions.widthCm <= 0 ||
		product.dimensions.widthCm > 200 ||
		product.dimensions.heightCm <= 0 ||
		product.dimensions.heightCm > 200
	) {
		errors.push("All dimensions must be greater than 0 and less than or equal to 200.");
	}

	if (product.stockQuantity < 0) {
		errors.push("stockQuantity must be greater than or equal to 0.");
	}

	if (product.minStockThreshold < 0) {
		errors.push("minStockThreshold must be greater than or equal to 0.");
	}

	if (product.unitCostUSD <= 0) {
		errors.push("unitCostUSD must be greater than 0.");
	}

	return {
		valid: errors.length === 0,
		errors,
	};
}

export function validateShipment(shipment: Shipment): ValidationResult {
	const errors: string[] = [];

	if (shipment.quantity <= 0) {
		errors.push("quantity must be greater than 0.");
	}

	if (shipment.declaredValueUSD <= 0) {
		errors.push("declaredValueUSD must be greater than 0.");
	}

	if (shipment.destination.distanceKm < 0) {
		errors.push("distanceKm must be greater than or equal to 0.");
	}

	return {
		valid: errors.length === 0,
		errors,
	};
}

export function validateCarrier(carrier: Carrier): ValidationResult {
	const errors: string[] = [];

	if (carrier.baseRateUSD < 0) {
		errors.push("baseRateUSD must be greater than or equal to 0.");
	}

	if (carrier.ratePerKgUSD < 0) {
		errors.push("ratePerKgUSD must be greater than or equal to 0.");
	}

	if (carrier.ratePerKmUSD < 0) {
		errors.push("ratePerKmUSD must be greater than or equal to 0.");
	}

	if (carrier.avgDeliveryDays <= 0) {
		errors.push("avgDeliveryDays must be greater than 0.");
	}

	if (carrier.onTimeRate < 0 || carrier.onTimeRate > 100) {
		errors.push("onTimeRate must be between 0 and 100.");
	}

	if (carrier.maxWeightKg <= 0) {
		errors.push("maxWeightKg must be greater than 0.");
	}

	if (carrier.operatesIn.length === 0) {
		errors.push("operatesIn must contain at least one country.");
	}

	return {
		valid: errors.length === 0,
		errors,
	};
}
