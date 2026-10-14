import {
    getHeaderRowError,
    HEADER_NAME_DUPLICATE_ERROR,
    HEADER_NAME_FORMAT_ERROR,
    HEADER_NAME_REQUIRED_ERROR,
    HEADER_VALUE_LINE_BREAK_ERROR,
} from './header-validation.util';

describe('getHeaderRowError', () => {
    it('ignores an entirely empty row', () => {
        expect(getHeaderRowError('', '', [])).toBeNull();
    });

    it('requires a name when a value is set', () => {
        expect(getHeaderRowError('', 'value', [])).toBe(HEADER_NAME_REQUIRED_ERROR);
    });

    it('rejects names with spaces or special characters', () => {
        expect(getHeaderRowError('X Team', 'v', [])).toBe(HEADER_NAME_FORMAT_ERROR);
        expect(getHeaderRowError('X:Team', 'v', [])).toBe(HEADER_NAME_FORMAT_ERROR);
    });

    it('accepts HTTP token names, with an empty value', () => {
        expect(getHeaderRowError('X-Proxy_Key.1', '', [])).toBeNull();
    });

    it('rejects duplicates case-insensitively', () => {
        expect(getHeaderRowError('x-team', 'v', ['X-Team'])).toBe(HEADER_NAME_DUPLICATE_ERROR);
    });

    it('rejects values with line breaks', () => {
        expect(getHeaderRowError('X-Team', 'a\nb', [])).toBe(HEADER_VALUE_LINE_BREAK_ERROR);
    });
});
