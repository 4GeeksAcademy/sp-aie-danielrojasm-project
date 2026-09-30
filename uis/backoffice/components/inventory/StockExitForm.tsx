"use client";

import { type FormEvent, useEffect, useState } from "react";
import { CircleCheck, History, TriangleAlert } from "lucide-react";
import { ApiError, getUserMessage } from "@/lib/api-client";
import {
  TRACKING_NUMBER_MAX_LENGTH,
  createStockExit,
  exitTypeLabels,
  formatUnits,
  getOverdraftWarning,
  getSKU,
  parseQuantity,
  validateStockExit,
  warehouseLabels,
  type ExitType,
  type FormErrors,
  type StockExitFormValues,
} from "@/lib/inventory";
import { FormField, controlClasses, fieldErrorId } from "@/components/inventory/FormField";
import { InventoryLinkButton } from "@/components/inventory/InventoryLinkButton";
import { InventoryPageHeader } from "@/components/inventory/InventoryPageHeader";
import { RetryAlert } from "@/components/inventory/RetryAlert";
import { StockLevelBadge } from "@/components/inventory/StockLevelBadge";
import { useSkuCatalog } from "@/components/inventory/useSkuCatalog";

interface StockExitFormProps {
  /** SKU preseleccionado desde la tabla de stock (`?sku=<id>`). */
  initialSkuId: string;
}

/** Resultado de la última consulta de stock; `key` = SKU + intento. */
interface StockLookup {
  key: string;
  available: number | null;
  error: string;
}

const exitTypes = Object.keys(exitTypeLabels) as ExitType[];
const emptyValues: StockExitFormValues = {
  skuId: "",
  quantity: "",
  exitType: "dispatch",
  trackingNumber: "",
};

