/** Mirrors JEV_MODEL_VERSIONS in src/shared/system_one/constants.py; the first one is the default. */
export const JEV_MODEL_VERSIONS = ['jev-1.14.0', 'jev-1.13.0'] as const;

/** Mirrors OPENAI_DECISIONS_MODELS in src/shared/system_one/constants.py; the first one is the default. */
export const OPENAI_DECISIONS_MODELS = ['gpt-6-luna'] as const;

/** The models each key-based provider offers; the first one is the default. */
export const SYSTEM_ONE_MODELS: Record<'typesafe' | 'openai', readonly string[]> = {
    typesafe: JEV_MODEL_VERSIONS,
    openai: OPENAI_DECISIONS_MODELS,
};
