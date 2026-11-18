import { SystemOneProvider } from '@shared/models';

/** System One's providers with their UI names; the LLM Library groups System One configs by them. */
export const SYSTEM_ONE_PROVIDERS: readonly { key: SystemOneProvider; label: string }[] = [
    { key: 'typesafe', label: 'TypeSafe' },
    { key: 'openai', label: 'OpenAI' },
    { key: 'llm', label: 'LLM' },
];
