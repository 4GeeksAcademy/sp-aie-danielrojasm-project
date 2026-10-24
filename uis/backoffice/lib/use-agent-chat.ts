"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { getUserMessage } from "@/lib/api-client";
import {
  ChatConnection,
  chatThreadReducer,
  createChatSession,
  emptyThread,
  getChatSession,
  type ChatConnectionStatus,
  type ChatThread,
} from "@/lib/agent-chat";

/** Última conversación de este navegador, para retomarla al volver a la vista. */
const SESSION_STORAGE_KEY = "trackflow_cx_chat_session";
const SESSION_ERROR = "No se pudo abrir la conversación con el agente. Recarga la página para reintentar.";

function readStoredSession(): string | null {
  try {
    return window.localStorage.getItem(SESSION_STORAGE_KEY);
  } catch {
    return null;
  }
}

function storeSession(sessionId: string | null): void {
  try {
    if (sessionId) window.localStorage.setItem(SESSION_STORAGE_KEY, sessionId);
    else window.localStorage.removeItem(SESSION_STORAGE_KEY);
  } catch {
    // Sin almacenamiento (modo privado): la conversación solo dura lo que la pestaña.
  }
}

/** La sesión guardada si sigue existiendo; si no, una nueva. */
async function resolveSession(stored: string | null): Promise<string> {
  if (stored) {
    try {
      return (await getChatSession(stored)).session_id;
    } catch {
      // Caducada o de otro usuario: se abre otra.
    }
  }
  return (await createChatSession()).session_id;
}

export interface AgentChat {
  sessionId: string | null;
  thread: ChatThread;
  status: ChatConnectionStatus;
  /** La sesión no se pudo abrir o la conexión se cerró sin reintento. */
  fatalError: string | null;
  /** El agente está respondiendo: un mensaje nuevo lo interrumpe. */
  generating: boolean;
  /** Envía el mensaje (o interrumpe y redirige). `false` si no hay conexión lista. */
  send: (text: string) => boolean;
  startNewConversation: () => void;
  dismissError: () => void;
}

export function useAgentChat(): AgentChat {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const connection = useRef<ChatConnection | null>(null);
  const [thread, dispatch] = useReducer(chatThreadReducer, emptyThread);
  const [status, setStatus] = useState<ChatConnectionStatus>({
    state: "connecting",
    attempt: 0,
    retryInMs: null,
  });
  const [fatalError, setFatalError] = useState<string | null>(null);
  const [resolveCount, setResolveCount] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const stored = resolveCount === 0 ? readStoredSession() : null;
    resolveSession(stored)
      .then((id) => {
        if (cancelled) return;
        storeSession(id);
        setSessionId(id);
      })
      .catch((error: unknown) => {
        if (!cancelled) setFatalError(getUserMessage(error, SESSION_ERROR));
      });
    return () => {
      cancelled = true;
    };
  }, [resolveCount]);

  useEffect(() => {
    if (!sessionId) return;
    const chat = new ChatConnection({
      sessionId,
      onEvent: dispatch,
      onStatus: setStatus,
      onDisconnected: () => dispatch({ event: "disconnected" }),
      onSessionMissing: () => {
        storeSession(null);
        setSessionId(null);
        setResolveCount((count) => count + 1);
      },
      onFatal: setFatalError,
    });
    connection.current = chat;
    const goOnline = () => chat.retryNow();
    window.addEventListener("online", goOnline);
    chat.start();
    return () => {
      window.removeEventListener("online", goOnline);
      chat.stop();
      connection.current = null;
    };
  }, [sessionId]);

  const generating = thread.streaming !== null || thread.awaitingReply;

  const send = useCallback(
    (text: string) => {
      const value = text.trim();
      if (!connection.current || !sessionId || !thread.ready || !value) return false;
      return connection.current.send(
        generating
          ? { event: "interrupt_requested", data: { session_id: sessionId, new_input: value } }
          : { event: "user_message", data: { session_id: sessionId, text: value } },
      );
    },
    [sessionId, thread.ready, generating],
  );

  const startNewConversation = useCallback(() => {
    storeSession(null);
    setSessionId(null);
    setFatalError(null);
    dispatch({ event: "reset" });
    setResolveCount((count) => count + 1);
  }, []);

  const dismissError = useCallback(() => dispatch({ event: "dismiss_error" }), []);

  return { sessionId, thread, status, fatalError, generating, send, startNewConversation, dismissError };
}
