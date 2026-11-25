import { SelectItem } from '@shared/components';

import { LibrarySectionKey } from '../models/llm-library.model';

/** System One's name, as its section heading and the Capabilities filter show it. */
export const SYSTEM_ONE_LABEL = 'System One';

/** The config sections of the AI Models page in their order, with their headings. */
export const AI_MODELS_SECTION_TITLES: Readonly<Record<LibrarySectionKey, string>> = {
    llm: 'LLM',
    embedding: 'Embeddings',
    voice: 'Voice',
    system_one: SYSTEM_ONE_LABEL,
};

/** The AI Models page's Capabilities filter: all sections (null), or one of them, by section key. */
export const LLM_LIBRARY_CAPABILITIES: SelectItem[] = [
    { name: 'All capabilities', value: null },
    { name: AI_MODELS_SECTION_TITLES.llm, value: 'llm' },
    { name: AI_MODELS_SECTION_TITLES.embedding, value: 'embedding' },
    { name: AI_MODELS_SECTION_TITLES.voice, value: 'voice' },
    { name: SYSTEM_ONE_LABEL, value: 'system_one' },
];

/** What "Add Model" offers: a config of one section's kind, by section key. */
export const AI_MODELS_ADD_OPTIONS: readonly { key: LibrarySectionKey; label: string }[] = [
    { key: 'llm', label: AI_MODELS_SECTION_TITLES.llm },
    { key: 'embedding', label: 'Embedding' },
    { key: 'voice', label: AI_MODELS_SECTION_TITLES.voice },
    { key: 'system_one', label: SYSTEM_ONE_LABEL },
];
