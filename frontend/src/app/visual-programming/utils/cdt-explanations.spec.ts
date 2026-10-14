import { CDT_EXPLANATION_LIMITS } from '../core/constants/cdt-explanation-limits';
import { readCdtExplanations, toStoredCdtExplanations } from './cdt-explanations';

const VALID = { text: 'Routes spam away', fingerprint: 'abc', generatedBy: 'gpt-4o-mini' };

describe('readCdtExplanations', () => {
    it.each<[string, Record<string, unknown> | null | undefined]>([
        ['no metadata', undefined],
        ['null metadata', null],
        ['no explanations entry', { position: { x: 0, y: 0 } }],
        ['a string', { explanations: 'nope' }],
        ['an array', { explanations: [VALID] }],
        ['null', { explanations: null }],
    ])('reads %s as no explanations', (_label, metadata) => {
        expect(readCdtExplanations(metadata)).toEqual({});
    });

    it('keeps valid entries and drops malformed ones', () => {
        const metadata = {
            explanations: {
                good: VALID,
                missingText: { fingerprint: 'f', generatedBy: 'g' },
                numericFingerprint: { text: 't', fingerprint: 1, generatedBy: 'g' },
                nullGeneratedBy: { text: 't', fingerprint: 'f', generatedBy: null },
                notAnObject: 'text',
                nullEntry: null,
            },
        };

        expect(readCdtExplanations(metadata)).toEqual({ good: VALID });
    });

    it('keeps only the three known fields of an entry', () => {
        const metadata = { explanations: { good: { ...VALID, status: 'ready', extra: 1 } } };

        expect(readCdtExplanations(metadata)).toEqual({ good: VALID });
    });
});

describe('toStoredCdtExplanations', () => {
    it('stores nothing as an empty object, not undefined', () => {
        expect(toStoredCdtExplanations(undefined)).toEqual({});
        expect(toStoredCdtExplanations({})).toEqual({});
    });

    it('writes keys in sorted order whatever order they were added in', () => {
        const stored = toStoredCdtExplanations({ 'rule:name:b': VALID, 'node:pre': VALID, 'rule:name:a': VALID });

        expect(Object.keys(stored)).toEqual(['node:pre', 'rule:name:a', 'rule:name:b']);
    });

    it('stringifies identically for the same entries in a different order, so a reload is not dirty', () => {
        const generated = { b: VALID, a: { ...VALID, text: 'other' } };
        const reloaded = readCdtExplanations({ explanations: { a: { ...VALID, text: 'other' }, b: VALID } });

        expect(JSON.stringify(toStoredCdtExplanations(reloaded))).toBe(
            JSON.stringify(toStoredCdtExplanations(generated))
        );
    });

    it('writes each entry with a fixed field order and nothing extra', () => {
        const stored = toStoredCdtExplanations({
            key: { generatedBy: 'g', fingerprint: 'f', text: 't', extra: true } as unknown as typeof VALID,
        });

        expect(JSON.stringify(stored)).toBe('{"key":{"text":"t","fingerprint":"f","generatedBy":"g"}}');
    });
});

