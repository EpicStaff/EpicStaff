import { isAllowedSecretName } from './secret-name.util';

describe('isAllowedSecretName', () => {
    it.each([
        ['letters', 'OpenAI'],
        ['digits', '2024'],
        ['an underscore', 'api_key'],
        ['a dash', 'api-key'],
        ['a dot', 'api.key'],
        ['a space', 'OpenAI API Key'],
        ['non-Latin letters', 'Ключ доступу'],
        ['non-ASCII digits', 'key٣'],
    ])('allows %s', (_case, name) => {
        expect(isAllowedSecretName(name)).toBe(true);
    });

    it.each([
        ['an opening parenthesis', 'a(b'],
        ['a closing parenthesis', 'a)b'],
        ['an opening brace', 'a{b'],
        ['a closing brace', 'a}b'],
        ['a plus', 'a+b'],
        ['a double quote', 'a"b'],
        ['a single quote', "a'b"],
        ['a backslash', 'a\\b'],
        ['a control character', 'a\u0008b'],
        ['a colon', 'a:b'],
        ['a slash', 'a/b'],
        ['a less-than sign', 'a<b'],
        ['a newline', 'a\nb'],
        ['a tab', 'a\tb'],
        ['a dollar sign', 'a$1'],
        ['an empty name', ''],
    ])('rejects %s', (_case, name) => {
        expect(isAllowedSecretName(name)).toBe(false);
    });
});