export function StockExitForm({ initialSkuId }: StockExitFormProps) {
  const catalog = useSkuCatalog();
  const [values, setValues] = useState<StockExitFormValues>({ ...emptyValues, skuId: initialSkuId });
  const [errors, setErrors] = useState<FormErrors<StockExitFormValues>>({});
  const [quantityApiError, setQuantityApiError] = useState("");
  const [submitError, setSubmitError] = useState("");
  const [notice, setNotice] = useState("");
  const [saving, setSaving] = useState(false);
  const [stockLookup, setStockLookup] = useState<StockLookup>({ key: "", available: null, error: "" });
  const [stockAttempt, setStockAttempt] = useState(0);

  const selectedSku = catalog.skus.find((sku) => String(sku.id) === values.skuId) ?? null;
  const skuValue = catalog.loading || selectedSku ? values.skuId : "";
  const lookupKey = skuValue ? `${skuValue}:${stockAttempt}` : "";

  // El stock se pide a la API cada vez que cambia el SKU (y tras cada envío),
  // para mostrar la cifra real antes de escribir la cantidad.
  useEffect(() => {
    if (!lookupKey) return;
    let active = true;
    const load = async () => {
      try {
        const sku = await getSKU(Number(skuValue));
        if (active) setStockLookup({ key: lookupKey, available: sku.current_stock, error: "" });
      } catch (error) {
        if (active) {
          setStockLookup({
            key: lookupKey,
            available: null,
            error: getUserMessage(error, "No se pudo consultar el stock disponible."),
          });
        }
      }
    };
    void load();
    return () => {
      active = false;
    };
  }, [lookupKey, skuValue]);

  const stockReady = lookupKey !== "" && stockLookup.key === lookupKey;
  const available = stockReady ? stockLookup.available : null;
  const stockError = stockReady ? stockLookup.error : "";
  const overdraftWarning = getOverdraftWarning(values.quantity, available);

  function update(field: keyof StockExitFormValues, value: string) {
    setValues((current) => ({
      ...current,
      [field]: value,
      // Una pérdida no lleva número de seguimiento.
      ...(field === "exitType" && value === "loss" ? { trackingNumber: "" } : {}),
    }));
    setErrors((current) => ({ ...current, [field]: undefined }));
    if (field === "quantity" || field === "skuId") setQuantityApiError("");
    setNotice("");
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitError("");
    setQuantityApiError("");
    setNotice("");
    const validation = validateStockExit({ ...values, skuId: skuValue });
    const quantity = parseQuantity(values.quantity);
    if (Object.keys(validation).length > 0 || !selectedSku || quantity === null) {
      setErrors(validation);
      return;
    }
    // El aviso de stock no bloquea: la API aplica la regla y responde 400.
    setSaving(true);
    try {
      await createStockExit({
        sku_id: selectedSku.id,
        quantity,
        exit_type: values.exitType,
        tracking_number: values.exitType === "dispatch" ? values.trackingNumber.trim() : null,
        warehouse: selectedSku.warehouse,
      });
      // Se mantiene el SKU para ver al momento el stock que queda.
      setValues({ ...emptyValues, skuId: values.skuId });
      setErrors({});
      setNotice(
        `Salida registrada (${exitTypeLabels[values.exitType].toLowerCase()}): −${formatUnits(quantity)} uds. de ${selectedSku.sku} en ${warehouseLabels[selectedSku.warehouse]}.`,
      );
    } catch (error) {
      const message = getUserMessage(
        error,
        "No se pudo registrar la salida de stock. Inténtalo de nuevo.",
      );
      // 400 = stock insuficiente: se muestra junto a la cantidad.
      if (error instanceof ApiError && error.status === 400) setQuantityApiError(message);
      else setSubmitError(message);
    } finally {
      setSaving(false);
      setStockAttempt((value) => value + 1);
    }
  }

  const quantityDescribedBy = (describedBy: string | undefined) =>
    [describedBy, quantityApiError ? fieldErrorId("exit-quantity-api") : null, overdraftWarning ? "exit-overdraft" : null]
      .filter(Boolean)
      .join(" ") || undefined;

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <InventoryPageHeader
        title="Registrar salida de stock"
        description="Despacho a cliente final o pérdida confirmada. Resta unidades del stock del SKU en su almacén."
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
        aria-labelledby="stock-exit-title"
        className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6"
      >
        <h2 id="stock-exit-title" className="text-lg font-semibold text-slate-900">
          Datos de la salida
        </h2>

        {catalog.error ? (
          <div className="mt-5">
            <RetryAlert message={catalog.error} onRetry={catalog.retry} />
          </div>
        ) : (
          <form noValidate onSubmit={handleSubmit} className="mt-5 space-y-5">
            <FormField
              id="exit-sku"
              label="SKU"
              error={errors.skuId}
              hint={
                selectedSku
                  ? `Cliente: ${selectedSku.client_name} · Almacén: ${warehouseLabels[selectedSku.warehouse]}`
                  : undefined
              }
            >
              {(describedBy) => (
                <select
                  id="exit-sku"
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

            <div
              aria-live="polite"
              className="rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm"
            >
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Stock disponible
              </p>
              <div className="mt-2">
                {!skuValue ? (
                  <p className="text-slate-500">Selecciona un SKU para ver su stock disponible.</p>
                ) : !stockReady ? (
                  <p className="text-slate-600" role="status">
                    Consultando stock...
                  </p>
                ) : stockError ? (
                  <div role="alert" className="flex flex-wrap items-center gap-3 text-rose-800">
                    <span>{stockError}</span>
                    <button
                      type="button"
                      onClick={() => setStockAttempt((value) => value + 1)}
                      className="rounded-md border border-rose-300 bg-white px-3 py-1 text-xs font-semibold hover:bg-rose-100"
                    >
                      Reintentar
                    </button>
                  </div>
                ) : available !== null && selectedSku ? (
                  <p className="flex flex-wrap items-center gap-2 text-slate-700">
                    <StockLevelBadge stock={available} />
                    <span>uds. en {warehouseLabels[selectedSku.warehouse]}</span>
                  </p>
                ) : null}
              </div>
            </div>

            <div className="grid gap-5 sm:grid-cols-2">
              <FormField id="exit-type" label="Tipo de salida">
                {(describedBy) => (
                  <select
                    id="exit-type"
                    value={values.exitType}
                    onChange={(event) => update("exitType", event.target.value)}
                    aria-describedby={describedBy}
                    className={controlClasses(false)}
                  >
                    {exitTypes.map((type) => (
                      <option key={type} value={type}>
                        {exitTypeLabels[type]}
                      </option>
                    ))}
                  </select>
                )}
              </FormField>

              <FormField id="exit-quantity" label="Unidades" error={errors.quantity}>
                {(describedBy) => (
                  <input
                    id="exit-quantity"
                    type="number"
                    inputMode="numeric"
                    min={1}
                    step={1}
                    max={available ?? undefined}
                    value={values.quantity}
                    onChange={(event) => update("quantity", event.target.value)}
                    aria-invalid={Boolean(errors.quantity || quantityApiError)}
                    aria-describedby={quantityDescribedBy(describedBy)}
                    className={controlClasses(Boolean(errors.quantity || quantityApiError))}
                  />
                )}
              </FormField>
            </div>

            {overdraftWarning ? (
              <p
                id="exit-overdraft"
                role="alert"
                className="flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900"
              >
                <TriangleAlert aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />
                <span>
                  {overdraftWarning} Revisa la cantidad: la salida será rechazada si supera el stock.
                </span>
              </p>
            ) : null}

            {quantityApiError ? (
              <p
                id={fieldErrorId("exit-quantity-api")}
                role="alert"
                className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800"
              >
                <span className="font-semibold">Salida rechazada por stock insuficiente.</span>{" "}
                {quantityApiError}
              </p>
            ) : null}

            {values.exitType === "dispatch" ? (
              <FormField
                id="exit-tracking"
                label="Número de seguimiento"
                hint="El del transportista que recoge el envío."
                error={errors.trackingNumber}
              >
                {(describedBy) => (
                  <input
                    id="exit-tracking"
                    type="text"
                    maxLength={TRACKING_NUMBER_MAX_LENGTH}
                    value={values.trackingNumber}
                    onChange={(event) => update("trackingNumber", event.target.value)}
                    aria-invalid={Boolean(errors.trackingNumber)}
                    aria-describedby={describedBy}
                    className={controlClasses(Boolean(errors.trackingNumber))}
                  />
                )}
              </FormField>
            ) : (
              <p className="text-xs text-slate-500">
                Las pérdidas confirmadas (daño o descuadre) no llevan número de seguimiento.
              </p>
            )}

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
              {saving ? "Registrando..." : "Registrar salida"}
            </button>
          </form>
        )}
      </section>
    </div>
  );
}