describe('toStoredCdtExplanations — the backend storage limits', () => {
    const LIMITS = CDT_EXPLANATION_LIMITS;

    /** Compact JSON, UTF-8: how the backend measures the stored map. */
    function storedBytes(stored: Record<string, unknown>): number {
        return new TextEncoder().encode(JSON.stringify(stored)).length;
    }

    it.each([
        ['an empty key', '', VALID],
        ['a key past its limit', 'k'.repeat(LIMITS.maxStepKeyLength + 1), VALID],
        ['text past its limit', 'key', { ...VALID, text: 't'.repeat(LIMITS.maxTextLength + 1) }],
        ['generatedBy past its limit', 'key', { ...VALID, generatedBy: 'g'.repeat(LIMITS.maxGeneratedByLength + 1) }],
        ['a fingerprint past its limit', 'key', { ...VALID, fingerprint: 'f'.repeat(LIMITS.maxFingerprintLength + 1) }],
        ['empty text', 'key', { ...VALID, text: '' }],
        ['an empty fingerprint', 'key', { ...VALID, fingerprint: '' }],
        ['an empty generatedBy', 'key', { ...VALID, generatedBy: '' }],
        ['a NUL in the text', 'key', { ...VALID, text: 'a\u0000b' }],
        ['an unpaired surrogate in the text', 'key', { ...VALID, text: 'a\uD83Db' }],
        ['an unpaired surrogate in the key', 'k\uDE00', VALID],
    ])('drops an entry with %s, and keeps the others', (_label, key, entry) => {
        const stored = toStoredCdtExplanations({ [key]: entry as typeof VALID, other: VALID });

        expect(stored).toEqual({ other: VALID });
    });

    it('keeps every field at exactly its limit', () => {
        const atLimit = {
            text: 't'.repeat(LIMITS.maxTextLength),
            generatedBy: 'g'.repeat(LIMITS.maxGeneratedByLength),
            fingerprint: 'f'.repeat(LIMITS.maxFingerprintLength),
        };
        const key = 'k'.repeat(LIMITS.maxStepKeyLength);

        expect(toStoredCdtExplanations({ [key]: atLimit })).toEqual({ [key]: atLimit });
    });

    it('counts characters as the backend does: an emoji is one, not two UTF-16 units', () => {
        const emojiText = '😀'.repeat(LIMITS.maxTextLength);

        expect(toStoredCdtExplanations({ key: { ...VALID, text: emojiText } })).toEqual({
            key: { ...VALID, text: emojiText },
        });
    });

    it(`keeps the first ${CDT_EXPLANATION_LIMITS.maxEntries} entries in key order and leaves out the rest`, () => {
        const many = Object.fromEntries(
            Array.from({ length: LIMITS.maxEntries + 5 }, (_, index) => [
                `key-${String(index).padStart(5, '0')}`,
                VALID,
            ])
        );

        const stored = toStoredCdtExplanations(many);

        expect(Object.keys(stored)).toHaveLength(LIMITS.maxEntries);
        expect(Object.keys(stored).at(-1)).toBe(`key-${String(LIMITS.maxEntries - 1).padStart(5, '0')}`);
    });

    it('stops at the total size limit, leaving out every later entry, even a small one', () => {
        const big = { ...VALID, text: 't'.repeat(LIMITS.maxTextLength) };
        const entries: Record<string, typeof VALID> = {};
        for (let index = 0; index < 60; index++) entries[`big-${String(index).padStart(2, '0')}`] = big;
        entries['zz-small'] = VALID;

        const stored = toStoredCdtExplanations(entries);

        expect(storedBytes(stored)).toBeLessThanOrEqual(LIMITS.maxTotalBytes);
        expect(Object.keys(stored).length).toBeLessThan(60);
        expect(stored).not.toHaveProperty('zz-small');
        // One more of the big ones would have gone over.
        const nextBig = `big-${String(Object.keys(stored).length).padStart(2, '0')}`;
        expect(storedBytes({ ...stored, [nextBig]: big })).toBeGreaterThan(LIMITS.maxTotalBytes);
    });

    it('measures the size in UTF-8 bytes, so multi-byte text fills the limit sooner', () => {
        const ascii = { ...VALID, text: 'a'.repeat(LIMITS.maxTextLength) };
        const cyrillic = { ...VALID, text: 'я'.repeat(LIMITS.maxTextLength) };
        const fill = (entry: typeof VALID): number =>
            Object.keys(
                toStoredCdtExplanations(
                    Object.fromEntries(
                        Array.from({ length: 60 }, (_, index) => [`k${String(index).padStart(2, '0')}`, entry])
                    )
                )
            ).length;

        expect(fill(cyrillic)).toBeLessThan(fill(ascii));
    });

    it('orders keys by code point, as the backend does', () => {
        const astral = '\u{1F600}';
        const highBmp = '～';

        // UTF-16 order puts the emoji (a surrogate pair, 0xD83D…) first; code-point order puts it last.
        expect(Object.keys(toStoredCdtExplanations({ [astral]: VALID, [highBmp]: VALID }))).toEqual([highBmp, astral]);
    });
});
