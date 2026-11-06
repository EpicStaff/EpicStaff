import { providerDisplayName } from './provider-display-name.util';

describe('providerDisplayName', () => {
    it.each([
        ['openai', 'OpenAI'],
        ['aws_sagemaker', 'AWS SageMaker'],
        ['OpenAI', 'OpenAI'],
        ['OPENAI', 'OpenAI'],
        ['oPeNaI', 'OpenAI'],
        ['foo_bar', 'Foo Bar'],
        ['some-thing', 'Some Thing'],
    ])('shows %s as %s', (providerId, expected) => {
        expect(providerDisplayName(providerId)).toBe(expected);
    });
});
