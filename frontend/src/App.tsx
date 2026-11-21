import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
} from 'react';
import { UserRound } from 'lucide-react';
import { AIComposer } from '@/components/ui/ai-composer';
import { Brushwork } from '@/components/ui/brushwork';
import { AssistantReply, ReplySkeleton } from '@/components/ui/assistant-reply';
import { MessageNavigation } from '@/components/ui/message-navigation';
import { SystemPromptEditor } from '@/components/ui/system-prompt-editor';
import { useChat } from './useChat';
import type { ChatRequest } from './types';

export default function App({ sessionId }: { sessionId: string }) {
  const [draft, setDraft] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('');
  const [promptEdited, setPromptEdited] = useState(false);
  const [announcement, setAnnouncement] = useState('');
  const input = useRef<HTMLTextAreaElement>(null);
  const conversation = useRef<HTMLElement>(null);
  const followsLatest = useRef(true);
  const wasPending = useRef(false);
  const composing = useRef(false);
  const editFrame = useRef<number | undefined>(undefined);
  const hasMessages = useRef(false);
  const { turns, pending, failedTurn, send, editFailed } = useChat();
  const characterCount = Array.from(draft.trim()).length;
  const tooLong = characterCount > 4000;
  const canSend = !!characterCount && !tooLong && !pending && !failedTurn;
  hasMessages.current = turns.length > 0;

  const followReply = useCallback(() => {
    const area = conversation.current;
    if (area && hasMessages.current && followsLatest.current)
      area.scrollTop = area.scrollHeight;
  }, []);
  useLayoutEffect(followReply, [turns, pending, followReply]);
  useEffect(() => {
    const area = conversation.current;
    if (!area) return;
    const observer = new ResizeObserver(followReply);
    observer.observe(area);
    return () => {
      observer.disconnect();
      window.cancelAnimationFrame(editFrame.current ?? 0);
    };
  }, [followReply]);
  useEffect(() => {
    if (wasPending.current && !pending && !failedTurn)
      input.current?.focus({ preventScroll: true });
    wasPending.current = pending;
  }, [pending, failedTurn]);

  function trackReadingPosition() {
    const area = conversation.current;
    if (!area) return;
    followsLatest.current =
      !hasMessages.current ||
      area.scrollHeight - area.scrollTop - area.clientHeight < 48;
  }
  function submit() {
    if (!canSend) return;
    const request: ChatRequest = {
      session_id: sessionId,
      message: draft.trim(),
    };
    if (promptEdited) request.system_prompt = systemPrompt;
    setDraft('');
    setAnnouncement('');
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
    editFrame.current = window.requestAnimationFrame(() =>
      input.current?.focus({ preventScroll: true }),
    );
  }
  function navigate(id: string) {
    const message = document.getElementById(`message-${id}`);
    if (!message) return;
    followsLatest.current = false;
    message.scrollIntoView({ block: 'start', behavior: 'instant' });
    message.focus({ preventScroll: true });
  }

  return (
    <div className="app-shell">
      <Brushwork />
      <a className="skip-link" href="#chat-input">
        Skip to message
      </a>
      <main className="chat-layout">
        <MessageNavigation turns={turns} onNavigate={navigate} />
        <section
          ref={conversation}
          onScroll={trackReadingPosition}
          className={
            turns.length ? 'conversation' : 'conversation conversation-empty'
          }
          aria-label="Conversation"
          tabIndex={0}
        >
          <header className="site-header">
            <div className="wordmark">
              <img
                className="brand-mark"
                src="/lyftr-mark.svg"
                width="30"
                height="30"
                alt=""
                aria-hidden="true"
              />
              lyftr<span className="brand-period">.</span>
            </div>
            <p>A little clarity, one message at a time.</p>
          </header>
          <div className="conversation-content">
            {turns.length === 0 ? (
              <div className="empty-state">
                <p className="eyebrow">A fresh conversation</p>
                <h1>
                  What’s on <br />
                  your mind?
                </h1>
                <p className="empty-description">
                  Ask a question, follow an idea, or work through a problem.
                </p>
                <p className="empty-hint">
                  <span aria-hidden="true">↳</span> Start with a message below.
                </p>
              </div>
            ) : (
              <div role="log" aria-live="off" aria-label="Messages">
                <h1 className="visually-hidden">Your conversation</h1>
                {turns.map((turn, index) => (
                  <div className="turn" key={turn.id}>
                    <article
                      id={`message-${turn.id}`}
                      className="message user-message"
                      aria-label="Your message"
                      tabIndex={-1}
                    >
                      <h2 className="speaker">
                        <UserRound size={14} aria-hidden="true" />
                        <span className="visually-hidden">You</span>
                      </h2>
                      <p className="message-text">{turn.request.message}</p>
                    </article>
                    {turn.response && (
                      <AssistantReply
                        response={turn.response}
                        finish={pending || index !== turns.length - 1}
                        onProgress={followReply}
                        onComplete={() =>
                          setAnnouncement(`Reply ${index + 1} complete.`)
                        }
                      />
                    )}
                    {turn.error && (
                      <div className="chat-error" role="alert">
                        <p className="error-title">
                          Couldn’t send that message
                        </p>
                        <p>{turn.error}</p>
                        <div className="error-actions">
                          <button
                            type="button"
                            className="retry-button"
                            onClick={() => {
                              setAnnouncement('');
                              void send(turn.request, turn.id);
                            }}
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
            {pending && <ReplySkeleton />}
          </div>
        </section>
        <div className="composer-area">
          <SystemPromptEditor
            value={systemPrompt}
            disabled={pending}
            onChange={(value) => {
              setSystemPrompt(value);
              setPromptEdited(true);
            }}
          />
          <AIComposer
            value={draft}
            onChange={setDraft}
            onSubmit={submit}
            onKeyDown={handleKey}
            onCompositionStart={() => {
              composing.current = true;
            }}
            onCompositionEnd={() => {
              composing.current = false;
            }}
            inputRef={input}
            disabled={pending || !!failedTurn}
            canSend={canSend}
            pending={pending}
            failed={!!failedTurn}
            characterCount={characterCount}
            tooLong={tooLong}
          />
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
      <p
        className="visually-hidden"
        role="status"
        aria-live="polite"
        aria-atomic="true"
      >
        {pending ? 'Thinking…' : announcement}
      </p>
    </div>
  );
}
