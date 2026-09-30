/**
 * @jest-environment jsdom
 */
/** Hook compartido de carga de listas (`lib/use-api-list.ts`). */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { ApiError } from "@/lib/api-client";
import { useApiList, type ApiList } from "@/lib/use-api-list";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let latest: ApiList<string>;

interface ProbeProps {
  load: () => Promise<string[]>;
  keyValue?: string;
  onResult: (result: ApiList<string>) => void;
}

function Probe({ load, keyValue, onResult }: ProbeProps) {
  onResult(useApiList(load, "No se pudo cargar la lista.", keyValue));
  return null;
}

function capture(result: ApiList<string>) {
  latest = result;
}

async function render(load: () => Promise<string[]>, keyValue?: string) {
  await act(async () => root.render(<Probe load={load} keyValue={keyValue} onResult={capture} />));
}

beforeEach(() => {
  root = createRoot(document.createElement("div"));
});

afterEach(() => {
  act(() => root.unmount());
});

describe("useApiList", () => {
  it("empieza cargando y expone los elementos recibidos", async () => {
    let resolve: (value: string[]) => void = () => {};
    const load = () => new Promise<string[]>((done) => (resolve = done));

    await render(load);
    expect(latest.loading).toBe(true);
    expect(latest.items).toEqual([]);

    await act(async () => resolve(["TEC-EAR-001", "CSM-SRM-030"]));
    expect(latest.loading).toBe(false);
    expect(latest.error).toBe("");
    expect(latest.items).toEqual(["TEC-EAR-001", "CSM-SRM-030"]);
  });

  it("muestra el mensaje de la API y se recupera al reintentar", async () => {
    const load = jest
      .fn<Promise<string[]>, []>()
      .mockRejectedValueOnce(new ApiError("El servicio de inventario no responde.", 503))
      .mockResolvedValueOnce(["TEC-CHG-065"]);

    await render(load);
    expect(latest.loading).toBe(false);
    expect(latest.error).toBe("El servicio de inventario no responde.");
    expect(latest.items).toEqual([]);

    await act(async () => latest.retry());
    expect(load).toHaveBeenCalledTimes(2);
    expect(latest.error).toBe("");
    expect(latest.items).toEqual(["TEC-CHG-065"]);
  });

  it("usa el mensaje por defecto si el error no trae uno para el usuario", async () => {
    await render(() => Promise.reject(new TypeError("Failed to fetch")));
    expect(latest.error).toBe("No se pudo cargar la lista.");
  });

  it("trata una respuesta que no es un array como lista vacía", async () => {
    await render(() => Promise.resolve({ detail: "inesperado" } as unknown as string[]));
    expect(latest.error).toBe("");
    expect(latest.items).toEqual([]);
  });

  it("recarga al cambiar la clave y descarta la respuesta anterior", async () => {
    const pending = new Map<string, (value: string[]) => void>();
    const loadFor = (key: string) => () =>
      new Promise<string[]>((done) => pending.set(key, done));

    await render(loadFor("country=USA"), "country=USA");
    await render(loadFor("country=Spain"), "country=Spain");
    expect(latest.loading).toBe(true);

    await act(async () => pending.get("country=Spain")?.(["Zaragoza"]));
    await act(async () => pending.get("country=USA")?.(["Los Ángeles"]));
    expect(latest.items).toEqual(["Zaragoza"]);
  });

  it("permite reflejar en local un alta confirmada por la API", async () => {
    await render(() => Promise.resolve(["A"]));
    await act(async () => latest.setItems((current) => [...current, "B"]));
    expect(latest.items).toEqual(["A", "B"]);
  });
});
