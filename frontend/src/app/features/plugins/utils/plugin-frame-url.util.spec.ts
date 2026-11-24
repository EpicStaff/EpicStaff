import { toPluginFrameOrigin, toPluginFrameUrl } from './plugin-frame-url.util';

const HOST_ORIGIN = 'https://epicstaff.example.com';
const FRAME_ORIGIN = 'https://weather.plugins.example.com';

describe('toPluginFrameOrigin', () => {
    it.each([
        ['a nested host: the identifier is the whole first label', FRAME_ORIGIN],
        ['a flat host with a suffix ({id}-app)', 'https://weather-app.example.com'],
        ['a flat host with a prefix (app-{id})', 'https://app-weather.example.com'],
        ['a prefix and a suffix (es-{id}-app)', 'https://es-weather-app.example.com'],
        ['an affix without a hyphen ({id}app)', 'https://weatherapp.example.com'],
        ['an explicit port', 'https://weather.plugins.example.com:8443'],
        ['a flat host with a port', 'https://weather-app.example.com:8443'],
        // A containment check, not the template: a longer word that holds the identifier passes too.
        ['a first label that only contains the identifier', 'https://weatherman.example.com'],
        ['http on a .localhost host (local development)', 'http://weather.plugins.epicstaff.localhost'],
        ['http on a .localhost host with a port', 'http://weather.plugins.epicstaff.localhost:4200'],
    ])('accepts %s', (_label, origin) => {
        expect(toPluginFrameOrigin(origin, 'weather', HOST_ORIGIN)).toBe(origin);
    });

    it.each([
        ['plain http outside .localhost', 'http://weather.plugins.example.com'],
        ['a trailing slash', `${FRAME_ORIGIN}/`],
        ['a path', `${FRAME_ORIGIN}/app`],
        ['a query', `${FRAME_ORIGIN}?x=1`],
        ['credentials', 'https://user:secret@weather.plugins.example.com'],
        ['another plugin host', 'https://chat.plugins.example.com'],
        ['a first label without the identifier', 'https://chat-app.example.com'],
        ['a first label that holds only part of the identifier', 'https://weath-app.example.com'],
        ['the identifier only in a deeper label', 'https://app.weather.example.com'],
        ['the identifier only in the parent domain', 'https://chat.weather.example.com'],
        ['a hyphen at the outer edge of the first label', 'https://-weather.example.com'],
        ['a one-label parent domain', 'https://weather-app.com'],
        ['a nested host with a one-label parent domain', 'https://weather.com'],
        ['the bare identifier as the host', 'https://weather'],
        ['an empty label in the parent domain', 'https://weather..example.com'],
        ['upper case, which is not the canonical origin', 'https://Weather.plugins.example.com'],
        ['a javascript: URL', 'javascript:alert(1)'],
        ['a data: URL', 'data:text/html,<script>alert(1)</script>'],
        ['an empty string', ''],
        ['a non-string', 42],
    ])('refuses %s', (_label, origin) => {
        expect(toPluginFrameOrigin(origin, 'weather', HOST_ORIGIN)).toBeNull();
    });

    it("refuses EpicStaff's own origin, even when it is under the identifier", () => {
        const sameOrigin = 'https://weather.example.com';
        expect(toPluginFrameOrigin(sameOrigin, 'weather', sameOrigin)).toBeNull();
    });

    it('refuses an identifier the manifest would refuse', () => {
        expect(toPluginFrameOrigin('https://we.ather.example.com', 'we.ather', HOST_ORIGIN)).toBeNull();
    });
});

describe('toPluginFrameUrl', () => {
    function frameUrl(navPath: string, orgId = 3, frameOrigin: unknown = FRAME_ORIGIN): string | null {
        return toPluginFrameUrl({ frameOrigin, identifier: 'weather', navPath, orgId, hostOrigin: HOST_ORIGIN });
    }

    it('appends es_org with "?" when the path has no query', () => {
        expect(frameUrl('/')).toBe(`${FRAME_ORIGIN}/?es_org=3`);
        expect(frameUrl('/about')).toBe(`${FRAME_ORIGIN}/about?es_org=3`);
    });

    it('appends es_org with "&" after the page query', () => {
        expect(frameUrl('/forecast?city=Berlin&days=3')).toBe(`${FRAME_ORIGIN}/forecast?city=Berlin&days=3&es_org=3`);
    });

    it("drops an es_org of the page's own, so only EpicStaff's reaches it", () => {
        expect(frameUrl('/forecast?es_org=99&city=Paris')).toBe(`${FRAME_ORIGIN}/forecast?city=Paris&es_org=3`);
    });

    it('keeps the frame on the plugin origin: an invalid path opens the root', () => {
        for (const path of ['//evil.example/x', '/../admin', '/%2e%2e/x', 'https://evil.example/']) {
            const url = frameUrl(path);
            expect(url).toBe(`${FRAME_ORIGIN}/?es_org=3`);
            expect(new URL(url ?? '').origin).toBe(FRAME_ORIGIN);
        }
    });

    it('refuses an unsafe frame origin or an org id that is not a positive integer', () => {
        expect(frameUrl('/', 3, 'http://weather.plugins.example.com')).toBeNull();
        expect(frameUrl('/', 3, HOST_ORIGIN)).toBeNull();
        for (const orgId of [0, -1, 1.5, Number.NaN]) {
            expect(frameUrl('/', orgId)).toBeNull();
        }
    });
});
