"use client";

import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Badge, Panel } from "@/components/ui/Panel";
import {
  CHAT_MESSAGE_MAX_LENGTH,
  chatConnectionLabels,
  chatMessageStatusLabels,
  type ChatConnectionStatus,
  type ChatMessage,
  type ChatMessageStatus,
} from "@/lib/agent-chat";
import { useAgentChat } from "@/lib/use-agent-chat";

const statusTones: Record<ChatMessageStatus, "neutral" | "success" | "warning" | "danger" | "info"> = {
  streaming: "info",
  completed: "success",
  interrupted: "warning",
  failed: "danger",
};

const connectionTones: Record<ChatConnectionStatus["state"], "neutral" | "success" | "warning" | "danger"> = {
  connecting: "neutral",
  open: "success",
  reconnecting: "warning",
  closed: "danger",
};

interface ChatBubbleProps {
  message: ChatMessage;
}

function ChatBubble({ message }: ChatBubbleProps) {
  const fromUser = message.role === "user";
  return (
    <li className={`flex ${fromUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed shadow-sm ${
          fromUser ? "bg-slate-900 text-white" : "border border-slate-200 bg-white text-slate-800"
        } ${message.status === "interrupted" ? "border-dashed border-amber-400" : ""}`}
      >
        <p className="mb-1 text-xs font-semibold uppercase tracking-wide opacity-70">
          {fromUser ? "Tú" : "Agente de CX"}
        </p>
        <p className="whitespace-pre-line">
          {message.text}
          {message.status === "streaming" ? (
            <span aria-hidden="true" className="ml-0.5 inline-block w-2 animate-pulse bg-cyan-600">
              &nbsp;
            </span>
          ) : null}
        </p>
        {!fromUser && message.status !== "completed" ? (
          <p className="mt-2">
            <Badge tone={statusTones[message.status]}>{chatMessageStatusLabels[message.status]}</Badge>
          </p>
        ) : null}
      </div>
    </li>
  );
}

interface ConnectionBadgeProps {
  status: ChatConnectionStatus;
}

function ConnectionBadge({ status }: ConnectionBadgeProps) {
  const retry =
    status.state === "reconnecting" && status.retryInMs !== null
      ? ` (intento ${status.attempt}, en ${Math.ceil(status.retryInMs / 1000)} s)`
      : "";
  return (
    <Badge tone={connectionTones[status.state]}>
      {chatConnectionLabels[status.state]}
      {retry}
    </Badge>
  );
}

export function SupportChat() {
  const { thread, status, fatalError, generating, send, startNewConversation, dismissError } = useAgentChat();
  const [draft, setDraft] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  const lastText = thread.messages.at(-1)?.text;
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [thread.messages.length, lastText]);

  const canSend = thread.ready && status.state === "open";
  const error = localError ?? thread.error;

  function submit() {
    if (!draft.trim()) {
      setLocalError("Escribe tu mensaje para el agente.");
      return;
    }
    if (!send(draft)) {
      setLocalError("Sin conexión con el agente: espera a que se recupere y vuelve a enviarlo.");
      return;
    }
    setDraft("");
    setLocalError(null);
    dismissError();
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    submit();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.18em] text-cyan-700">
            Customer Experience · Agente de primera línea
          </p>
          <h1 className="mt-2 text-3xl font-bold text-slate-950">Atención al cliente</h1>
          <p className="mt-2 text-sm text-slate-600">
            Consulta tracking, devoluciones y preguntas frecuentes. La respuesta aparece mientras el
            agente la escribe; si va por el camino equivocado, escribe de nuevo para interrumpirlo y
            redirigirlo.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <ConnectionBadge status={status} />
          <button
            type="button"
            onClick={startNewConversation}
            className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:border-cyan-500 hover:text-cyan-800"
          >
            Nueva conversación
          </button>
        </div>
      </header>

      {fatalError ? (
        <p role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm font-medium text-rose-800">
          {fatalError}
        </p>
      ) : null}

      <Panel id="support-chat" title="Conversación">
        <div className="max-h-[55vh] min-h-48 overflow-y-auto rounded-lg bg-slate-50 p-4">
          {!thread.ready ? (
            <p className="text-sm text-slate-500">
              {status.state === "reconnecting"
                ? "Recuperando la conversación…"
                : "Conectando con el agente…"}
            </p>
          ) : thread.messages.length === 0 ? (
            <p className="text-sm text-slate-500">
              Escribe tu consulta: por ejemplo, el estado de una devolución o cómo rastrear un envío.
            </p>
          ) : null}
          <ol role="log" aria-live="polite" aria-label="Mensajes de la conversación" className="space-y-3">
            {thread.messages.map((message) => (
              <ChatBubble key={message.message_id} message={message} />
            ))}
          </ol>
          {thread.awaitingReply ? (
            <p className="mt-3 text-sm text-slate-500">El agente está consultando sus fuentes…</p>
          ) : null}
          <div ref={endRef} />
        </div>

        <form onSubmit={handleSubmit} noValidate className="mt-4 space-y-3">
          <div>
            <label htmlFor="chat-message" className="block text-sm font-semibold text-slate-800">
              {generating ? "Escribe para interrumpir y redirigir al agente" : "Tu mensaje"}
            </label>
            <textarea
              id="chat-message"
              name="chat-message"
              rows={2}
              maxLength={CHAT_MESSAGE_MAX_LENGTH}
              value={draft}
              onChange={(event) => {
                setDraft(event.target.value);
                setLocalError(null);
              }}
              onKeyDown={handleKeyDown}
              aria-invalid={Boolean(error)}
              aria-describedby={error ? "chat-error" : "chat-hint"}
              placeholder="Ej.: quiero devolver un pedido que recibí ayer"
              className={`mt-2 block w-full rounded-lg border bg-white px-4 py-3 text-base text-slate-900 shadow-sm focus:outline-none focus:ring-2 focus:ring-cyan-500 ${
                error ? "border-rose-400" : "border-slate-300"
              }`}
            />
            {error ? (
              <p id="chat-error" role="alert" className="mt-1.5 text-sm font-medium text-rose-700">
                {error}
              </p>
            ) : (
              <p id="chat-hint" className="mt-1.5 text-sm text-slate-500">
                Intro envía · Mayús + Intro añade una línea.
              </p>
            )}
          </div>
          <button
            type="submit"
            disabled={!canSend}
            className={`rounded-md px-5 py-2.5 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60 ${
              generating ? "bg-amber-600 hover:bg-amber-500" : "bg-slate-900 hover:bg-slate-800"
            }`}
          >
            {generating ? "Interrumpir y enviar" : "Enviar"}
          </button>
        </form>
      </Panel>
    </div>
  );
}
