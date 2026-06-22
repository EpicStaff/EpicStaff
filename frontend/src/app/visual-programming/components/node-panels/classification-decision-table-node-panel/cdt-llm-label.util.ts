import { CDT_DEFAULT_LLM_LABEL } from './cdt.constants';

/**
 * Resolves the display label for an LLM config id.
 *
 * Returns the matching `label` from `options` when found, or
 * `CDT_DEFAULT_LLM_LABEL` when `llmId` is null/undefined or not present in the list.
 */
export function resolveLlmLabel(
    llmId: number | null | undefined,
    options: ReadonlyArray<{ id: number; label: string }>
): string {
    if (llmId == null) {
        return CDT_DEFAULT_LLM_LABEL;
    }
    const found = options.find((l) => l.id === llmId);
    return found ? found.label : CDT_DEFAULT_LLM_LABEL;
}
