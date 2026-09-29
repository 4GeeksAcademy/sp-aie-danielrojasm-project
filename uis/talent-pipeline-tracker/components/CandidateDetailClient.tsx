"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import CandidateForm from "@/components/CandidateForm";
import {
  STAGE_OPTIONS,
  STATUS_OPTIONS,
  formatDate,
  getStageLabel,
  getStatusLabel,
} from "@/lib/domain";
import {
  addRecordNote,
  deleteRecordNote,
  fetchRecordById,
  fetchRecordNotes,
  getUserMessage,
  patchRecord,
  updateRecord,
} from "@/services/recordsApi";
import {
  Candidate,
  CandidateFormValues,
  CandidateNote,
  CandidateStage,
  CandidateStatus,
} from "@/types/candidate";

interface CandidateDetailClientProps {
  id: string;
}

export default function CandidateDetailClient({ id }: CandidateDetailClientProps) {
  const [candidate, setCandidate] = useState<Candidate | null>(null);
  const [notes, setNotes] = useState<CandidateNote[]>([]);

  const [isLoadingCandidate, setIsLoadingCandidate] = useState(true);
  const [candidateError, setCandidateError] = useState<string | null>(null);
  const [candidateAttempt, setCandidateAttempt] = useState(0);

  const [isLoadingNotes, setIsLoadingNotes] = useState(true);
  const [notesError, setNotesError] = useState<string | null>(null);
  const [notesAttempt, setNotesAttempt] = useState(0);
  const [deletingNoteId, setDeletingNoteId] = useState<string | null>(null);

  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [isUpdatingStatus, setIsUpdatingStatus] = useState(false);

  const [stageMessage, setStageMessage] = useState<string | null>(null);
  const [stageError, setStageError] = useState<string | null>(null);
  const [isUpdatingStage, setIsUpdatingStage] = useState(false);

  const [newNote, setNewNote] = useState("");
  const [isAddingNote, setIsAddingNote] = useState(false);
  const [noteError, setNoteError] = useState<string | null>(null);
  const [noteMessage, setNoteMessage] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function loadCandidate() {
      setIsLoadingCandidate(true);
      setCandidateError(null);

      try {
        const foundCandidate = await fetchRecordById(id);
        if (active) setCandidate(foundCandidate);
      } catch (error) {
        if (active) {
          setCandidateError(getUserMessage(error, "No se pudo cargar la candidatura."));
        }
      } finally {
        if (active) setIsLoadingCandidate(false);
      }
    }

    void loadCandidate();
    return () => {
      active = false;
    };
  }, [id, candidateAttempt]);

  useEffect(() => {
    let active = true;

    async function loadNotes() {
      setIsLoadingNotes(true);
      setNotesError(null);

      try {
        const fetchedNotes = await fetchRecordNotes(id);
        if (active) setNotes(fetchedNotes ?? []);
      } catch (error) {
        if (active) {
          setNotesError(getUserMessage(error, "No se pudieron cargar las notas."));
        }
      } finally {
        if (active) setIsLoadingNotes(false);
      }
    }

    void loadNotes();
    return () => {
      active = false;
    };
  }, [id, notesAttempt]);

  const handleStatusUpdate = async (status: CandidateStatus) => {
    if (!candidate) return;

    setIsUpdatingStatus(true);
    setStatusMessage(null);
    setStatusError(null);

    try {
      const updatedCandidate = await patchRecord(candidate.id, { status });
      setCandidate(updatedCandidate);
      setStatusMessage("Estado actualizado correctamente.");
    } catch (error) {
      setStatusError(
        getUserMessage(error, "No se pudo actualizar el estado. Inténtalo de nuevo."),
      );
    } finally {
      setIsUpdatingStatus(false);
    }
  };

  const handleStageUpdate = async (stage: CandidateStage) => {
    if (!candidate) return;

    setIsUpdatingStage(true);
    setStageMessage(null);
    setStageError(null);

    try {
      const updatedCandidate = await patchRecord(candidate.id, { stage });
      setCandidate(updatedCandidate);
      setStageMessage("Etapa actualizada correctamente.");
    } catch (error) {
      setStageError(
        getUserMessage(error, "No se pudo actualizar la etapa. Inténtalo de nuevo."),
      );
    } finally {
      setIsUpdatingStage(false);
    }
  };

  const handleAddNote = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    if (!newNote.trim()) {
      setNoteError("La nota no puede estar vacia.");
      return;
    }

    setIsAddingNote(true);
    setNoteError(null);
    setNoteMessage(null);

    try {
      const createdNote = await addRecordNote(id, newNote.trim());
      setNotes((previousNotes) => [createdNote, ...previousNotes]);
      setNewNote("");
      setNoteMessage("Nota añadida correctamente.");
    } catch (error) {
      setNoteError(
        getUserMessage(error, "No se pudo añadir la nota. Inténtalo de nuevo."),
      );
    } finally {
      setIsAddingNote(false);
    }
  };

  const handleDeleteNote = async (noteId: string) => {
    setNoteError(null);
    setNoteMessage(null);
    setDeletingNoteId(noteId);

    try {
      await deleteRecordNote(id, noteId);
      setNotes((previousNotes) =>
        previousNotes.filter((noteItem) => noteItem.id !== noteId),
      );
      setNoteMessage("Nota eliminada correctamente.");
    } catch (error) {
      setNoteError(
        getUserMessage(error, "No se pudo eliminar la nota. Inténtalo de nuevo."),
      );
    } finally {
      setDeletingNoteId(null);
    }
  };

  const handleEditSubmit = async (
    values: CandidateFormValues,
  ): Promise<Candidate> => {
    const updated = await updateRecord(id, values);
    setCandidate(updated);
    return updated;
  };

  return (
    <div className="mx-auto grid w-full max-w-6xl gap-6 px-4 py-6 md:px-6">
      <header className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-cyan-300/20 bg-slate-950/85 p-5 text-slate-100 shadow-lg shadow-cyan-900/20 backdrop-blur">
        <div>
          <p className="text-xs uppercase tracking-[0.2em] text-cyan-200">
            TrackFlow · People & Talent
          </p>
          <h1 className="mt-1 text-2xl font-black text-white">Detalle de candidatura</h1>
        </div>
        <Link
          href="/"
          className="rounded-lg border border-slate-600 px-3 py-2 text-sm font-semibold text-slate-100 transition hover:border-cyan-200 hover:text-cyan-100"
        >
          Volver al listado
        </Link>
      </header>

      {isLoadingCandidate && (
        <p className="rounded-lg border border-cyan-300/30 bg-cyan-300/10 px-3 py-2 text-sm text-cyan-100">
          Cargando detalle de candidatura...
        </p>
      )}

      {candidateError && (
        <div
          role="alert"
          className="rounded-lg border border-rose-300/40 bg-rose-400/10 px-3 py-2 text-sm text-rose-200"
        >
          <p>{candidateError}</p>
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={() => setCandidateAttempt((attempt) => attempt + 1)}
              className="mt-2 rounded-lg border border-rose-300/50 bg-slate-950 px-3 py-1.5 text-xs font-semibold text-rose-100 hover:border-rose-200"
            >
              Reintentar
            </button>
            <Link href="/" className="mt-2 text-xs font-semibold text-cyan-200 underline">
              Volver al listado
            </Link>
          </div>
        </div>
      )}

      {candidate && !candidateError && !isLoadingCandidate && (
        <>
          <section className="grid gap-4 rounded-2xl border border-slate-700 bg-slate-900/80 p-4 shadow-lg shadow-black/20 md:grid-cols-2">
            <article className="grid gap-1 text-sm text-slate-300">
              <h2 className="mb-2 text-lg font-bold text-cyan-100">Datos de la candidatura</h2>
              <p><strong>Nombre:</strong> {candidate.name}</p>
              <p><strong>Email:</strong> {candidate.email}</p>
              <p><strong>Teléfono:</strong> {candidate.phone}</p>
              <p><strong>Puesto:</strong> {candidate.position}</p>
              <p>
                <strong>LinkedIn:</strong>{" "}
                {candidate.linkedinUrl ? (
                  <a
                    href={candidate.linkedinUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="text-cyan-200 underline hover:text-cyan-100"
                  >
                    Ver perfil
                  </a>
                ) : (
                  "-"
                )}
              </p>
              <p>
                <strong>CV:</strong>{" "}
                {candidate.cvUrl ? (
                  <a
                    href={candidate.cvUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="text-cyan-200 underline hover:text-cyan-100"
                  >
                    Ver CV
                  </a>
                ) : (
                  "-"
                )}
              </p>
              <p><strong>Años de experiencia:</strong> {candidate.yearsExperience}</p>
              <p><strong>Estado:</strong> {getStatusLabel(candidate.status)}</p>
              <p><strong>Etapa:</strong> {getStageLabel(candidate.stage)}</p>
              <p><strong>Fecha de aplicación:</strong> {formatDate(candidate.appliedAt)}</p>
            </article>

            <article className="grid gap-4">
              <div className="rounded-lg border border-slate-700 bg-slate-950 p-3">
                <h3 className="mb-2 text-sm font-semibold text-cyan-100">Actualizar estado</h3>
                <select
                  className="w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-cyan-300 focus:ring-2 focus:ring-cyan-300/30"
                  value={candidate.status}
                  onChange={(event) =>
                    handleStatusUpdate(event.target.value as CandidateStatus)
                  }
                  disabled={isUpdatingStatus}
                >
                  {STATUS_OPTIONS.map((statusValue) => (
                    <option key={statusValue} value={statusValue}>
                      {getStatusLabel(statusValue)}
                    </option>
                  ))}
                </select>
                {statusError && (
                  <p className="mt-2 text-sm text-rose-200">{statusError}</p>
                )}
                {statusMessage && (
                  <p className="mt-2 text-sm text-emerald-200">{statusMessage}</p>
                )}
              </div>

              <div className="rounded-lg border border-slate-700 bg-slate-950 p-3">
                <h3 className="mb-2 text-sm font-semibold text-cyan-100">Actualizar etapa</h3>
                <select
                  className="w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-cyan-300 focus:ring-2 focus:ring-cyan-300/30"
                  value={candidate.stage}
                  onChange={(event) =>
                    handleStageUpdate(event.target.value as CandidateStage)
                  }
                  disabled={isUpdatingStage}
                >
                  {STAGE_OPTIONS.map((stageValue) => (
                    <option key={stageValue} value={stageValue}>
                      {getStageLabel(stageValue)}
                    </option>
                  ))}
                </select>
                {stageError && <p className="mt-2 text-sm text-rose-200">{stageError}</p>}
                {stageMessage && (
                  <p className="mt-2 text-sm text-emerald-200">{stageMessage}</p>
                )}
              </div>
            </article>
          </section>

          <section className="rounded-2xl border border-slate-700 bg-slate-900/80 p-4 shadow-lg shadow-black/20">
            <h2 className="mb-3 text-lg font-bold text-cyan-100">Notas internas</h2>

            <form className="grid gap-2" onSubmit={handleAddNote}>
              <textarea
                className="min-h-24 rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-cyan-300 focus:ring-2 focus:ring-cyan-300/30"
                value={newNote}
                onChange={(event) => setNewNote(event.target.value)}
                placeholder="Añade una nota interna después de una llamada o entrevista"
              />
              <button
                className="w-fit rounded-lg bg-cyan-300 px-4 py-2 text-sm font-bold text-slate-950 transition hover:bg-cyan-200 disabled:cursor-not-allowed disabled:opacity-70"
                type="submit"
                disabled={isAddingNote}
              >
                {isAddingNote ? "Guardando nota..." : "Añadir nota"}
              </button>
            </form>

            {noteError && (
              <p className="mt-3 rounded-lg border border-rose-300/40 bg-rose-400/10 px-3 py-2 text-sm text-rose-200">
                {noteError}
              </p>
            )}
            {noteMessage && (
              <p className="mt-3 rounded-lg border border-emerald-300/40 bg-emerald-400/10 px-3 py-2 text-sm text-emerald-200">
                {noteMessage}
              </p>
            )}

            {isLoadingNotes && (
              <p className="mt-4 rounded-lg border border-cyan-300/30 bg-cyan-300/10 px-3 py-2 text-sm text-cyan-100">
                Cargando notas...
              </p>
            )}

            {notesError && (
              <div
                role="alert"
                className="mt-4 rounded-lg border border-rose-300/40 bg-rose-400/10 px-3 py-2 text-sm text-rose-200"
              >
                <p>{notesError}</p>
                <button
                  type="button"
                  onClick={() => setNotesAttempt((attempt) => attempt + 1)}
                  className="mt-2 rounded-lg border border-rose-300/50 bg-slate-950 px-3 py-1.5 text-xs font-semibold text-rose-100 hover:border-rose-200"
                >
                  Reintentar
                </button>
              </div>
            )}

            {!isLoadingNotes && !notesError && (
              <ul className="mt-4 grid gap-3">
                {notes.length === 0 ? (
                  <li className="rounded-lg border border-dashed border-slate-600 bg-slate-950 p-3 text-sm text-slate-300">
                    Todavía no hay notas registradas para esta candidatura.
                  </li>
                ) : (
                  notes.map((note) => (
                    <li
                      key={note.id}
                      className="rounded-lg border border-slate-700 bg-slate-950 p-3"
                    >
                      <p className="text-sm text-slate-100">{note.content}</p>
                      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                        <span className="text-xs text-slate-400">
                          {note.createdAt ? formatDate(note.createdAt) : "Sin fecha"}
                        </span>
                        <button
                          type="button"
                          className="rounded-lg border border-rose-300/50 bg-rose-400/10 px-3 py-1 text-xs font-semibold text-rose-200 disabled:cursor-wait disabled:opacity-60"
                          disabled={deletingNoteId === note.id}
                          onClick={() => void handleDeleteNote(note.id)}
                        >
                          {deletingNoteId === note.id ? "Eliminando..." : "Eliminar nota"}
                        </button>
                      </div>
                    </li>
                  ))
                )}
              </ul>
            )}
          </section>

          <CandidateForm
            mode="edit"
            title="Editar candidatura"
            submitLabel="Guardar cambios"
            initialCandidate={candidate}
            onSubmit={handleEditSubmit}
            onSuccess={setCandidate}
          />
        </>
      )}
    </div>
  );
}
