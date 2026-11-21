import type { ChatRequest, ChatResponse } from './types';

export class ChatError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
  ) {
    super(message);
    this.name = 'ChatError';
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function isTokenCount(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}

function isChatResponse(value: unknown): value is ChatResponse {
  if (
    !isRecord(value) ||
    typeof value.session_id !== 'string' ||
    typeof value.reply !== 'string' ||
    !value.reply.trim() ||
    !isRecord(value.metadata)
  ) {
    return false;
  }
  const metadata = value.metadata;
  const cached = metadata.resolution_source === 'LLM_CACHE';
  const live = metadata.resolution_source === 'LIVE_INFERENCE';
  return (
    (cached || live) &&
    typeof metadata.model === 'string' &&
    !!metadata.model.trim() &&
    isTokenCount(metadata.latency_ms) &&
    isTokenCount(metadata.input_tokens) &&
    isTokenCount(metadata.output_tokens) &&
    isTokenCount(metadata.fallback_attempts) &&
    (cached
      ? metadata.key_id === null && metadata.fallback_attempts === 0
      : typeof metadata.key_id === 'string' &&
        /^key_[1-9]\d*$/.test(metadata.key_id))
  );
}

function apiUrl(): string {
  const configured =
    import.meta.env.VITE_API_BASE_URL?.trim() || 'http://localhost:8000';
  try {
    const url = new URL(configured);
    if (
      !['http:', 'https:'].includes(url.protocol) ||
      url.username ||
      url.password ||
      url.search ||
      url.hash
    ) {
      throw new Error();
    }
    return `${url.toString().replace(/\/$/, '')}/chat`;
  } catch {
    throw new ChatError(
      'The assistant isn’t connected yet. Please try again later.',
    );
  }
}

export async function sendChat(
  request: ChatRequest,
  signal: AbortSignal,
): Promise<ChatResponse> {
  let response: Response;
  try {
    response = await fetch(apiUrl(), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
      signal,
      credentials: 'omit',
    });
  } catch (error) {
    if (error instanceof ChatError || signal.aborted) throw error;
    throw new ChatError(
      'Couldn’t reach the assistant. Check your connection and try again.',
    );
  }
  if (!response.ok) {
    if (response.status === 503)
      throw new ChatError(
        'The assistant is busy right now. Please try again.',
        503,
      );
    if (response.status === 422)
      throw new ChatError(
        'That message couldn’t be sent. Check your message and try again.',
        422,
      );
    throw new ChatError(
      'Something went wrong while getting a reply. Please try again.',
      response.status,
    );
  }
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new ChatError(
      'The assistant returned an unreadable reply. Please try again.',
    );
  }
  if (!isChatResponse(body) || body.session_id !== request.session_id) {
    throw new ChatError(
      'The assistant returned an incomplete reply. Please try again.',
    );
  }
  return body;
}
