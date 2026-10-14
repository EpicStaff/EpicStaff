import { normalizeIana } from './timezone-selector.component';

describe('normalizeIana', () => {
    it('maps the legacy Kiev name to Kyiv', () => {
        expect(normalizeIana('Europe/Kiev')).toBe('Europe/Kyiv');
    });

    it('keeps any other zone unchanged', () => {
        expect(normalizeIana('Europe/Kyiv')).toBe('Europe/Kyiv');
        expect(normalizeIana('America/New_York')).toBe('America/New_York');
    });
});
