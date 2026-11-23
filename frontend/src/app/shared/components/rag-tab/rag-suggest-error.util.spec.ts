import { HttpErrorResponse } from '@angular/common/http';

import { suggestErrorState } from './rag-suggest-error.util';

const CONNECTION_MESSAGE = "Couldn't load token limits. Check your connection and try again.";
const NOT_INDEXED_MESSAGE = "This collection isn't indexed yet. Suggestions are available once indexing completes.";
const NO_LLM_MESSAGE = 'This RAG has no LLM config. Select one in Update RAG.';

function envelope(code: string): unknown {
    return { type: 'client_error', errors: [{ code, detail: 'Refused.', attr: null, context: null }] };
}

describe('suggestErrorState', () => {
    it.each([
        ['an index that is not ready', 409, envelope('rag_index_not_ready'), NOT_INDEXED_MESSAGE, true],
        ['a GraphRAG with no LLM config', 409, envelope('graph_rag_llm_not_configured'), NO_LLM_MESSAGE, false],
        ['knowledge metrics temporarily unavailable', 409, envelope('rag_error'), CONNECTION_MESSAGE, true],
        ['a code outside the error envelope', 409, { code: 'graph_rag_llm_not_configured' }, CONNECTION_MESSAGE, true],
        ['a network failure', 0, null, CONNECTION_MESSAGE, true],
        ['a server error with an HTML body', 500, '<html><body>Bad Gateway</body></html>', CONNECTION_MESSAGE, true],
        ['a body without a code', 409, { error: 'Something went wrong' }, CONNECTION_MESSAGE, true],
        ['an empty body', 409, null, CONNECTION_MESSAGE, true],
    ])('for %s', (_case: string, status: number, body: unknown, message: string, canRetry: boolean) => {
        const error = new HttpErrorResponse({ status, error: body });

        expect(suggestErrorState(error)).toEqual({ message, canRetry });
    });
});
