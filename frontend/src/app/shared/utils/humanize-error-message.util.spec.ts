import { humanizeErrorMessage } from './humanize-error-message.util';

describe('humanizeErrorMessage', () => {
    it.each([
        [
            'model: Changing where this sends its secrets requires the "Use" permission on Secrets.',
            'Model: Changing where this sends its secrets requires the "Use" permission on Secrets.',
        ],
        ['base_url: Ask an organization admin to grant it.', 'Base URL: Ask an organization admin to grant it.'],
        ['api_key_secret_id: The value was left unchanged.', 'API key secret: The value was left unchanged.'],
        ['secret_ids: Not allowed.', 'Secret ids: Not allowed.'],
        ['llm_config: Not found.', 'LLM config: Not found.'],
        ['id: Invalid.', 'ID: Invalid.'],
        ['api_url_override: Invalid.', 'API URL override: Invalid.'],
        ['apikey_value: Kept as one word.', 'Apikey value: Kept as one word.'],
        ['constructor: Not an acronym.', 'Constructor: Not an acronym.'],
        ['python_code: secret_ids: Requires "Use".', 'Python code: Secret ids: Requires "Use".'],
        ['name: a tool with this name already exists.', 'Name: a tool with this name already exists.'],
        ['model: Bad model.; base_url: Bad URL.', 'Model: Bad model.; Base URL: Bad URL.'],
        ['quickstart will not attach a key: see the model.', 'Quickstart will not attach a key: see the model.'],
        ['the "Use" permission is missing.', 'The "Use" permission is missing.'],
        ['Already a sentence about base_url: kept.', 'Already a sentence about base_url: kept.'],
        ['Model: Already labelled.', 'Model: Already labelled.'],
        ['', ''],
        [null, ''],
        [undefined, ''],
    ])('%j -> %j', (message, expected) => {
        expect(humanizeErrorMessage(message)).toBe(expected);
    });
});
