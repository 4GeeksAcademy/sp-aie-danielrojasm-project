import {
  Carrier,
  Product,
  ProductCategory,
  WarehouseLocation,
} from "../types/models";

export function filterProductsByWarehouse(
  products: Product[],
  warehouse: WarehouseLocation,
): Product[] {
  return products.filter((product) => product.warehouse === warehouse);
}

export function filterProductsByCategory(
  products: Product[],
  category: ProductCategory,
): Product[] {
  return products.filter((product) => product.category === category);
}

export function filterLowStockProducts(products: Product[]): Product[] {
  return products.filter(
    (product) => product.stockQuantity <= product.minStockThreshold,
  );
}

export function sortProductsByStock(
  products: Product[],
  order: "asc" | "desc",
): Product[] {
  const sortedProducts = [...products].sort(
    (a, b) => a.stockQuantity - b.stockQuantity,
  );

  return order === "desc" ? sortedProducts.reverse() : sortedProducts;
}

export function sortCarriersByReliability(
  carriers: Carrier[],
  order: "asc" | "desc",
): Carrier[] {
  const sortedCarriers = [...carriers].sort(
    (a, b) => a.onTimeRate - b.onTimeRate,
  );

  return order === "desc" ? sortedCarriers.reverse() : sortedCarriers;
}