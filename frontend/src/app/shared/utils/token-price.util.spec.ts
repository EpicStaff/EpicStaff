import { perMillionToPerToken, perTokenToPerMillion } from './token-price.util';

describe('perMillionToPerToken', () => {
    it.each([
        { perMillion: 2.5, expected: 2.5e-6 },
        { perMillion: 10, expected: 1e-5 },
        { perMillion: 0.15, expected: 1.5e-7 },
    ])('converts $perMillion per 1M to exactly $expected per token', ({ perMillion, expected }) => {
        expect(perMillionToPerToken(perMillion)).toBe(expected);
    });

    it('hides float noise: typing 3.3 sends exactly 3.3e-6, not 3.2999999999999997e-6', () => {
        expect(3.3 / 1_000_000).not.toBe(3.3e-6);
        expect(perMillionToPerToken(3.3)).toBe(3.3e-6);
    });

    it('keeps an explicit 0 (free model) as 0', () => {
        expect(perMillionToPerToken(0)).toBe(0);
    });

    it.each([null, undefined])('maps empty (%s) to null', (empty) => {
        expect(perMillionToPerToken(empty)).toBeNull();
    });
});

describe('perTokenToPerMillion', () => {
    it('shows 2.5e-6 per token as 2.5', () => {
        expect(perTokenToPerMillion(2.5e-6)).toBe(2.5);
    });

    it('hides float noise: 3.3e-6 per token shows as 3.3, not 3.3000000000000003', () => {
        expect(3.3e-6 * 1_000_000).not.toBe(3.3);
        expect(perTokenToPerMillion(3.3e-6)).toBe(3.3);
    });

    it('keeps significant digits of a price set outside this UI', () => {
        expect(perTokenToPerMillion(1.234567891e-7)).toBe(0.1234567891);
    });

    it('keeps a tiny per-token price instead of rounding it to 0', () => {
        expect(perTokenToPerMillion(4e-13)).toBe(4e-7);
    });

    it('keeps an explicit 0 (free model) as 0', () => {
        expect(perTokenToPerMillion(0)).toBe(0);
    });

    it.each([null, undefined])('maps empty (%s) to null', (empty) => {
        expect(perTokenToPerMillion(empty)).toBeNull();
    });
});

describe('token price round trips', () => {
    it.each([0, 0.15, 0.3, 1.1, 2.5, 3, 3.3, 15, 75, 0.000001, 1234.5])(
        'round-trips %s per 1M through per-token unchanged',
        (perMillion) => {
            expect(perTokenToPerMillion(perMillionToPerToken(perMillion))).toBe(perMillion);
        }
    );

    it.each([0, 3.3e-6, 1.234567891e-7, 4e-13, 2.5e-6, 1.5e-7, 6e-5])(
        'round-trips %s per token through per-1M unchanged',
        (perToken) => {
            expect(perMillionToPerToken(perTokenToPerMillion(perToken))).toBe(perToken);
        }
    );
});
