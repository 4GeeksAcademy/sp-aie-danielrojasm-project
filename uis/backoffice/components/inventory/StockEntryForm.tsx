"use client";

import { type FormEvent, useState } from "react";
import { CircleCheck, History } from "lucide-react";
import { getUserMessage } from "@/lib/api-client";
import {
  REFERENCE_MAX_LENGTH,
  createStockEntry,
  formatSKUOption,
  formatUnits,
  parseQuantity,
  validateStockEntry,
  warehouseLabels,
  type FormErrors,
  type StockEntryFormValues,
} from "@/lib/inventory";
import { FormField, controlClasses } from "@/components/inventory/FormField";
import { InventoryLinkButton } from "@/components/inventory/InventoryLinkButton";
import { InventoryPageHeader } from "@/components/inventory/InventoryPageHeader";
import { RetryAlert } from "@/components/inventory/RetryAlert";
import { useSkuCatalog } from "@/components/inventory/useSkuCatalog";

interface StockEntryFormProps {
  /** SKU preseleccionado desde la tabla de stock (`?sku=<id>`). */
  initialSkuId: string;
}

const emptyValues: StockEntryFormValues = { skuId: "", quantity: "", reference: "" };

export function StockEntryForm({ initialSkuId }: StockEntryFormProps) {
  const catalog = useSkuCatalog();
  const [values, setValues] = useState<StockEntryFormValues>({ ...emptyValues, skuId: initialSkuId });
  const [errors, setErrors] = useState<FormErrors<StockEntryFormValues>>({});
  const [submitError, setSubmitError] = useState("");
  const [notice, setNotice] = useState("");
  const [saving, setSaving] = useState(false);

  // Un `?sku=` que no existe no deja el selector en un valor invisible.
  const selectedSku = catalog.skus.find((sku) => String(sku.id) === values.skuId) ?? null;
  const skuValue = catalog.loading || selectedSku ? values.skuId : "";

  function update(field: keyof StockEntryFormValues, value: string) {
    setValues((current) => ({ ...current, [field]: value }));
    setErrors((current) => ({ ...current, [field]: undefined }));
    setNotice("");
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitError("");
    setNotice("");
    const validation = validateStockEntry({ ...values, skuId: skuValue });
    const quantity = parseQuantity(values.quantity);
    if (Object.keys(validation).length > 0 || !selectedSku || quantity === null) {
      setErrors(validation);
      return;
    }
    setSaving(true);
    try {
      await createStockEntry({
        sku_id: selectedSku.id,
        quantity,
        reference: values.reference.trim(),
        warehouse: selectedSku.warehouse,
      });
      setValues(emptyValues);
      setErrors({});
      setNotice(
        `Entrada registrada: +${formatUnits(quantity)} uds. de ${selectedSku.sku} en ${warehouseLabels[selectedSku.warehouse]} (ref. ${values.reference.trim()}).`,
      );
    } catch (error) {
      setSubmitError(
        getUserMessage(error, "No se pudo registrar la entrada de stock. Inténtalo de nuevo."),
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <InventoryPageHeader
        title="Registrar entrada de stock"
        description="Recepción de mercancía de una marca cliente en un almacén de TrackFlow. Suma unidades al stock del SKU."
        actions={
          <InventoryLinkButton href="/inventory/products">Ver stock por SKU</InventoryLinkButton>
        }
      />

      {notice ? (
        <div
          role="status"
          className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900"
        >
          <p className="flex items-center gap-2">
            <CircleCheck aria-hidden="true" className="h-4 w-4 shrink-0" />
            {notice}
          </p>
          <InventoryLinkButton href="/inventory/orders" size="sm">
            <History aria-hidden="true" className="h-3.5 w-3.5" />
            Ver historial
          </InventoryLinkButton>
        </div>
      ) : null}

      <section
        aria-labelledby="stock-entry-title"
        className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6"
      >
        <h2 id="stock-entry-title" className="text-lg font-semibold text-slate-900">
          Datos de la recepción
        </h2>

        {catalog.error ? (
          <div className="mt-5">
            <RetryAlert message={catalog.error} onRetry={catalog.retry} />
          </div>
        ) : (
          <form noValidate onSubmit={handleSubmit} className="mt-5 space-y-5">
            <FormField
              id="entry-sku"
              label="SKU recibido"
              error={errors.skuId}
              hint={
                selectedSku
                  ? `Cliente: ${selectedSku.client_name} · Almacén receptor: ${warehouseLabels[selectedSku.warehouse]}`
                  : undefined
              }
            >
              {(describedBy) => (
                <select
                  id="entry-sku"
                  value={skuValue}
                  disabled={catalog.loading}
                  onChange={(event) => update("skuId", event.target.value)}
                  aria-invalid={Boolean(errors.skuId)}
                  aria-describedby={describedBy}
                  className={controlClasses(Boolean(errors.skuId))}
                >
                  <option value="">
                    {catalog.loading ? "Cargando SKUs..." : "Selecciona un SKU"}
                  </option>
                  {catalog.skus.map((sku) => (
                    <option key={sku.id} value={sku.id}>
                      {formatSKUOption(sku)}
                    </option>
                  ))}
                </select>
              )}
            </FormField>

            <div className="grid gap-5 sm:grid-cols-2">
              <FormField id="entry-quantity" label="Unidades recibidas" error={errors.quantity}>
                {(describedBy) => (
                  <input
                    id="entry-quantity"
                    type="number"
                    inputMode="numeric"
                    min={1}
                    step={1}
                    value={values.quantity}
                    onChange={(event) => update("quantity", event.target.value)}
                    aria-invalid={Boolean(errors.quantity)}
                    aria-describedby={describedBy}
                    className={controlClasses(Boolean(errors.quantity))}
                  />
                )}
              </FormField>

              <FormField
                id="entry-reference"
                label="Referencia de la marca"
                hint="Orden de compra o albarán, p. ej. PO-2024-0098."
                error={errors.reference}
              >
                {(describedBy) => (
                  <input
                    id="entry-reference"
                    type="text"
                    maxLength={REFERENCE_MAX_LENGTH}
                    value={values.reference}
                    onChange={(event) => update("reference", event.target.value)}
                    aria-invalid={Boolean(errors.reference)}
                    aria-describedby={describedBy}
                    className={controlClasses(Boolean(errors.reference))}
                  />
                )}
              </FormField>
            </div>

            {submitError ? (
              <p
                role="alert"
                className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800"
              >
                {submitError}
              </p>
            ) : null}

            <button
              type="submit"
              disabled={saving || catalog.loading}
              className="h-11 w-full rounded-md bg-slate-950 px-5 text-sm font-semibold text-white hover:bg-slate-800 disabled:cursor-wait disabled:opacity-60 sm:w-auto"
            >
              {saving ? "Registrando..." : "Registrar entrada"}
            </button>
          </form>
        )}
      </section>
    </div>
  );
}
