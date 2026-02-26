export interface RealtimeAgent {
  agent: number;
  similarity_threshold: string;
  search_limit: number;
  wake_word: string | null;
  stop_prompt: string | null;

  language: string | null;
  voice_recognition_prompt: string | null;
  voice: string;
}

export interface UpdateRealtimeAgentRequest {
  agent: number;
  similarity_threshold?: string;
  search_limit?: number;
  wake_word?: string;
  stop_prompt?: string;
  language?: string;
  voice_recognition_prompt?: string;
  voice?: string;
}
export interface CreateRealtimeAgentRequest {
  agent: number;
  similarity_threshold?: string;
  search_limit?: number;
  wake_word?: string;
  stop_prompt?: string;
  language?: string;
  voice_recognition_prompt?: string;
  voice?: string;
}
