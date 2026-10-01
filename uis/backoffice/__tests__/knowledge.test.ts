/** Asistente comercial: validación y cliente de `lib/knowledge.ts`. */
import { ApiError } from "@/lib/api-client";
import { askKnowledgeBase, QUESTION_MAX_LENGTH, validateQuestion } from "@/lib/knowledge";

describe("validateQuestion", () => {
  it("rechaza preguntas vacías o demasiado cortas", () => {
    expect(validateQuestion("   ")).not.toBeNull();
    expect(validateQuestion("ok")).not.toBeNull();
  });

  it("rechaza preguntas por encima del límite de la API", () => {
    expect(validateQuestion("x".repeat(QUESTION_MAX_LENGTH + 1))).toMatch(/1000/);
  });

  it("acepta una pregunta normal", () => {
    expect(validateQuestion("¿Cuál es la ventana de devolución estándar?")).toBeNull();
  });
});

describe("askKnowledgeBase", () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("envía la pregunta recortada y devuelve la respuesta", async () => {
    const fetchMock = jest.fn().mockResolvedValue(
      new Response(JSON.stringify({ answer: "Son 30 días." }), { status: 200 }),
    );
    global.fetch = fetchMock;

    await expect(askKnowledgeBase("  ¿Ventana de devolución?  ")).resolves.toEqual({
      answer: "Son 30 días.",
    });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/knowledge/query");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ question: "¿Ventana de devolución?" });
  });

  it("un 503 es un error visible, no una respuesta vacía", async () => {
    global.fetch = jest.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "El asistente comercial no está disponible." }), {
        status: 503,
      }),
    );

    await expect(askKnowledgeBase("¿Ventana de devolución?")).rejects.toBeInstanceOf(ApiError);
  });
});
