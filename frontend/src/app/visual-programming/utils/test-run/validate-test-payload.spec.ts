import { MAX_TRIGGER_PAYLOAD_BYTES, parseTestPayload, validateTestPayloadValue } from './validate-test-payload';

describe('parseTestPayload', () => {
    it('accepts a JSON object, including an empty one', () => {
        expect(parseTestPayload('{"id": "104", "nested": {"a": [1, 2]}}')).toEqual({
            value: { id: '104', nested: { a: [1, 2] } },
        });
        expect(parseTestPayload('{}')).toEqual({ value: {} });
    });

    it('reports text that is not JSON', () => {
        const result = parseTestPayload('{"id": ');
        expect(result.value).toBeUndefined();
        expect(result.error).toMatch(/^Invalid JSON: /);
    });

    it.each(['[]', 'null', '"text"', '42', 'true'])('rejects %s because it is not an object', (text) => {
        expect(parseTestPayload(text)).toEqual({ error: 'Test payload must be a JSON object.' });
    });
});

describe('validateTestPayloadValue', () => {
    it('rejects a NUL character in a value or a key', () => {
        const message = 'Test payload must not contain the NUL character (\\u0000) in any key or value.';
        expect(validateTestPayloadValue({ text: 'a\u0000b' })).toBe(message);
        expect(validateTestPayloadValue({ 'a\u0000': 1 })).toBe(message);
        expect(validateTestPayloadValue({ list: [{ deep: '\u0000' }] })).toBe(message);
    });

    it('accepts the literal text \\u0000', () => {
        expect(parseTestPayload('{"text": "\\\\u0000"}')).toEqual({ value: { text: '\\u0000' } });
    });

    it('rejects an unpaired surrogate but accepts a real emoji', () => {
        expect(validateTestPayloadValue({ text: '\uD800' })).toBe(
            'Test payload must not contain unpaired Unicode surrogates.'
        );
        expect(validateTestPayloadValue({ text: '😀' })).toBeNull();
    });

    it('measures the size as UTF-8 bytes of compact JSON', () => {
        // {"t":"..."} is 8 bytes of structure around the string.
        const structureBytes = JSON.stringify({ t: '' }).length;
        const atLimit = { t: 'a'.repeat(MAX_TRIGGER_PAYLOAD_BYTES - structureBytes) };
        expect(validateTestPayloadValue(atLimit)).toBeNull();

        const overLimit = { t: 'a'.repeat(MAX_TRIGGER_PAYLOAD_BYTES - structureBytes + 1) };
        expect(validateTestPayloadValue(overLimit)).toBe(
            `Test payload must not exceed ${MAX_TRIGGER_PAYLOAD_BYTES} bytes of compact JSON (got ${MAX_TRIGGER_PAYLOAD_BYTES + 1}).`
        );
    });

    it('counts a multi-byte character by its UTF-8 length', () => {
        // 'ж' is 2 bytes in UTF-8, so half as many fit.
        const structureBytes = JSON.stringify({ t: '' }).length;
        const characters = (MAX_TRIGGER_PAYLOAD_BYTES - structureBytes) / 2;
        expect(validateTestPayloadValue({ t: 'ж'.repeat(Math.floor(characters)) })).toBeNull();
        expect(validateTestPayloadValue({ t: 'ж'.repeat(Math.floor(characters) + 1) })).not.toBeNull();
    });
});
