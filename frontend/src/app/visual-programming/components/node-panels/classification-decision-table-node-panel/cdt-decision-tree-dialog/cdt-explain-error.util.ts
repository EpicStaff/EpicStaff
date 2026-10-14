import { HttpErrorResponse } from '@angular/common/http';

import { CDT_TREE_COPY } from './cdt-decision-tree.constants';

/**
 * The explain endpoint's error codes, each with what Explain Step and Explain All
 * say for it: 404 for a model that is gone (deleted, another organization's, or
 * unusable), 422 for one with no key whose every batch failed, 502 for a keyed
 * one that failed upstream.
 */
const EXPLAIN_ERROR_MESSAGES: ReadonlyMap<string, string> = new Map([
    ['cdt_explain_llm_config_not_found', CDT_TREE_COPY.explainModelGone],
    ['cdt_explain_llm_config_missing_key', CDT_TREE_COPY.explainNoApiKey],
    ['cdt_explain_upstream_failed', CDT_TREE_COPY.explainUpstreamFailed],
]);

/**
 * What a failed explain request says, for Explain Step and Explain All alike.
 * Keyed on the backend's error codes, not the status. Neither is handled by an
 * interceptor: `forbidden` covers 403 and `validation-errors` only annotates 4xx.
 */
export function explainErrorMessage(error: HttpErrorResponse): string {
    const code: unknown = (error.error as { code?: unknown } | null)?.code;
    const message = typeof code === 'string' ? EXPLAIN_ERROR_MESSAGES.get(code) : undefined;
    return message ?? CDT_TREE_COPY.explainFailed;
}
