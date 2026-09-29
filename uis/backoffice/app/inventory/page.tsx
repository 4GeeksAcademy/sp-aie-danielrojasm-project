import { redirect } from "next/navigation";

/** `/inventory` no tiene vista propia: la entrada natural es el stock por SKU. */
export default function InventoryPage() {
  redirect("/inventory/products");
}
