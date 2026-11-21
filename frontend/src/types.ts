export interface ChatRequest {
  session_id: string;
  message: string;
  system_prompt?: string;
}

export interface ReplyMetadata {
  resolution_source: 'LIVE_INFERENCE' | 'LLM_CACHE';
  model: string;
  latency_ms: number;
  input_tokens: number;
  output_tokens: number;
  key_id: string | null;
  fallback_attempts: number;
}

export interface ChatResponse {
  session_id: string;
  reply: string;
  metadata: ReplyMetadata;
}

export interface ChatTurn {
  id: string;
  request: ChatRequest;
  response?: ChatResponse;
  error?: string;
}
