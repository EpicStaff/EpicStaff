import { SystemOneProvider } from '@shared/models';

/** System One's providers, in the order the config form offers them, with their UI names. */
export const SYSTEM_ONE_PROVIDERS: readonly { key: SystemOneProvider; label: string }[] = [
    { key: 'typesafe', label: 'TypeSafe' },
    { key: 'llm', label: 'LLM' },
];
