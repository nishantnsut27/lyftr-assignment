import { ChevronDown, Terminal } from 'lucide-react';
import { CopyButton } from './copy-button';

interface SystemPromptEditorProps {
  value: string;
  onChange: (value: string) => void;
  disabled: boolean;
}

export function SystemPromptEditor({
  value,
  onChange,
  disabled,
}: SystemPromptEditorProps) {
  return (
    <details className="prompt-settings">
      <summary>
        <Terminal size={16} aria-hidden="true" />
        <span>Session instructions</span>
        <span className="optional">Optional</span>
        <ChevronDown className="prompt-chevron" size={16} aria-hidden="true" />
      </summary>
      <div className="prompt-content">
        <div className="editor-header">
          <label htmlFor="system-prompt-input">System prompt</label>
          <CopyButton text={value} label="Copy system prompt" />
        </div>
        <textarea
          id="system-prompt-input"
          data-testid="system-prompt-input"
          rows={3}
          value={value}
          placeholder="For example: answer in short, practical steps."
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
          aria-describedby="prompt-help prompt-count"
        />
        <div className="editor-footer">
          <p id="prompt-help">
            Send edits with your next message. Clear to send an empty prompt.
          </p>
          <span id="prompt-count">
            {Array.from(value).length.toLocaleString('en-US')} characters
          </span>
        </div>
      </div>
    </details>
  );
}
