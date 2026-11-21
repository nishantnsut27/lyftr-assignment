import { useEffect, useRef, useState } from 'react';
import { sendChat } from './api';
import { createSessionId } from './session';
import type { ChatRequest, ChatTurn } from './types';

export function useChat() {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [pending, setPending] = useState(false);
  const [failedTurn, setFailedTurn] = useState<ChatTurn | null>(null);
  const activeRequest = useRef<AbortController | null>(null);

  useEffect(() => () => activeRequest.current?.abort(), []);

  async function send(request: ChatRequest, retryId?: string): Promise<void> {
    // The ref guards duplicate events before React has rendered the disabled controls.
    if (activeRequest.current) return;
    const controller = new AbortController();
    activeRequest.current = controller;
    const id = retryId ?? createSessionId();
    setPending(true);
    setFailedTurn(null);
    setTurns((current) =>
      retryId
        ? current.map((turn) => (turn.id === id ? { id, request } : turn))
        : [...current, { id, request }],
    );
    const timeout = window.setTimeout(
      () => controller.abort('timeout'),
      120_000,
    );
    try {
      const response = await sendChat(request, controller.signal);
      setTurns((current) =>
        current.map((turn) =>
          turn.id === id ? { id, request, response } : turn,
        ),
      );
    } catch (error) {
      if (controller.signal.aborted && controller.signal.reason !== 'timeout')
        return;
      const message =
        controller.signal.reason === 'timeout'
          ? 'The reply is taking longer than expected. Please try again.'
          : error instanceof Error
            ? error.message
            : 'Something went wrong. Please try again.';
      const failed = { id, request, error: message };
      setFailedTurn(failed);
      setTurns((current) =>
        current.map((turn) => (turn.id === id ? failed : turn)),
      );
    } finally {
      window.clearTimeout(timeout);
      activeRequest.current = null;
      setPending(false);
    }
  }

  function editFailed(): ChatRequest | undefined {
    if (!failedTurn || activeRequest.current) return;
    setTurns((current) => current.filter((turn) => turn.id !== failedTurn.id));
    setFailedTurn(null);
    return failedTurn.request;
  }

  return { turns, pending, failedTurn, send, editFailed };
}
