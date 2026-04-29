function filterProductsByWarehouse(products: Product[], warehouse: WarehouseLocation): Product[] {
  return products.filter(product => product.warehouse === warehouse);
}

function filterProductsByCategory(products: Product[], category: ProductCategory): Product[] {
  return products.filter(product => product.category === category);
}

function filterLowStockProducts(products: Product[]): Product[] {
  return products.filter(product => product.stockQuantity <= product.minStockThreshold);
}

function sortProductsByStock(products: Product[], order: "asc" | "desc"): Product[] {
  const sortedProducts = [...products].sort((a, b) => a.stockQuantity - b.stockQuantity);
  return order === "desc" ? sortedProducts.reverse() : sortedProducts;
}