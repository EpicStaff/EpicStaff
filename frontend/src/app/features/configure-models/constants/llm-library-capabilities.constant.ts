import { SelectItem } from '@shared/components';

/** System One's name, as its section heading and the Capabilities filter show it. */
export const SYSTEM_ONE_LABEL = 'System One';

/** The LLM Library's Capabilities filter: all sections (null), or one of them, by section key. */
export const LLM_LIBRARY_CAPABILITIES: SelectItem[] = [
    { name: 'All capabilities', value: null },
    { name: 'LLM', value: 'llm' },
    { name: 'Embedding', value: 'embedding' },
    { name: 'Realtime', value: 'voice' },
    { name: SYSTEM_ONE_LABEL, value: 'system_one' },
];
