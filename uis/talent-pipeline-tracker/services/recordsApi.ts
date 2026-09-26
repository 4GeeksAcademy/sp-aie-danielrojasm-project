import {
  Candidate,
  CandidateFormValues,
  CandidateNote,
  CandidateStage,
  CandidateStatus,
  CandidateUpsertPayload,
} from "@/types/candidate";

const DEFAULT_API_BASE_URL = "http://localhost:3001";

const API_BASE_URL = (
  process.env.NEXT_PUBLIC_TRACKFLOW_API_BASE_URL ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  DEFAULT_API_BASE_URL
).replace(/\/$/, "");

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
    cache: "no-store",
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(errorText || "No se pudo completar la solicitud.");
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

function pickString(source: unknown, keys: string[], fallback = ""): string {
  if (!source || typeof source !== "object") {
    return fallback;
  }

  const sourceObject = source as Record<string, unknown>;

  for (const key of keys) {
    const value = sourceObject[key];
    if (typeof value === "string") {
      return value;
    }
    if (typeof value === "number") {
      return String(value);
    }
  }

  return fallback;
}

function pickNumber(source: unknown, keys: string[], fallback = 0): number {
  if (!source || typeof source !== "object") {
    return fallback;
  }

  const sourceObject = source as Record<string, unknown>;

  for (const key of keys) {
    const value = sourceObject[key];
    if (typeof value === "number") {
      return value;
    }
    if (typeof value === "string") {
      const parsedValue = Number(value);
      if (!Number.isNaN(parsedValue)) {
        return parsedValue;
      }
    }
  }

  return fallback;
}

function normalizeStatus(value: string): CandidateStatus {
  const validValues: CandidateStatus[] = [
    "received",
    "in_progress",
    "selected",
    "discarded",
  ];

  return validValues.includes(value as CandidateStatus)
    ? (value as CandidateStatus)
    : "received";
}

function normalizeStage(value: string): CandidateStage {
  const validValues: CandidateStage[] = [
    "pending",
    "review",
    "personal_interview",
    "technical_interview",
    "offer_presented",
  ];

  return validValues.includes(value as CandidateStage)
    ? (value as CandidateStage)
    : "pending";
}

function parseCandidate(rawCandidate: unknown): Candidate {
  const source = (rawCandidate || {}) as Record<string, unknown>;

  return {
    id: pickString(source, ["id", "_id", "record_id"]),
    name: pickString(source, ["name", "full_name", "fullName"]),
    email: pickString(source, ["email"]),
    phone: pickString(source, ["phone", "phone_number"]),
    position: pickString(source, ["position", "job_title", "role"]),
    linkedinUrl: pickString(source, ["linkedin_url", "linkedin", "linkedinUrl"]),
    cvUrl: pickString(source, ["resume_url", "cv_url", "cv", "cvUrl"]),
    yearsExperience: pickNumber(source, [
      "experience_years",
      "years_experience",
      "yearsExperience",
    ]),
    status: normalizeStatus(pickString(source, ["status"], "received")),
    stage: normalizeStage(pickString(source, ["stage"], "pending")),
    appliedAt: pickString(source, ["applied_at", "application_date", "appliedAt"]),
  };
}

function parseNote(rawNote: unknown): CandidateNote {
  const source = (rawNote || {}) as Record<string, unknown>;

  return {
    id: pickString(source, ["id", "note_id", "_id"]),
    content: pickString(source, ["content", "text", "message", "note"]),
    createdAt: pickString(source, ["created_at", "createdAt", "date"]),
  };
}

function parseCandidateCollection(payload: unknown): Candidate[] {
  if (Array.isArray(payload)) {
    return payload.map(parseCandidate);
  }

  if (payload && typeof payload === "object") {
    const source = payload as Record<string, unknown>;
    const nestedItems = source.records;
    if (Array.isArray(nestedItems)) {
      return nestedItems.map(parseCandidate);
    }
  }

  return [];
}

function parseNotesCollection(payload: unknown): CandidateNote[] {
  if (Array.isArray(payload)) {
    return payload.map(parseNote);
  }

  if (payload && typeof payload === "object") {
    const source = payload as Record<string, unknown>;
    const nestedItems = source.notes;
    if (Array.isArray(nestedItems)) {
      return nestedItems.map(parseNote);
    }
  }

  return [];
}

function buildUpsertPayload(values: CandidateFormValues): CandidateUpsertPayload {
  return {
    name: values.name.trim(),
    email: values.email.trim(),
    phone: values.phone.trim(),
    position: values.position.trim(),
    linkedin_url: values.linkedinUrl.trim(),
    resume_url: values.cvUrl.trim(),
    experience_years: Number(values.yearsExperience),
    status: values.status,
    stage: values.stage,
    applied_at: values.appliedAt,
  };
}

export async function fetchRecords(): Promise<Candidate[]> {
  const payload = await request<unknown>("/records");
  return parseCandidateCollection(payload);
}

export async function fetchRecordById(id: string): Promise<Candidate> {
  const payload = await request<unknown>(`/records/${id}`);
  return parseCandidate(payload);
}

export async function patchRecord(
  id: string,
  values: Partial<Pick<Candidate, "status" | "stage">>,
): Promise<Candidate> {
  const payload = await request<unknown>(`/records/${id}`, {
    method: "PATCH",
    body: JSON.stringify(values),
  });
  return parseCandidate(payload);
}

export async function fetchRecordNotes(id: string): Promise<CandidateNote[]> {
  const payload = await request<unknown>(`/records/${id}/notes`);
  return parseNotesCollection(payload);
}

export async function addRecordNote(
  id: string,
  content: string,
): Promise<CandidateNote> {
  const payload = await request<unknown>(`/records/${id}/notes`, {
    method: "POST",
    body: JSON.stringify({ content }),
  });
  return parseNote(payload);
}

export async function deleteRecordNote(
  recordId: string,
  noteId: string,
): Promise<void> {
  await request<void>(`/records/${recordId}/notes/${noteId}`, {
    method: "DELETE",
  });
}

export async function createRecord(
  values: CandidateFormValues,
): Promise<Candidate> {
  const payload = await request<unknown>("/records", {
    method: "POST",
    body: JSON.stringify(buildUpsertPayload(values)),
  });

  return parseCandidate(payload);
}

export async function updateRecord(
  id: string,
  values: CandidateFormValues,
): Promise<Candidate> {
  const payload = await request<unknown>(`/records/${id}`, {
    method: "PUT",
    body: JSON.stringify(buildUpsertPayload(values)),
  });

  return parseCandidate(payload);
}
