import { GraphRagSearchConfig } from '@shared/models';

export function buildGraphSearchConfig(
    formValue: GraphRagSearchConfig,
    stored: GraphRagSearchConfig | null | undefined
): GraphRagSearchConfig {
    const { basic, local, global, drift } = formValue;
    return {
        ...formValue,
        basic: basic && { ...basic, prompt: basic.prompt || null },
        local: local && { ...local, prompt: local.prompt || null },
        global: global && {
            ...global,
            map_prompt: global.map_prompt || null,
            reduce_prompt: global.reduce_prompt || null,
            knowledge_prompt: global.knowledge_prompt || null,
        },
        drift: drift && {
            reduce_temperature: stored?.drift?.reduce_temperature,
            local_search_temperature: stored?.drift?.local_search_temperature,
            ...drift,
            prompt: drift.prompt || null,
            reduce_prompt: drift.reduce_prompt || null,
        },
    };
}
