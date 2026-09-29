export function TopBar() {
  return (
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-white px-6 py-4">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-700">
          Operaciones de almacén · Los Ángeles y Zaragoza
        </p>
        <p className="text-sm text-slate-500">
          Responsable: Ana Whitfield, Directora de Operaciones de Almacén
        </p>
      </div>
      <span className="rounded-full border border-amber-300 bg-amber-50 px-3 py-1 text-xs font-medium text-amber-800">
        Datos de ejemplo · sin conexión a API
      </span>
    </header>
  );
}
