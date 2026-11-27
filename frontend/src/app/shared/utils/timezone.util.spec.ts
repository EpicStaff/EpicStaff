import { browserTimeZone, effectiveZone, normalizeIana } from './timezone.util';

function browserReports(zone: string): void {
    vi.spyOn(Intl.DateTimeFormat.prototype, 'resolvedOptions').mockReturnValue({
        timeZone: zone,
    } as Intl.ResolvedDateTimeFormatOptions);
}

describe('timezone.util', () => {
    afterEach(() => vi.restoreAllMocks());

    it.each([
        ['Europe/Kiev', 'Europe/Kyiv'],
        ['Europe/Kyiv', 'Europe/Kyiv'],
        ['America/New_York', 'America/New_York'],
    ])('normalises %s to %s', (zone, expected) => {
        expect(normalizeIana(zone)).toBe(expected);
    });

    it('reports the browser zone under its current name', () => {
        browserReports('Europe/Kiev');

        expect(browserTimeZone()).toBe('Europe/Kyiv');
    });

    it.each([
        { preference: null, expected: 'Asia/Tokyo' },
        { preference: '', expected: 'Asia/Tokyo' },
        { preference: 'America/New_York', expected: 'America/New_York' },
        { preference: 'Europe/Kiev', expected: 'Europe/Kyiv' },
    ])('takes $expected for the preference $preference', ({ preference, expected }) => {
        browserReports('Asia/Tokyo');

        expect(effectiveZone(preference)).toBe(expected);
    });
});
