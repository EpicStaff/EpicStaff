import { HttpErrorResponse } from '@angular/common/http';

export interface SuggestErrorState {
    message: string;
    canRetry: boolean;
}

const RETRYABLE_ERROR: SuggestErrorState = {
    message: "Couldn't load token limits. Check your connection and try again.",
    canRetry: true,
};

/**
 * The suggest-search-params error codes with their own message. A collection
 * still indexing finishes on its own, so Retry stays; a GraphRAG with no LLM
 * config needs the user to pick one, so Retry is hidden. Every other failure
 * (`rag_error`, a network error, an unknown body) falls back to a retryable one.
 */
const SUGGEST_ERROR_STATES: ReadonlyMap<string, SuggestErrorState> = new Map([
    [
        'rag_index_not_ready',
        {
            message: "This collection isn't indexed yet. Suggestions are available once indexing completes.",
            canRetry: true,
        },
    ],
    [
        'graph_rag_llm_not_configured',
        { message: 'This RAG has no LLM config. Select one in Update RAG.', canRetry: false },
    ],
]);

/** What a failed suggest-search-params request says, and whether Retry can help. Keyed on the backend's error code. */
export function suggestErrorState(error: HttpErrorResponse): SuggestErrorState {
    const code: unknown = (error.error as { code?: unknown } | null)?.code;
    const state = typeof code === 'string' ? SUGGEST_ERROR_STATES.get(code) : undefined;
    return state ?? RETRYABLE_ERROR;
}
