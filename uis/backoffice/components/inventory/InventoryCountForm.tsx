"use client";

import { type FormEvent, useState } from "react";
import { CircleCheck, PackageMinus, PackagePlus, TriangleAlert } from "lucide-react";
import { getUserMessage } from "@/lib/api-client";
import {
  createInventoryCount,
  detectionMethodLabels,
  formatUnits,
  parseCountedQuantity,
  validateInventoryCount,
  warehouseLabels,
  type DetectionMethod,
  type FormErrors,
  type InventoryCount,
  type InventoryCountFormValues,
  type SKUListItem,
} from "@/lib/inventory";
import { FormField, controlClasses } from "@/components/inventory/FormField";
import { InventoryLinkButton } from "@/components/inventory/InventoryLinkButton";
import { InventoryPageHeader } from "@/components/inventory/InventoryPageHeader";
import { RetryAlert } from "@/components/inventory/RetryAlert";
import { useSkuCatalog } from "@/components/inventory/useSkuCatalog";

interface InventoryCountFormProps {
  /** SKU preseleccionado (`?sku=<id>`). */
  initialSkuId: string;
}

interface CountResult {
  count: InventoryCount;
  sku: SKUListItem;
}

const detectionMethods = Object.keys(detectionMethodLabels) as DetectionMethod[];
const emptyValues: InventoryCountFormValues = {
  skuId: "",
  countedQuantity: "",
  detectionMethod: "cycle_count",
};

/**
 * Conteo físico: compara lo que hay en la estantería con el stock calculado.
 * No cambia el stock; si hay descuadre, la API lo registra
 * (`inventory_discrepancy_detected`) y el operador lo corrige con una entrada
 * o una salida de tipo pérdida, trazables como cualquier movimiento.
 */
export function InventoryCountForm({ initialSkuId }: InventoryCountFormProps) {
  const catalog = useSkuCatalog();
  const [values, setValues] = useState<InventoryCountFormValues>({ ...emptyValues, skuId: initialSkuId });
  const [errors, setErrors] = useState<FormErrors<InventoryCountFormValues>>({});
  const [submitError, setSubmitError] = useState("");
  const [result, setResult] = useState<CountResult | null>(null);
  const [saving, setSaving] = useState(false);

  const selectedSku = catalog.skus.find((sku) => String(sku.id) === values.skuId) ?? null;
  const skuValue = catalog.loading || selectedSku ? values.skuId : "";

  function update(field: keyof InventoryCountFormValues, value: string) {
    setValues((current) => ({ ...current, [field]: value }));
    setErrors((current) => ({ ...current, [field]: undefined }));
    setResult(null);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitError("");
    setResult(null);
    const validation = validateInventoryCount({ ...values, skuId: skuValue });
    const counted = parseCountedQuantity(values.countedQuantity);
    if (Object.keys(validation).length > 0 || !selectedSku || counted === null) {
      setErrors(validation);
      return;
    }
    setSaving(true);
    try {
      const count = await createInventoryCount({
        sku_id: selectedSku.id,
        warehouse: selectedSku.warehouse,
        counted_quantity: counted,
        detection_method: values.detectionMethod,
      });
      setResult({ count, sku: selectedSku });
      setValues({ ...emptyValues, detectionMethod: values.detectionMethod });
      setErrors({});
    } catch (error) {
      setSubmitError(getUserMessage(error, "No se pudo registrar el conteo físico. Inténtalo de nuevo."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <InventoryPageHeader
        title="Conteo físico"
        description="Compara las unidades contadas en la estantería con el stock que calcula el sistema. El conteo no cambia el stock: un descuadre se corrige después con una entrada o una salida."
        actions={
          <InventoryLinkButton href="/inventory/products">Ver stock por SKU</InventoryLinkButton>
        }
      />

      {result ? <CountResultPanel result={result} /> : null}

      <section
        aria-labelledby="inventory-count-title"
        className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6"
      >
        <h2 id="inventory-count-title" className="text-lg font-semibold text-slate-900">
          Datos del conteo
        </h2>

        {catalog.error ? (
          <div className="mt-5">
            <RetryAlert message={catalog.error} onRetry={catalog.retry} />
          </div>
        ) : (
          <form noValidate onSubmit={handleSubmit} className="mt-5 space-y-5">
            <FormField
              id="count-sku"
              label="SKU contado"
              error={errors.skuId}
              hint={
                selectedSku
                  ? `Cliente: ${selectedSku.client_name} · Almacén: ${warehouseLabels[selectedSku.warehouse]}`
                  : undefined
              }
            >
              {(describedBy) => (
                <select
                  id="count-sku"
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
                  {catalog.options}
                </select>
              )}
            </FormField>

            <div className="grid gap-5 sm:grid-cols-2">
              <FormField
                id="count-quantity"
                label="Unidades contadas"
                hint="Lo que hay físicamente; 0 si no queda ninguna."
                error={errors.countedQuantity}
              >
                {(describedBy) => (
                  <input
                    id="count-quantity"
                    type="number"
                    inputMode="numeric"
                    min={0}
                    step={1}
                    value={values.countedQuantity}
                    onChange={(event) => update("countedQuantity", event.target.value)}
                    aria-invalid={Boolean(errors.countedQuantity)}
                    aria-describedby={describedBy}
                    className={controlClasses(Boolean(errors.countedQuantity))}
                  />
                )}
              </FormField>

              <FormField id="count-method" label="Tipo de conteo">
                {(describedBy) => (
                  <select
                    id="count-method"
                    value={values.detectionMethod}
                    onChange={(event) => update("detectionMethod", event.target.value)}
                    aria-describedby={describedBy}
                    className={controlClasses(false)}
                  >
                    {detectionMethods.map((method) => (
                      <option key={method} value={method}>
                        {detectionMethodLabels[method]}
                      </option>
                    ))}
                  </select>
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
              {saving ? "Registrando..." : "Registrar conteo"}
            </button>
          </form>
        )}
      </section>
    </div>
  );
}

function CountResultPanel({ result }: { result: CountResult }) {
  const { count, sku } = result;
  const summary = `${sku.sku} en ${warehouseLabels[count.warehouse]}: contadas ${formatUnits(count.counted_quantity)} uds., el sistema calculaba ${formatUnits(count.system_quantity)}.`;

  if (count.difference === 0) {
    return (
      <p
        role="status"
        className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900"
      >
        <CircleCheck aria-hidden="true" className="h-4 w-4 shrink-0" />
        Sin descuadre. {summary}
      </p>
    );
  }

  const missing = count.difference < 0;
  return (
    <div role="status" className="space-y-3 rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900">
      <p className="flex items-start gap-2">
        <TriangleAlert aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />
        <span>
          <span className="font-semibold">
            Descuadre de {missing ? "−" : "+"}
            {formatUnits(Math.abs(count.difference))} uds.
          </span>{" "}
          {summary}{" "}
          {missing
            ? "Si se confirma la falta, regístrala como salida de tipo pérdida."
            : "Si sobra mercancía, registra la recepción pendiente como entrada."}
        </span>
      </p>
      <InventoryLinkButton
        href={`/inventory/orders/${missing ? "outbound" : "inbound"}?sku=${sku.id}`}
        size="sm"
      >
        {missing ? (
          <PackageMinus aria-hidden="true" className="h-3.5 w-3.5" />
        ) : (
          <PackagePlus aria-hidden="true" className="h-3.5 w-3.5" />
        )}
        {missing ? "Registrar pérdida" : "Registrar entrada"}
      </InventoryLinkButton>
    </div>
  );
}
