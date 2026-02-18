export interface EmbeddingModel {
  id: number;
  name: string;
  predefined: boolean;
  deployment?: string | null;
  base_url?: string | null;
  embedding_provider?: number;
  is_visible: boolean;
  is_custom: boolean;
}

export interface CreateEmbeddingModelRequest {
  name: string;
  description?: string | null;
  base_url?: string | null;
  deployment?: string | null;
  is_visible: boolean;
  is_custom: boolean;
  predefined?: boolean;
  embedding_provider: number;
}
