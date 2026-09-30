"use client";

import { useMemo, useState } from "react";
import { ArrowDownToLine, ArrowUpFromLine } from "lucide-react";
import {
  exitTypeLabels,
  formatOrderDate,
  formatUnits,
  listInventoryOrders,
  orderTypeLabels,
  warehouseLabels,
  type InventoryOrder,
  type OrderType,
} from "@/lib/inventory";
import { useApiList } from "@/lib/use-api-list";
import { useAuth } from "@/components/auth/AuthProvider";
import { InventoryLinkButton } from "@/components/inventory/InventoryLinkButton";
import { InventoryPageHeader } from "@/components/inventory/InventoryPageHeader";
import { RetryAlert } from "@/components/inventory/RetryAlert";

type OrderTypeFilter = "all" | OrderType;

const orderTypes = Object.keys(orderTypeLabels) as OrderType[];

const orderTypeStyles: Record<OrderType, { badge: string; quantity: string; sign: string }> = {
  inbound: {
    badge: "bg-emerald-100 text-emerald-800 ring-emerald-200",
    quantity: "text-emerald-700",
    sign: "+",
  },
  outbound: {
    badge: "bg-orange-100 text-orange-800 ring-orange-200",
    quantity: "text-orange-700",
    sign: "−",
  },
};

const orderTypeIcons: Record<OrderType, typeof ArrowDownToLine> = {
  inbound: ArrowDownToLine,
  outbound: ArrowUpFromLine,
};

function orderDetail(order: InventoryOrder): string {
  if (order.order_type === "inbound") return `Ref. ${order.reference ?? "—"}`;
  const type = order.exit_type ? exitTypeLabels[order.exit_type] : "Salida";
  return order.tracking_number ? `${type} · ${order.tracking_number}` : type;
}

/** Historial de solo lectura: sin acciones de edición ni borrado. */
export function InventoryOrderHistory() {
  const { user } = useAuth();
  const { items: orders, loading, error: loadError, retry } = useApiList<InventoryOrder>(
    listInventoryOrders,
    "No se pudo cargar el historial de movimientos.",
  );
  const [typeFilter, setTypeFilter] = useState<OrderTypeFilter>("all");

  const visible = useMemo(
    () => (typeFilter === "all" ? orders : orders.filter((order) => order.order_type === typeFilter)),
    [orders, typeFilter],
  );
  const currentUserId = user?.id ?? null;

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <InventoryPageHeader
        title="Historial de movimientos"
        description="Todas las entradas y salidas de stock, con el SKU y el usuario que registró cada una. Es de solo lectura: un error se corrige con un movimiento nuevo."
        actions={<InventoryLinkButton href="/inventory/products">Ver stock por SKU</InventoryLinkButton>}
      />

      <section
        aria-labelledby="order-history-title"
        className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
      >
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h2 id="order-history-title" className="text-lg font-semibold text-slate-900">
              Movimientos de stock
            </h2>
            <p className="mt-1 text-sm text-slate-500" aria-live="polite">
              {loading
                ? "Cargando movimientos..."
                : loadError
                  ? "Sin datos"
                  : `${visible.length} movimientos, del más reciente al más antiguo`}
            </p>
          </div>
          <label htmlFor="order-type-filter" className="text-xs font-medium text-slate-600">
            Tipo
            <select
              id="order-type-filter"
              value={typeFilter}
              onChange={(event) => setTypeFilter(event.target.value as OrderTypeFilter)}
              className="mt-1 block rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
            >
              <option value="all">Todos</option>
              {orderTypes.map((type) => (
                <option key={type} value={type}>
                  {orderTypeLabels[type]}
                </option>
              ))}
            </select>
          </label>
        </div>

        {loading ? (
          <div aria-busy="true" className="mt-5 space-y-2">
            <p className="sr-only" role="status">
              Cargando movimientos...
            </p>
            {Array.from({ length: 6 }, (_, index) => (
              <div key={index} className="h-12 animate-pulse rounded-lg bg-slate-100" />
            ))}
          </div>
        ) : null}

        {!loading && loadError ? (
          <div className="mt-5">
            <RetryAlert message={loadError} onRetry={retry} />
          </div>
        ) : null}

        {!loading && !loadError ? (
          <div className="mt-5 overflow-x-auto">
            <table className="w-full min-w-[960px] text-left text-sm">
              <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th scope="col" className="px-3 py-3">Tipo</th>
                  <th scope="col" className="px-3 py-3">Fecha</th>
                  <th scope="col" className="px-3 py-3">SKU</th>
                  <th scope="col" className="px-3 py-3">Almacén</th>
                  <th scope="col" className="px-3 py-3 text-right">Unidades</th>
                  <th scope="col" className="px-3 py-3">Detalle</th>
                  <th scope="col" className="px-3 py-3">Registrado por (UUID)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {visible.map((order) => {
                  const styles = orderTypeStyles[order.order_type];
                  const Icon = orderTypeIcons[order.order_type];
                  return (
                    <tr key={`${order.order_type}-${order.id}`}>
                      <td className="px-3 py-3">
                        <span
                          className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset ${styles.badge}`}
                        >
                          <Icon aria-hidden="true" className="h-3.5 w-3.5" />
                          {orderTypeLabels[order.order_type]}
                        </span>
                      </td>
                      <td className="whitespace-nowrap px-3 py-3 text-slate-700">
                        <time dateTime={order.created_at}>{formatOrderDate(order.created_at)}</time>
                      </td>
                      <td className="px-3 py-3">
                        <p className="text-slate-900">{order.sku_name}</p>
                        <p className="mt-0.5 font-mono text-xs text-slate-500">
                          {order.sku_code} · {order.client_name}
                        </p>
                      </td>
                      <td className="whitespace-nowrap px-3 py-3 text-slate-700">
                        {warehouseLabels[order.warehouse]}
                      </td>
                      <td
                        className={`whitespace-nowrap px-3 py-3 text-right font-bold tabular-nums ${styles.quantity}`}
                      >
                        {styles.sign}
                        {formatUnits(order.quantity)}
                      </td>
                      <td className="px-3 py-3 text-slate-700">{orderDetail(order)}</td>
                      <td className="px-3 py-3">
                        <span className="font-mono text-xs text-slate-700">{order.user_uuid}</span>
                        {order.user_uuid === currentUserId ? (
                          <span className="ml-2 rounded bg-cyan-50 px-1.5 py-0.5 text-[11px] font-semibold text-cyan-800">
                            Tú
                          </span>
                        ) : null}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {visible.length === 0 ? (
              <p className="py-8 text-center text-sm text-slate-500">
                {orders.length === 0
                  ? "Todavía no hay movimientos de stock registrados."
                  : "No hay movimientos de este tipo."}
              </p>
            ) : null}
          </div>
        ) : null}
      </section>
    </div>
  );
}
