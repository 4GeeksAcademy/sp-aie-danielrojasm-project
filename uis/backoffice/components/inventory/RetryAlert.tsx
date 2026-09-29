interface RetryAlertProps {
  message: string;
  onRetry: () => void;
}

/** Error de carga con «Reintentar»: ningún fallo de la API queda en silencio. */
export function RetryAlert({ message, onRetry }: RetryAlertProps) {
  return (
    <div
      role="alert"
      className="rounded-lg border border-rose-200 bg-rose-50 p-5 text-center text-sm text-rose-800"
    >
      <p>{message}</p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-3 rounded-md border border-rose-300 bg-white px-4 py-2 font-semibold hover:bg-rose-100"
      >
        Reintentar
      </button>
    </div>
  );
}
