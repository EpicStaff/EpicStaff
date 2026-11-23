/**
 * The field labels the API puts in front of a field's message (`base_url: …`, nested `python_code: secret_ids: …`, or
 * an error's dotted `attr` such as `ngrok_config.auth_token_secret_id: …`), at the start of the text or after the
 * "; " that joins several messages.
 */
const FIELD_PREFIX = /(^|; )((?:[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)*: )+)/g;
const FIELD_LABEL = /([a-z][a-z0-9_]*(?:\.[a-z0-9_]+)*): /g;
/** A list index in a dotted path (`prompt_configs.1.result_variable`); not named back to the user. */
const LIST_INDEX = /^\d+$/;

/** Words of a field name written as acronyms; matched whole, between underscores. */
const ACRONYMS: ReadonlyMap<string, string> = new Map([
    ['api', 'API'],
    ['url', 'URL'],
    ['llm', 'LLM'],
    ['id', 'ID'],
]);

/**
 * Reads a server error message as a sentence: each leading field label becomes words (`api_key_secret_id:` →
 * `API key secret:`, `base_url:` → `Base URL:`), each part of a dotted path one label of its own
 * (`ngrok_config.auth_token_secret_id:` → `Ngrok config: Auth token secret:`, list indexes left out), and the first
 * letter is capitalised. Nothing else in the message changes case.
 */
export function humanizeErrorMessage(message: string | null | undefined): string {
    if (!message) return '';
    const labelled = message.replace(
        FIELD_PREFIX,
        (_match, start: string, prefix: string) =>
            start + prefix.replace(FIELD_LABEL, (_label, path: string) => pathLabels(path))
    );
    return capitalize(labelled);
}

function pathLabels(path: string): string {
    return path
        .split('.')
        .filter((segment) => !LIST_INDEX.test(segment))
        .map((field) => `${fieldLabel(field)}: `)
        .join('');
}

function fieldLabel(field: string): string {
    const words = field.replace(/_id$/, '').split('_');
    return capitalize(words.map((word) => ACRONYMS.get(word) ?? word).join(' '));
}

function capitalize(text: string): string {
    return text.charAt(0).toUpperCase() + text.slice(1);
}
