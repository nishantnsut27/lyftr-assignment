import { useEffect, useRef, useState } from 'react';
import { Check, Copy } from 'lucide-react';
import { cn } from '@/lib/utils';

export function CopyButton({
  text,
  label,
  className,
}: {
  text: string;
  label: string;
  className?: string;
}) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle');
  const timer = useRef<number | undefined>(undefined);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      window.clearTimeout(timer.current);
    };
  }, []);

  async function copy() {
    let result: 'copied' | 'failed';
    try {
      await navigator.clipboard.writeText(text);
      result = 'copied';
    } catch {
      result = 'failed';
    }
    if (!mounted.current) return;
    setState(result);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setState('idle'), 2000);
  }
  return (
    <>
      <button
        type="button"
        className={cn('copy-button', className)}
        onClick={() => void copy()}
        aria-label={label}
        data-copied={state === 'copied'}
      >
        {state === 'copied' ? (
          <Check size={14} aria-hidden="true" />
        ) : (
          <Copy size={14} aria-hidden="true" />
        )}
        <span>
          {state === 'copied'
            ? 'Copied'
            : state === 'failed'
              ? 'Try copy'
              : 'Copy'}
        </span>
      </button>
      <span className="visually-hidden" aria-live="polite">
        {state === 'copied'
          ? `${label === 'Copy response' ? 'Response' : 'System prompt'} copied.`
          : state === 'failed'
            ? 'Could not copy. Select and copy the text manually.'
            : ''}
      </span>
    </>
  );
}
