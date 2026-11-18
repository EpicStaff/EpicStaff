import { getProviderHeadingIcon } from './get-provider-icon';

describe('getProviderHeadingIcon', () => {
    it.each([
        ['openai', { icon: 'llm-openai-mono', isTinted: false }],
        ['OpenAI', { icon: 'llm-openai-mono', isTinted: false }],
        ['groq', { icon: 'own-logo', isTinted: true }],
    ])('gives %s the heading icon %o', (providerId, expected) => {
        expect(getProviderHeadingIcon(providerId, 'own-logo')).toEqual(expected);
    });
});
