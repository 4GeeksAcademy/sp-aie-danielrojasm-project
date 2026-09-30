"use client";

import { useEffect, useRef } from "react";
import { usePathname } from "next/navigation";
import { useReportWebVitals } from "next/web-vitals";
import { onTelemetryPageHide, track } from "@/lib/telemetry";
import type { BackofficeEventProperties } from "@/lib/telemetry-events";
import { deviceClass, routeTemplate, sectionForRoute } from "@/lib/telemetry-helpers";
import { reportFrontendError } from "@/lib/telemetry-reporters";

/** Las redirecciones (`/inventory` → `/inventory/products`, 401 → `/login`) solo cuentan el destino. */
const PAGE_VIEW_DEBOUNCE_MS = 1_000;

type PageLoad = BackofficeEventProperties["page_load_recorded"];
type WebVitalsMetric = Parameters<Parameters<typeof useReportWebVitals>[0]>[0];

const VITAL_FIELDS: Record<string, keyof PageLoad> = {
  TTFB: "ttfb_ms",
  FCP: "fcp_ms",
  LCP: "lcp_ms",
  INP: "inp_ms",
  CLS: "cls",
};

// Una carga de página = un evento con todas las métricas disponibles al ocultarse.
const vitals: Partial<Record<keyof PageLoad, number>> = {};
let pageLoadReported = false;

function recordWebVital(metric: WebVitalsMetric): void {
  const field = VITAL_FIELDS[metric.name];
  if (field) vitals[field] = metric.value;
}

/** Milisegundos enteros; CLS (sin unidad) con 4 decimales. */
function vitalValue(field: keyof PageLoad): number | null {
  const value = vitals[field];
  if (typeof value !== "number") return null;
  return field === "cls" ? Number(value.toFixed(4)) : Math.round(value);
}

function navigationType(): PageLoad["navigation_type"] {
  const entry = performance.getEntriesByType("navigation")[0] as PerformanceNavigationTiming | undefined;
  const type = entry?.type as string | undefined;
  return type === "reload" || type === "back_forward" || type === "prerender" ? type : "navigate";
}

function reportPageLoad(route: string): void {
  if (pageLoadReported) return;
  pageLoadReported = true;
  track("page_load_recorded", {
    route,
    ttfb_ms: vitalValue("ttfb_ms"),
    fcp_ms: vitalValue("fcp_ms"),
    lcp_ms: vitalValue("lcp_ms"),
    inp_ms: vitalValue("inp_ms"),
    cls: vitalValue("cls"),
    navigation_type: navigationType(),
    device_class: deviceClass(),
  });
}

/**
 * Instrumentación transversal del backoffice (piso técnico del plan):
 * `page_viewed`, `frontend_error_captured` de `window` y `page_load_recorded`
 * (Web Vitals reales). No pinta nada.
 */
export function TelemetryListener() {
  const pathname = usePathname();
  const previousRoute = useRef<string | null>(null);

  useReportWebVitals(recordWebVital);

  useEffect(() => {
    // La ruta de la carga inicial: las navegaciones SPA posteriores no son cargas.
    const loadRoute = routeTemplate(window.location.pathname);
    const stopListening = onTelemetryPageHide(() => reportPageLoad(loadRoute));
    const onError = (event: ErrorEvent) => reportFrontendError(event.error, "window");
    const onRejection = (event: PromiseRejectionEvent) =>
      reportFrontendError(event.reason, "unhandled_rejection");
    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onRejection);
    return () => {
      stopListening();
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onRejection);
    };
  }, []);

  useEffect(() => {
    const route = routeTemplate(pathname);
    const timer = setTimeout(() => {
      const section = sectionForRoute(route);
      if (!section || route === previousRoute.current) return;
      track("page_viewed", { route, section, previous_route: previousRoute.current });
      previousRoute.current = route;
    }, PAGE_VIEW_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [pathname]);

  return null;
}
