import {
  useEffect,
  useRef,
  useState,
  type RefObject,
  type KeyboardEvent,
} from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { ArrowUp } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useMotionPreferences } from './use-motion-preferences';

const placeholders = [
  'Explain a concept',
  'Help me solve a problem',
  'Explore an idea',
  'Ask a follow-up question',
];

interface AIComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onKeyDown: (event: KeyboardEvent<HTMLTextAreaElement>) => void;
  onCompositionStart: () => void;
  onCompositionEnd: () => void;
  inputRef: RefObject<HTMLTextAreaElement | null>;
  disabled: boolean;
  canSend: boolean;
  pending: boolean;
  failed: boolean;
  characterCount: number;
  tooLong: boolean;
}

export function AIComposer({
  value,
  onChange,
  onSubmit,
  onKeyDown,
  onCompositionStart,
  onCompositionEnd,
  inputRef,
  disabled,
  canSend,
  pending,
  failed,
  characterCount,
  tooLong,
}: AIComposerProps) {
  const [focused, setFocused] = useState(false);
  const [hovered, setHovered] = useState(false);
  const [placeholderIndex, setPlaceholderIndex] = useState(0);
  const [sendEffect, setSendEffect] = useState(false);
  const effectTimer = useRef<number | undefined>(undefined);
  const blurTimer = useRef<number | undefined>(undefined);
  const { reducedMotion, hidden } = useMotionPreferences();
  const expanded = focused || hovered || value.length > 0;
  useEffect(() => () => window.clearTimeout(blurTimer.current), []);

  useEffect(() => {
    if (reducedMotion || hidden || value || disabled) return;
    const timer = window.setInterval(
      () => setPlaceholderIndex((index) => (index + 1) % placeholders.length),
      3600,
    );
    return () => window.clearInterval(timer);
  }, [reducedMotion, hidden, value, disabled]);

  useEffect(() => {
    if (!pending || reducedMotion || hidden) return;
    setSendEffect(true);
    effectTimer.current = window.setTimeout(() => setSendEffect(false), 420);
    return () => {
      window.clearTimeout(effectTimer.current);
      setSendEffect(false);
    };
  }, [pending, reducedMotion, hidden]);

  return (
    <form
      className={cn(
        'composer',
        expanded && 'composer-expanded',
        sendEffect && 'composer-sent',
      )}
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocusCapture={() => {
        window.clearTimeout(blurTimer.current);
        setFocused(true);
      }}
      onBlurCapture={(event) => {
        if (event.currentTarget.contains(event.relatedTarget)) return;
        // Let the next control receive its click before the composer changes height.
        blurTimer.current = window.setTimeout(() => setFocused(false), 150);
      }}
      aria-label="Send a message"
    >
      <div className="composer-input-wrap">
        <label className="visually-hidden" htmlFor="chat-input">
          Message
        </label>
        <textarea
          ref={inputRef}
          id="chat-input"
          data-testid="chat-input"
          rows={1}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={onKeyDown}
          onCompositionStart={onCompositionStart}
          onCompositionEnd={onCompositionEnd}
          disabled={disabled}
          placeholder="Write your message…"
          aria-invalid={tooLong}
          aria-describedby={
            tooLong
              ? 'message-help character-count message-error'
              : 'message-help character-count'
          }
        />
        {!value && (
          <div className="cycling-placeholder" aria-hidden="true">
            <AnimatePresence mode="wait" initial={false}>
              <motion.span
                key={failed ? 'failed' : pending ? 'pending' : placeholderIndex}
                initial={
                  reducedMotion
                    ? false
                    : { opacity: 1, filter: 'blur(3px)', y: 3 }
                }
                animate={{ opacity: 1, filter: 'blur(0px)', y: 0 }}
                exit={
                  reducedMotion
                    ? undefined
                    : { opacity: 1, filter: 'blur(3px)', y: -3 }
                }
                transition={{ duration: reducedMotion ? 0 : 0.22 }}
              >
                {failed
                  ? 'Retry or edit your last message.'
                  : pending
                    ? 'Making room for a little clarity…'
                    : placeholders[placeholderIndex]}
              </motion.span>
            </AnimatePresence>
          </div>
        )}
      </div>
      <div className="composer-footer">
        <span
          className={cn('character-count', tooLong && 'over-limit')}
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
          <ArrowUp size={20} aria-hidden="true" />
        </button>
      </div>
    </form>
  );
}
