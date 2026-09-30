"use client";

import { FormEvent, useState } from "react";
import { getUserMessage, requestJson } from "@/lib/api-client";
import { useApiList } from "@/lib/use-api-list";

type Country = "USA" | "Spain";
type Status = "active" | "suspended";
type Category =
  | "carrier_last_mile"
  | "carrier_international"
  | "warehouse_supplies"
  | "packaging_materials"
  | "reverse_logistics"
  | "fleet_maintenance"
  | "it_and_wms_software"
  | "cleaning_and_facilities";

interface Supplier {
  id: number;
  name: string;
  country: Country;
  categories: Category[];
  rate_per_shipment: number;
  currency: "USD" | "EUR";
  updated_at: string;
  status: Status;
  service_zone?: string | null;
  contact_email?: string | null;
  notes?: string | null;
}

const categoryLabels: Record<Category, string> = {
  carrier_last_mile: "Última milla",
  carrier_international: "Internacional",
  warehouse_supplies: "Suministros de almacén",
  packaging_materials: "Embalaje",
  reverse_logistics: "Logística inversa",
  fleet_maintenance: "Mantenimiento de flota",
  it_and_wms_software: "Software IT / WMS",
  cleaning_and_facilities: "Limpieza e instalaciones",
};

const categories = Object.keys(categoryLabels) as Category[];
const money = new Intl.NumberFormat("es-ES", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

interface FormState {
  name: string;
  country: Country;
  categories: Category[];
  rate_per_shipment: string;
  currency: "USD" | "EUR";
  status: Status;
  service_zone: string;
  contact_email: string;
  notes: string;
}

const emptyForm: FormState = {
  name: "",
  country: "USA",
  categories: ["carrier_last_mile"],
  rate_per_shipment: "",
  currency: "USD",
  status: "active",
  service_zone: "",
  contact_email: "",
  notes: "",
};

const JSON_HEADERS = { "Content-Type": "application/json" };

export function SupplierDirectory() {
  const [country, setCountry] = useState<"all" | Country>("all");
  const [category, setCategory] = useState<"all" | Category>("all");
  const [form, setForm] = useState<FormState>(emptyForm);
  const [saving, setSaving] = useState(false);
  const [pendingId, setPendingId] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [editingRate, setEditingRate] = useState<number | null>(null);
  const [rateValue, setRateValue] = useState("");

  const params = new URLSearchParams();
  if (country !== "all") params.set("country", country);
  if (category !== "all") params.set("category", category);
  const query = params.toString();
  const {
    items: suppliers,
    setItems: setSuppliers,
    loading,
    error: loadError,
    retry: retryLoad,
  } = useApiList<Supplier>(
    () => requestJson<Supplier[]>(`/api/suppliers?${query}`),
    "No se pudo cargar el directorio de proveedores.",
    query,
  );

  function updateForm(field: keyof FormState, value: string) {
    setForm((current) => ({ ...current, [field]: value }));
    if (field === "country") setForm((current) => ({ ...current, currency: value === "USA" ? "USD" : "EUR" }));
  }

  function toggleCategory(value: Category) {
    setForm((current) => ({
      ...current,
      categories: current.categories.includes(value)
        ? current.categories.filter((item) => item !== value)
        : [...current.categories, value],
    }));
  }

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const created = await requestJson<Supplier>("/api/suppliers", {
        method: "POST",
        headers: JSON_HEADERS,
        body: JSON.stringify({
          ...form,
          rate_per_shipment: Number(form.rate_per_shipment),
          service_zone: form.service_zone || null,
          contact_email: form.contact_email || null,
          notes: form.notes || null,
        }),
      }, "No se pudo registrar el proveedor. Revisa los datos.");
      setSuppliers((current) => [...current, created]);
      setForm(emptyForm);
      setNotice("Proveedor registrado correctamente.");
    } catch (createError) {
      setError(getUserMessage(createError, "No se pudo registrar el proveedor. Inténtalo de nuevo."));
    } finally {
      setSaving(false);
    }
  }

  async function updateRate(id: number) {
    const rate = Number(rateValue);
    setError("");
    setNotice("");
    if (!Number.isFinite(rate) || rate <= 0) {
      setError("La tarifa debe ser un número mayor que 0.");
      return;
    }
    setPendingId(id);
    try {
      const updated = await requestJson<Supplier>(`/api/suppliers/${id}/rate`, {
        method: "PATCH",
        headers: JSON_HEADERS,
        body: JSON.stringify({ rate_per_shipment: rate }),
      }, "No se pudo actualizar la tarifa.");
      setSuppliers((current) => current.map((supplier) => supplier.id === id ? updated : supplier));
      setEditingRate(null);
      setNotice("Tarifa actualizada y fechada correctamente.");
    } catch (rateError) {
      setError(getUserMessage(rateError, "No se pudo actualizar la tarifa. Inténtalo de nuevo."));
    } finally {
      setPendingId(null);
    }
  }

  async function toggleStatus(supplier: Supplier) {
    const nextStatus: Status = supplier.status === "active" ? "suspended" : "active";
    setError("");
    setNotice("");
    setPendingId(supplier.id);
    try {
      const updated = await requestJson<Supplier>(`/api/suppliers/${supplier.id}/status`, {
        method: "PATCH",
        headers: JSON_HEADERS,
        body: JSON.stringify({ status: nextStatus }),
      }, "No se pudo cambiar el estado.");
      setSuppliers((current) => current.map((item) => item.id === supplier.id ? updated : item));
    } catch (statusError) {
      setError(getUserMessage(statusError, `No se pudo cambiar el estado de ${supplier.name}. Inténtalo de nuevo.`));
    } finally {
      setPendingId(null);
    }
  }

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <header>
        <p className="text-sm font-semibold uppercase tracking-[0.18em] text-cyan-700">Compras · Milestone 09</p>
        <h1 className="mt-2 text-3xl font-bold text-slate-950">Directorio de proveedores</h1>
        <p className="mt-2 max-w-3xl text-sm text-slate-600">Una fuente de verdad para tarifas, cobertura y estado operativo en USA y Spain.</p>
      </header>

      {error ? <p className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800" role="alert">{error}</p> : null}
      {notice ? <p className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800" role="status">{notice}</p> : null}

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <section aria-labelledby="supplier-list-title" className="min-w-0 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <h2 id="supplier-list-title" className="text-lg font-semibold text-slate-900">Proveedores operativos</h2>
              <p className="mt-1 text-sm text-slate-500">{loading ? "Cargando proveedores..." : loadError ? "Sin datos" : `${suppliers.length} proveedores en la vista actual`}</p>
            </div>
            <div className="flex flex-wrap gap-3">
              <label className="text-xs font-medium text-slate-600">País<select value={country} onChange={(event) => setCountry(event.target.value as "all" | Country)} className="mt-1 block rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"><option value="all">Todos</option><option value="USA">USA</option><option value="Spain">Spain</option></select></label>
              <label className="text-xs font-medium text-slate-600">Categoría<select value={category} onChange={(event) => setCategory(event.target.value as "all" | Category)} className="mt-1 block max-w-52 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"><option value="all">Todas</option>{categories.map((item) => <option key={item} value={item}>{categoryLabels[item]}</option>)}</select></label>
            </div>
          </div>
          {/* Alto fijo por debajo de xl, donde el formulario va debajo: pasar del esqueleto a la
              tabla real no lo desplaza (CLS). En xl el formulario va al lado y la lista crece. */}
          <div
            role="region"
            aria-labelledby="supplier-list-title"
            tabIndex={0}
            className="mt-5 h-[28rem] overflow-y-auto xl:h-auto xl:overflow-visible"
          >
          {loading ? (
            <div aria-busy="true" className="space-y-2">
              <p className="sr-only" role="status">Cargando proveedores...</p>
              {Array.from({ length: 4 }, (_, index) => <div key={index} className="h-14 animate-pulse rounded-lg bg-slate-100" />)}
            </div>
          ) : null}
          {!loading && loadError ? (
            <div role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-5 text-center text-sm text-rose-800">
              <p>{loadError}</p>
              <button type="button" onClick={retryLoad} className="mt-3 rounded-md border border-rose-300 bg-white px-4 py-2 font-semibold hover:bg-rose-100">Reintentar</button>
            </div>
          ) : null}
          {!loading && !loadError ? <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-left text-sm">
              <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500"><tr><th className="px-3 py-3">Proveedor</th><th className="px-3 py-3">País</th><th className="px-3 py-3">Categorías</th><th className="px-3 py-3">Tarifa</th><th className="px-3 py-3">Estado</th><th className="px-3 py-3">Acciones</th></tr></thead>
              <tbody className="divide-y divide-slate-100">
                {suppliers.map((supplier) => <tr key={supplier.id} className={supplier.status === "suspended" ? "bg-slate-50 text-slate-500" : ""}>
                  <td className="px-3 py-4"><p className="font-semibold text-slate-900">{supplier.name}</p><p className="mt-1 text-xs">{supplier.service_zone || "Cobertura no indicada"}</p></td>
                  <td className="px-3 py-4">{supplier.country}</td>
                  <td className="max-w-56 px-3 py-4"><div className="flex flex-wrap gap-1">{(supplier.categories ?? []).map((item) => <span key={item} className="rounded bg-cyan-50 px-2 py-1 text-xs text-cyan-800">{categoryLabels[item]}</span>)}</div></td>
                  <td className="whitespace-nowrap px-3 py-4 font-semibold tabular-nums">{editingRate === supplier.id ? <div className="flex items-center gap-1"><input aria-label={`Nueva tarifa de ${supplier.name}`} type="number" min="0.01" step="0.01" value={rateValue} onChange={(event) => setRateValue(event.target.value)} className="w-24 rounded border border-slate-300 px-2 py-1" /><button type="button" disabled={pendingId === supplier.id} onClick={() => void updateRate(supplier.id)} className="rounded bg-slate-900 px-2 py-1 text-xs text-white disabled:cursor-wait disabled:opacity-60">{pendingId === supplier.id ? "Guardando..." : "Guardar"}</button></div> : <button type="button" onClick={() => { setEditingRate(supplier.id); setRateValue(String(supplier.rate_per_shipment)); }} className="underline decoration-dotted underline-offset-4">{money.format(supplier.rate_per_shipment)} {supplier.currency}</button>}</td>
                  <td className="px-3 py-4"><span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${supplier.status === "active" ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-800"}`}>{supplier.status === "active" ? "Activo" : "Suspendido"}</span></td>
                  <td className="px-3 py-4"><button type="button" disabled={pendingId === supplier.id} onClick={() => void toggleStatus(supplier)} className="whitespace-nowrap rounded-md border border-slate-300 px-2.5 py-1.5 text-xs font-medium hover:bg-slate-100 disabled:cursor-wait disabled:opacity-60">{pendingId === supplier.id ? "Guardando..." : supplier.status === "active" ? "Suspender" : "Reactivar"}</button></td>
                </tr>)}
              </tbody>
            </table>
            {suppliers.length === 0 ? <p className="py-8 text-center text-sm text-slate-500">{country === "all" && category === "all" ? "Todavía no hay proveedores registrados. Usa el formulario para dar de alta el primero." : "No hay proveedores para estos filtros."}</p> : null}
          </div> : null}
          </div>
        </section>

        <section aria-labelledby="new-supplier-title" className="rounded-xl border border-slate-200 bg-slate-950 p-5 text-white shadow-sm">
          <h2 id="new-supplier-title" className="text-lg font-semibold">Registrar proveedor</h2>
          <p className="mt-1 text-sm text-slate-300">La tarifa y la moneda se validan antes de persistir.</p>
          <form onSubmit={handleCreate} className="mt-5 space-y-4">
            <label className="block text-sm">Nombre<input required value={form.name} onChange={(event) => updateForm("name", event.target.value)} className="mt-1 w-full rounded-md border border-slate-600 bg-slate-900 px-3 py-2 text-white" /></label>
            <div className="grid grid-cols-2 gap-3"><label className="block text-sm">País<select value={form.country} onChange={(event) => updateForm("country", event.target.value)} className="mt-1 w-full rounded-md border border-slate-600 bg-slate-900 px-3 py-2 text-white"><option value="USA">USA</option><option value="Spain">Spain</option></select></label><label className="block text-sm">Moneda<select value={form.currency} disabled className="mt-1 w-full rounded-md border border-slate-600 bg-slate-800 px-3 py-2 text-slate-300"><option value="USD">USD</option><option value="EUR">EUR</option></select></label></div>
            <label className="block text-sm">Tarifa por envío<input required min="0.01" step="0.01" type="number" value={form.rate_per_shipment} onChange={(event) => updateForm("rate_per_shipment", event.target.value)} className="mt-1 w-full rounded-md border border-slate-600 bg-slate-900 px-3 py-2 text-white" /></label>
            <fieldset><legend className="text-sm">Categorías</legend><div className="mt-2 grid gap-2">{categories.map((item) => <label key={item} className="flex items-center gap-2 text-xs text-slate-300"><input type="checkbox" checked={form.categories.includes(item)} onChange={() => toggleCategory(item)} />{categoryLabels[item]}</label>)}</div></fieldset>
            <label className="block text-sm">Zona de servicio<input value={form.service_zone} onChange={(event) => updateForm("service_zone", event.target.value)} className="mt-1 w-full rounded-md border border-slate-600 bg-slate-900 px-3 py-2 text-white" /></label>
            <label className="block text-sm">Email de contacto<input type="email" value={form.contact_email} onChange={(event) => updateForm("contact_email", event.target.value)} className="mt-1 w-full rounded-md border border-slate-600 bg-slate-900 px-3 py-2 text-white" /></label>
            <label className="block text-sm">Notas<textarea value={form.notes} onChange={(event) => updateForm("notes", event.target.value)} className="mt-1 min-h-20 w-full rounded-md border border-slate-600 bg-slate-900 px-3 py-2 text-white" /></label>
            <button disabled={saving} type="submit" className="w-full rounded-md bg-cyan-300 px-4 py-2.5 text-sm font-bold text-slate-950 disabled:cursor-wait disabled:opacity-60">{saving ? "Guardando..." : "Registrar proveedor"}</button>
          </form>
        </section>
      </div>
    </div>
  );
}