import { SystemOneConfig } from '@shared/models';

import { PromptConfig } from '../../../core/models/classification-decision-table.model';
import { resolvePromptModelLabel } from './cdt-llm-label.util';

describe('resolvePromptModelLabel', () => {
    const llmOptions = [{ id: 2, label: 'GPT-4o' }];
    const systemOneConfigs = [{ id: 7, custom_name: 'jev' } as SystemOneConfig];

    function prompt(overrides: Partial<PromptConfig>): PromptConfig {
        return {
            prompt_text: '',
            llm_config: null,
            output_schema: null,
            result_variable: 'result',
            variable_mappings: {},
            ...overrides,
        };
    }

    it.each([
        ['an LLM prompt shows its LLM label', { llm_config: 2 }, 'GPT-4o'],
        ['a prompt of kind llm shows its LLM label', { kind: 'llm' as const, llm_config: 2 }, 'GPT-4o'],
        ['an LLM prompt with no LLM shows the default label', { llm_config: null }, 'Default LLM'],
        ['a System One entry shows its config name', { kind: 'system_one' as const, system_one_config: 7 }, 'jev'],
        [
            'a System One entry with no config says so',
            { kind: 'system_one' as const, system_one_config: null },
            'No config',
        ],
        [
            'a System One entry with a deleted config says so',
            { kind: 'system_one' as const, system_one_config: 8 },
            'No config',
        ],
    ])('%s', (_name, overrides, expected) => {
        expect(resolvePromptModelLabel(prompt(overrides), llmOptions, systemOneConfigs)).toBe(expected);
    });
});
