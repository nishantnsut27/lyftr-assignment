import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Telemetry } from '@/Telemetry';
import type { ChatResponse } from '@/types';
import { MarkdownReply } from './markdown-reply';
import { useMotionPreferences } from './use-motion-preferences';
import { CopyButton } from './copy-button';

interface AssistantReplyProps {
  response: ChatResponse;
  finish: boolean;
  onProgress: () => void;
  onComplete: () => void;
}

export function AssistantReply({
  response,
  finish,
  onProgress,
  onComplete,
}: AssistantReplyProps) {
  const { reducedMotion, hidden } = useMotionPreferences();
  const immediate =
    finish ||
    reducedMotion ||
    hidden ||
    response.metadata.resolution_source === 'LLM_CACHE';
  const [visible, setVisible] = useState(immediate ? response.reply : '');
  const announced = useRef(false);
  const completed = useRef(immediate);
  const revealing = !immediate && visible !== response.reply;

  useEffect(() => {
    if (immediate || completed.current) {
      completed.current = true;
      setVisible(response.reply);
      return;
    }
    const characters = Array.from(response.reply);
    const duration = Math.min(1500, Math.max(180, characters.length * 12));
    const start = Date.now();
    const timer = window.setInterval(() => {
      const fraction = Math.min(1, (Date.now() - start) / duration);
      setVisible(
        characters.slice(0, Math.ceil(characters.length * fraction)).join(''),
      );
      if (fraction === 1) {
        completed.current = true;
        window.clearInterval(timer);
      }
    }, 20);
    return () => window.clearInterval(timer);
  }, [immediate, response.reply]);

  useLayoutEffect(onProgress, [visible, onProgress, immediate]);
  useEffect(() => {
    if (!revealing && !announced.current) {
      announced.current = true;
      onComplete();
    }
  }, [revealing, onComplete]);

  return (
    <article
      className="message assistant-message"
      data-testid="assistant-message"
      aria-label="Assistant reply"
    >
      <h2 className="speaker">
        <img
          src="/lyftr-mark.svg"
          width="20"
          height="20"
          alt=""
          aria-hidden="true"
        />
        <span className="visually-hidden">Lyftr</span>
      </h2>
      <div
        className="markdown-content"
        aria-live="off"
        data-revealing={revealing}
      >
        <MarkdownReply content={immediate ? response.reply : visible} />
        {revealing && <span className="reply-cursor" aria-hidden="true" />}
      </div>
      <div className="reply-actions">
        <CopyButton
          text={response.reply}
          label="Copy response"
          className="response-copy"
        />
      </div>
      <Telemetry metadata={response.metadata} />
    </article>
  );
}

export function ReplySkeleton() {
  return (
    <div className="reply-skeleton" aria-hidden="true">
      <span />
      <span />
      <span />
    </div>
  );
}
