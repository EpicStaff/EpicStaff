import { toPluginFrameUrl } from './plugin-frame-url.util';

const ORIGIN = 'https://epicstaff.example';

describe('toPluginFrameUrl', () => {
    it('accepts a same-origin path under /api/plugin-ui/', () => {
        expect(toPluginFrameUrl('/api/plugin-ui/eyJ:1t2:Xyz/index.html', ORIGIN)).toBe(
            '/api/plugin-ui/eyJ:1t2:Xyz/index.html'
        );
    });

    it.each([
        ['an absolute URL elsewhere', 'https://evil.example/api/plugin-ui/x/index.html'],
        ['a protocol-relative URL', '//evil.example/api/plugin-ui/x/index.html'],
        ['a javascript: URL', 'javascript:alert(1)'],
        ['a data: URL', 'data:text/html,<script>alert(1)</script>'],
        ['another API path', '/api/graphs/'],
        ['a path that climbs out of the prefix', '/api/plugin-ui/../graphs/'],
        ['an encoded climb', '/api/plugin-ui/%2e%2e/graphs/'],
        ['a backslash trick', '/api/plugin-ui/\\evil.example'],
        ['an empty string', ''],
        ['a non-string', 42],
    ])('refuses %s', (_label, url) => {
        expect(toPluginFrameUrl(url, ORIGIN)).toBeNull();
    });
});
