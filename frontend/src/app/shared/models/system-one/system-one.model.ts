import { AuthorshipFields } from '../authorship.model';

export type SystemOneProvider = 'typesafe' | 'llm';

export interface SystemOneConfig extends AuthorshipFields {
    id: number;
    custom_name: string;
    provider: SystemOneProvider;
    /** The Jev version; set for the TypeSafe provider only. */
    model_name: string | null;
    api_key_secret_id: number | null;
    /** The LLM config answering the questions; set for the LLM provider only. */
    llm_config: number | null;
    created_at: string;
}

export type SystemOneConfigWrite = Pick<
    SystemOneConfig,
    'custom_name' | 'provider' | 'model_name' | 'api_key_secret_id' | 'llm_config'
>;

export type SystemOnePromptKind = 'llm' | 'system_one';

export interface NoulQuestion {
    type: 'noul';
    instructions: string;
    criteria?: { true?: string; false?: string } | null;
}

export interface ChoiceQuestion {
    type: 'choice';
    instructions: string;
    criteria: Record<string, string>;
}

export interface ScoreQuestion {
    type: 'score';
    instructions: string;
    /** Levels from low to high; the index is the score. */
    criteria: string[];
}

export type SystemOneQuestion = NoulQuestion | ChoiceQuestion | ScoreQuestion;
