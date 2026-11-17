import { SystemOneConfig } from '@shared/models';

import { PromptConfig } from '../../../core/models/classification-decision-table.model';
import { CDT_DEFAULT_LLM_LABEL, CDT_NO_SYSTEM_ONE_CONFIG_LABEL } from './cdt.constants';

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

/**
 * Resolves the model label of a prompt entry: the System One config's name for a
 * System One entry (`CDT_NO_SYSTEM_ONE_CONFIG_LABEL` when none is set or it no
 * longer exists), the LLM label otherwise.
 */
export function resolvePromptModelLabel(
    prompt: PromptConfig,
    llmOptions: ReadonlyArray<{ id: number; label: string }>,
    systemOneConfigs: ReadonlyArray<SystemOneConfig>
): string {
    if (prompt.kind !== 'system_one') {
        return resolveLlmLabel(prompt.llm_config, llmOptions);
    }
    const config = systemOneConfigs.find((candidate) => candidate.id === prompt.system_one_config);
    return config?.custom_name ?? CDT_NO_SYSTEM_ONE_CONFIG_LABEL;
}
