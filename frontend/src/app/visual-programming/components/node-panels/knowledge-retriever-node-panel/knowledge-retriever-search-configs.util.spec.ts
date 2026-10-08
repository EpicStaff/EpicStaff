import { GraphDriftSearchConfig, GraphRagSearchConfig } from '@shared/models';

import { buildGraphSearchConfig } from './knowledge-retriever-search-configs.util';

const drift: GraphDriftSearchConfig = {
    prompt: '',
    reduce_prompt: '',
    data_max_tokens: 12000,
    reduce_max_tokens: null,
    reduce_max_completion_tokens: null,
    concurrency: 32,
    drift_k_followups: 20,
    primer_folds: 5,
    primer_llm_max_tokens: 12000,
    n_depth: 3,
    community_level: 2,
    local_search_text_unit_prop: 0.9,
    local_search_community_prop: 0.1,
    local_search_top_k_mapped_entities: 10,
    local_search_top_k_relationships: 10,
    local_search_max_data_tokens: 12000,
    local_search_top_p: 1,
    local_search_n: 1,
    local_search_llm_max_gen_tokens: null,
    local_search_llm_max_gen_completion_tokens: null,
};

const formValue: GraphRagSearchConfig = {
    search_method: 'drift',
    basic: { prompt: '', k: 10, max_context_tokens: 12000 },
    local: {
        prompt: 'keep me',
        text_unit_prop: 0.5,
        community_prop: 0.1,
        conversation_history_max_turns: 5,
        max_context_tokens: 12000,
        top_k_entities: 10,
        top_k_relationships: 10,
    },
    global: {
        map_prompt: '',
        reduce_prompt: '',
        knowledge_prompt: '',
        max_context_tokens: 12000,
        data_max_tokens: 12000,
        map_max_length: 1000,
        reduce_max_length: 2000,
        dynamic_community_selection: false,
        dynamic_search_threshold: 1,
        dynamic_search_keep_parent: false,
        dynamic_search_num_repeats: 1,
        dynamic_search_use_summary: false,
        dynamic_search_max_level: 2,
    },
    drift,
};

describe('buildGraphSearchConfig', () => {
    it('sends cleared prompts as null and keeps filled ones', () => {
        const result = buildGraphSearchConfig(formValue, null);

        expect(result.basic?.prompt).toBeNull();
        expect(result.local?.prompt).toBe('keep me');
        expect(result.global?.map_prompt).toBeNull();
        expect(result.global?.reduce_prompt).toBeNull();
        expect(result.global?.knowledge_prompt).toBeNull();
        expect(result.drift?.prompt).toBeNull();
        expect(result.drift?.reduce_prompt).toBeNull();
    });

    it('carries stored drift temperatures the form has no controls for', () => {
        const stored: GraphRagSearchConfig = {
            search_method: 'drift',
            drift: { ...drift, reduce_temperature: 0.3, local_search_temperature: 0.7 },
        };

        const result = buildGraphSearchConfig(formValue, stored);

        expect(result.drift?.reduce_temperature).toBe(0.3);
        expect(result.drift?.local_search_temperature).toBe(0.7);
        expect(result.drift?.data_max_tokens).toBe(12000);
    });

    it('leaves sub-configs absent from the form value absent', () => {
        const result = buildGraphSearchConfig({ search_method: 'basic' }, null);

        expect(result.basic).toBeUndefined();
        expect(result.drift).toBeUndefined();
    });
});
