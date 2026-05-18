import {
	Carrier,
	Product,
	ProductCategory,
	Shipment,
	ShipmentStatus,
} from "../types/models";

function roundToTwoDecimals(value: number): number {
	return Math.round(value * 100) / 100;
}

export function calculateShippingCost(
	shipment: Shipment,
	product: Product,
	carrier: Carrier,
): number {
	const baseCost = carrier.baseRateUSD;
	const weightCost =
		product.weightKg * carrier.ratePerKgUSD * shipment.quantity;
	const distanceCost = shipment.destination.distanceKm * carrier.ratePerKmUSD;

	const subtotal = baseCost + weightCost + distanceCost;

	const priorityMultiplier: Record<Shipment["priority"], number> = {
		Standard: 1,
		Express: 1.3,
		"Same-day": 1.6,
	};

	return roundToTwoDecimals(subtotal * priorityMultiplier[shipment.priority]);
}

export function scoreCarrierForShipment(
	carrier: Carrier,
	shipment: Shipment,
	product: Product,
): number {
	let score = 0;

	if (carrier.operatesIn.includes(shipment.destination.country)) {
		score += 20;
	}

	if (product.weightKg * shipment.quantity <= carrier.maxWeightKg) {
		score += 20;
	}

	if (carrier.acceptsPriority.includes(shipment.priority)) {
		score += 15;
	}

	if (!product.isFragile || carrier.handlesFragile) {
		score += 15;
	}

	score += carrier.onTimeRate * 0.3;

	return roundToTwoDecimals(score);
}

export function selectBestCarrier(
	carriers: Carrier[],
	shipment: Shipment,
	product: Product,
): { carrier: Carrier; score: number; cost: number } | null {
	let bestOption: { carrier: Carrier; score: number; cost: number } | null = null;

	for (const carrier of carriers) {
		const score = scoreCarrierForShipment(carrier, shipment, product);

		if (score < 50) {
			continue;
		}

		const cost = calculateShippingCost(shipment, product, carrier);

		if (
			bestOption === null ||
			cost < bestOption.cost ||
			(cost === bestOption.cost && score > bestOption.score)
		) {
			bestOption = { carrier, score, cost };
		}
	}

	return bestOption;
}

export function countProductsByCategory(
	products: Product[],
): Record<ProductCategory, number> {
	const counts: Record<ProductCategory, number> = {
		Fashion: 0,
		Electronics: 0,
		Cosmetics: 0,
		Home: 0,
		Other: 0,
	};

	for (const product of products) {
		counts[product.category] += 1;
	}

	return counts;
}

export function calculateTotalInventoryValue(products: Product[]): number {
	const totalValue = products.reduce(
		(acc, product) => acc + product.stockQuantity * product.unitCostUSD,
		0,
	);

	return roundToTwoDecimals(totalValue);
}

export function calculateAverageShipmentDistance(shipments: Shipment[]): number {
	if (shipments.length === 0) {
		return 0;
	}

	const totalDistance = shipments.reduce(
		(acc, shipment) => acc + shipment.destination.distanceKm,
		0,
	);

	return roundToTwoDecimals(totalDistance / shipments.length);
}

export function groupShipmentsByStatus(
	shipments: Shipment[],
): Record<ShipmentStatus, Shipment[]> {
	const grouped: Record<ShipmentStatus, Shipment[]> = {
		Pending: [],
		Assigned: [],
		"In transit": [],
		Delivered: [],
		Failed: [],
	};

	for (const shipment of shipments) {
		grouped[shipment.status].push(shipment);
	}

	return grouped;
}

export function findTopCarriers(
	shipments: Shipment[],
	topN: number,
): Array<{ carrier: string; count: number }> {
	if (topN <= 0) {
		return [];
	}

	const usage = new Map<string, number>();

	for (const shipment of shipments) {
		if (shipment.carrier === null) {
			continue;
		}

		usage.set(shipment.carrier, (usage.get(shipment.carrier) ?? 0) + 1);
	}

	return [...usage.entries()]
		.map(([carrier, count]) => ({ carrier, count }))
		.sort((a, b) => b.count - a.count)
		.slice(0, topN);
}
