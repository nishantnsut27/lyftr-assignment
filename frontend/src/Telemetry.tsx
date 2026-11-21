import type { ReplyMetadata } from './types';

export function Telemetry({ metadata }: { metadata: ReplyMetadata }) {
  return (
    <dl className="telemetry" aria-label="Reply metadata">
      <div className="telemetry-source">
        <dt>Source</dt>
        <dd data-testid="meta-source">{metadata.resolution_source}</dd>
      </div>
      <div className="telemetry-model">
        <dt>Model</dt>
        <dd data-testid="meta-model">{metadata.model}</dd>
      </div>
      <div>
        <dt>Latency</dt>
        <dd data-testid="meta-latency">{metadata.latency_ms} ms</dd>
      </div>
      <div>
        <dt>Input tokens</dt>
        <dd data-testid="meta-input-tokens">{metadata.input_tokens}</dd>
      </div>
      <div>
        <dt>Output tokens</dt>
        <dd data-testid="meta-output-tokens">{metadata.output_tokens}</dd>
      </div>
    </dl>
  );
}
