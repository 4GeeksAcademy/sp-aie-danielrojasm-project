"use client";

import { useCallback, useEffect, useMemo, useRef } from "react";
import { usePathname } from "next/navigation";
import {
  inventoryEntryPoint,
  isActiveInventoryForm,
  registerActiveInventoryForm,
  type AbandonReason,
} from "@/lib/inventory-telemetry";
import { onTelemetryPageHide, track } from "@/lib/telemetry";
import type { InventoryForm, InventoryFormField } from "@/lib/telemetry-events";

interface FormAttempt {
  startedAt: number;
  lastField: InventoryFormField | null;
  hadValidationError: boolean;
  hadServerError: boolean;
  handle: { form: InventoryForm; abandon: (reason: AbandonReason) => void };
}

export interface InventoryFormTelemetry {
  /** El operador tocó un campo (nombre, nunca el valor). El primero abre el intento. */
  touch: (field: InventoryFormField) => void;
  validationFailed: () => void;
  serverError: () => void;
  /** 201 de la API: el intento termina en conversión, no en abandono. */
  completed: () => void;
}

/**
 * Conversión de los formularios de entrada y salida: `inventory_form_started`
 * con el primer campo tocado e `inventory_form_abandoned` si el operador se va
 * (otra ruta, cierre de pestaña o sesión caducada) sin registrar la orden.
 */
export function useInventoryFormTelemetry(
  form: InventoryForm,
  prefilledSku: boolean,
  fieldsCompleted: number,
): InventoryFormTelemetry {
  const pathname = usePathname();
  const attempt = useRef<FormAttempt | null>(null);
  const completedFields = useRef(fieldsCompleted);

  useEffect(() => {
    completedFields.current = fieldsCompleted;
  }, [fieldsCompleted]);

  const abandon = useCallback(
    (reason: AbandonReason) => {
      const current = attempt.current;
      if (!current) return;
      attempt.current = null;
      if (isActiveInventoryForm(current.handle)) registerActiveInventoryForm(null);
      track("inventory_form_abandoned", {
        form,
        duration_ms: Math.max(0, Date.now() - current.startedAt),
        last_field: current.lastField,
        fields_completed: completedFields.current,
        had_validation_error: current.hadValidationError,
        had_server_error: current.hadServerError,
        exit_reason: reason,
      });
    },
    [form],
  );

  const ensureStarted = useCallback((): FormAttempt => {
    if (attempt.current) return attempt.current;
    const handle = { form, abandon };
    attempt.current = {
      startedAt: Date.now(),
      lastField: null,
      hadValidationError: false,
      hadServerError: false,
      handle,
    };
    registerActiveInventoryForm(handle);
    track("inventory_form_started", {
      form,
      entry_point: inventoryEntryPoint(pathname, prefilledSku),
      prefilled_sku: prefilledSku,
    });
    return attempt.current;
  }, [form, abandon, pathname, prefilledSku]);

  useEffect(() => {
    // Solo `pagehide` (la página se va): ocultar la pestaña no es abandonar.
    const stopListening = onTelemetryPageHide((reason) => {
      if (reason === "pagehide") abandon("page_hidden");
    });
    return () => {
      stopListening();
      abandon("navigation");
    };
  }, [abandon]);

  return useMemo(
    () => ({
      touch: (field) => {
        ensureStarted().lastField = field;
      },
      validationFailed: () => {
        ensureStarted().hadValidationError = true;
      },
      serverError: () => {
        if (attempt.current) attempt.current.hadServerError = true;
      },
      completed: () => {
        const current = attempt.current;
        attempt.current = null;
        if (current && isActiveInventoryForm(current.handle)) registerActiveInventoryForm(null);
      },
    }),
    [ensureStarted],
  );
}
