import {
    isRefusedInPublicName,
    isSamePublicName,
    normalizePublicName,
    publicNameError,
    publicNameKey,
    validationReason,
} from './public-name.util';

const character = (codePoint: number): string => String.fromCodePoint(codePoint);

describe('public name rules', () => {
    describe('normalizePublicName', () => {
        it("composes, then strips the service's whitespace: information separators and NEL yes, the BOM no", () => {
            expect(normalizePublicName(`  Jose${character(0x301)} `)).toBe('José');
            expect(normalizePublicName(`${character(0x1c)}${character(0x85)} Mike${character(0x3000)}`)).toBe('Mike');
            expect(normalizePublicName(`${character(0xfeff)}Mike`)).toBe(`${character(0xfeff)}Mike`);
            expect(normalizePublicName(' \t\n ')).toBe('');
        });
    });

    describe('isRefusedInPublicName', () => {
        it('refuses controls, format characters, separators, private use and surrogates', () => {
            for (const codePoint of [0x07, 0x7f, 0x200b, 0x202e, 0x2066, 0xfeff, 0x2028, 0x2029, 0xe000, 0xd800]) {
                expect(isRefusedInPublicName(character(codePoint))).toBe(true);
            }
        });

        it('refuses the fillers of allowed kinds, at both ends of each range', () => {
            const fillers = [
                0x034f, 0x115f, 0x1160, 0x17b4, 0x17b5, 0x180b, 0x180f, 0x2800, 0x3164, 0xffa0, 0xfe00, 0xfe0d, 0x1bca0,
                0x1bca3, 0x1d173, 0x1d17a, 0xe0000, 0xe0fff,
            ];
            for (const codePoint of fillers) expect(isRefusedInPublicName(character(codePoint))).toBe(true);
        });

        it('keeps the emoji joiners, and letters, spaces and emoji', () => {
            for (const codePoint of [0x200d, 0xfe0e, 0xfe0f, 0x41, 0x20, 0xe9, 0x1f469, 0x3042]) {
                expect(isRefusedInPublicName(character(codePoint))).toBe(false);
            }
        });
    });

    describe('publicNameError', () => {
        it('counts characters, not UTF-16 units, and names the first refused character', () => {
            expect(publicNameError('x'.repeat(64))).toBeNull();
            expect(publicNameError('x'.repeat(65))).toBe('Use at most 64 characters.');
            expect(publicNameError(character(0x1f600).repeat(64))).toBeNull();
            expect(publicNameError(`Ava${character(0x1d173)}${character(0x200b)}`)).toBe(
                'Remove the invisible or control character U+1D173: visitors would not see it.'
            );
        });
    });

    describe('validationReason', () => {
        it("drops Pydantic's prefix and keeps any other message", () => {
            expect(validationReason('Value error, Must be at most 64 characters.')).toBe(
                'Must be at most 64 characters.'
            );
            expect(validationReason('Input should be a valid string')).toBe('Input should be a valid string');
        });
    });

    describe('publicNameKey', () => {
        it('reads a name with emoji joiners added as the same name', () => {
            expect(isSamePublicName(`Ava${character(0x200d)}`, 'Ava')).toBe(true);
            expect(isSamePublicName(`A${character(0xfe0f)}va${character(0xfe0e)}`, 'ava')).toBe(true);
        });

        it('folds case as the service does for "ß" and "ẞ", and composes before and after', () => {
            expect(isSamePublicName('Straße', 'STRASSE')).toBe(true);
            expect(isSamePublicName('STRAẞE', 'strasse')).toBe(true);
            expect(publicNameKey(`Jose${character(0x301)}`)).toBe(publicNameKey('JOSÉ'));
        });

        it('keeps names that only look alike apart', () => {
            expect(isSamePublicName('Ava', 'Ava B')).toBe(false);
            expect(isSamePublicName('Ava', 'Eva')).toBe(false);
        });
    });
});
