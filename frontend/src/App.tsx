import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from 'react';
import { Telemetry } from './Telemetry';
import { useChat } from './useChat';
import type { ChatRequest } from './types';

function Arrow() {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <path
        d="M10 15V5m0 0L5 10m5-5 5 5"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export default function App({ sessionId }: { sessionId: string }) {
  const [draft, setDraft] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('');
  const [promptEdited, setPromptEdited] = useState(false);
  const input = useRef<HTMLTextAreaElement>(null);
  const conversation = useRef<HTMLElement>(null);
  const followsLatest = useRef(true);
  const wasPending = useRef(false);
  const composing = useRef(false);
  const { turns, pending, failedTurn, send, editFailed } = useChat();
  const characterCount = Array.from(draft.trim()).length;
  const tooLong = characterCount > 4000;
  const canSend = !!characterCount && !tooLong && !pending && !failedTurn;

  useLayoutEffect(() => {
    const area = conversation.current;
    if (area && followsLatest.current) area.scrollTop = area.scrollHeight;
  }, [turns, pending]);

  useEffect(() => {
    if (wasPending.current && !pending && !failedTurn) {
      input.current?.focus({ preventScroll: true });
    }
    wasPending.current = pending;
  }, [pending, failedTurn]);

  function trackReadingPosition() {
    const area = conversation.current;
    if (!area) return;
    followsLatest.current =
      area.scrollHeight - area.scrollTop - area.clientHeight < 48;
  }

  function submit(event?: FormEvent) {
    event?.preventDefault();
    if (!canSend) return;
    const request: ChatRequest = {
      session_id: sessionId,
      message: draft.trim(),
    };
    if (promptEdited) request.system_prompt = systemPrompt;
    setDraft('');
    void send(request);
  }

  function handleKey(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (
      event.key === 'Enter' &&
      !event.shiftKey &&
      !event.nativeEvent.isComposing &&
      !composing.current &&
      event.keyCode !== 229
    ) {
      event.preventDefault();
      submit();
    }
  }

  function edit() {
    const request = editFailed();
    if (!request) return;
    setDraft(request.message);
    setSystemPrompt(request.system_prompt ?? '');
    setPromptEdited(request.system_prompt !== undefined);
    window.requestAnimationFrame(() =>
      input.current?.focus({ preventScroll: true }),
    );
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#chat-input">
        Skip to message
      </a>
      <header className="site-header">
        <div className="wordmark">
          <span className="brand-mark" aria-hidden="true">
            ↗
          </span>
          lyftr<span className="brand-period">.</span>
        </div>
        <p>A little clarity, one message at a time.</p>
      </header>
      <main className="chat-layout">
        <section
          ref={conversation}
          onScroll={trackReadingPosition}
          className="conversation"
          aria-label="Conversation"
          tabIndex={0}
        >
          {turns.length === 0 ? (
            <div className="empty-state">
              <span className="empty-symbol" aria-hidden="true">
                ✦
              </span>
              <p className="eyebrow">A fresh conversation</p>
              <h1>What’s on your mind?</h1>
              <p className="empty-description">
                Ask a question, follow an idea, or work through a problem.
              </p>
              <p className="empty-hint">Start with a message below.</p>
            </div>
          ) : (
            <div
              role="log"
              aria-live="polite"
              aria-relevant="additions text"
              aria-label="Messages"
            >
              <h1 className="visually-hidden">Your conversation</h1>
              {turns.map((turn) => (
                <div className="turn" key={turn.id}>
                  <article
                    className="message user-message"
                    aria-label="Your message"
                  >
                    <h2 className="speaker">
                      <span
                        className="speaker-dot user-dot"
                        aria-hidden="true"
                      />
                      You
                    </h2>
                    <p className="message-text">{turn.request.message}</p>
                  </article>
                  {turn.response && (
                    <article
                      className="message assistant-message"
                      data-testid="assistant-message"
                      aria-label="Assistant reply"
                    >
                      <h2 className="speaker">
                        <span className="speaker-dot" aria-hidden="true" />
                        Lyftr
                      </h2>
                      <p className="message-text">{turn.response.reply}</p>
                      <Telemetry metadata={turn.response.metadata} />
                    </article>
                  )}
                  {turn.error && (
                    <div className="chat-error" role="alert">
                      <p className="error-title">Couldn’t send that message</p>
                      <p>{turn.error}</p>
                      <div className="error-actions">
                        <button
                          type="button"
                          className="retry-button"
                          onClick={() => void send(turn.request, turn.id)}
                          disabled={pending}
                        >
                          Try again
                        </button>
                        <button
                          type="button"
                          className="edit-button"
                          onClick={edit}
                          disabled={pending}
                        >
                          Edit message
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
          {pending && (
            <p className="thinking" role="status">
              <span className="thinking-dot" aria-hidden="true" />
              Thinking…
            </p>
          )}
        </section>
        <div className="composer-area">
          <details className="prompt-settings">
            <summary>
              <span>Session instructions</span>
              <span className="optional">Optional</span>
              <svg viewBox="0 0 16 16" aria-hidden="true">
                <path
                  d="m4 6 4 4 4-4"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.5"
                />
              </svg>
            </summary>
            <div className="prompt-content">
              <label htmlFor="system-prompt-input">System prompt</label>
              <textarea
                id="system-prompt-input"
                data-testid="system-prompt-input"
                rows={3}
                value={systemPrompt}
                placeholder="For example: answer in short, practical steps."
                disabled={pending}
                onChange={(event) => {
                  setSystemPrompt(event.target.value);
                  setPromptEdited(true);
                }}
                aria-describedby="prompt-help"
              />
              <p id="prompt-help">
                Set a tone or a way of answering for this conversation.
              </p>
            </div>
          </details>
          <form
            className="composer"
            onSubmit={submit}
            aria-label="Send a message"
          >
            <label className="visually-hidden" htmlFor="chat-input">
              Message
            </label>
            <textarea
              ref={input}
              id="chat-input"
              data-testid="chat-input"
              rows={3}
              value={draft}
              placeholder={
                failedTurn
                  ? 'Retry or edit your last message to continue.'
                  : 'Write your message…'
              }
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={handleKey}
              onCompositionStart={() => {
                composing.current = true;
              }}
              onCompositionEnd={() => {
                composing.current = false;
              }}
              disabled={pending || !!failedTurn}
              aria-invalid={tooLong}
              aria-describedby={
                tooLong
                  ? 'message-help character-count message-error'
                  : 'message-help character-count'
              }
            />
            <div className="composer-footer">
              <span
                className={
                  tooLong ? 'character-count over-limit' : 'character-count'
                }
                id="character-count"
              >
                {characterCount.toLocaleString('en-US')} / 4,000
              </span>
              <button
                type="submit"
                className="send-button"
                data-testid="send-button"
                disabled={!canSend}
              >
                <span>{pending ? 'Sending' : 'Send'}</span>
                <Arrow />
              </button>
            </div>
          </form>
          {tooLong && (
            <p id="message-error" className="validation-error" role="alert">
              Keep your message to 4,000 characters or fewer.
            </p>
          )}
          <p className="composer-hint" id="message-help">
            <span>
              Enter to send <span aria-hidden="true">·</span> Shift + Enter for
              a new line
            </span>
            <span>New session on reload</span>
          </p>
        </div>
      </main>
    </div>
  );
}
