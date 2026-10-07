import { toPluginDevFrameUrl, toPluginFrameUrl, withPluginNavFragment } from './plugin-frame-url.util';

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
        ['a dev server URL', 'http://localhost:4300/'],
        ['an empty string', ''],
        ['a non-string', 42],
    ])('refuses %s', (_label, url) => {
        expect(toPluginFrameUrl(url, ORIGIN)).toBeNull();
    });
});

describe('toPluginDevFrameUrl', () => {
    it.each([
        'http://localhost:4300/',
        'http://localhost',
        'http://localhost:4300',
        'http://127.0.0.1:8080/apps/chat-admin/',
        'http://localhost:65535/a_b~c.d%20e-f/',
    ])('accepts %s', (url) => {
        expect(toPluginDevFrameUrl(url)).toBe(url);
    });

    it.each([
        ['https', 'https://localhost:4300/'],
        ['another host', 'http://evil.example/'],
        ['a host that only starts with localhost', 'http://localhost.evil.com/'],
        ['user info', 'http://user:pass@localhost:4300/'],
        ['user info hiding another host', 'http://localhost:4300@evil.example/'],
        ['a query', 'http://localhost:4300/?x=1'],
        ['a fragment', 'http://localhost:4300/#x'],
        ['a port above 65535', 'http://localhost:99999/'],
        ['a six-digit port', 'http://localhost:123456/'],
        ['IPv6 loopback', 'http://[::1]:4300/'],
        ['a production path', '/api/plugin-ui/token/index.html'],
        ['a javascript: URL', 'javascript:alert(1)'],
        ['a backslash', 'http://localhost:4300\\@evil.example/'],
        ['a space', 'http://localhost:4300/a b'],
        ['over 255 characters', `http://localhost:4300/${'a'.repeat(240)}`],
        ['a non-string', null],
    ])('refuses %s', (_label, url) => {
        expect(toPluginDevFrameUrl(url)).toBeNull();
    });
});

describe('withPluginNavFragment', () => {
    it('puts the page path into the fragment, replacing any fragment there was', () => {
        expect(withPluginNavFragment('/api/plugin-ui/t/index.html', '/conversations/c_1?sort=key')).toBe(
            '/api/plugin-ui/t/index.html#/conversations/c_1?sort=key'
        );
        expect(withPluginNavFragment('http://localhost:4300/#old', '/')).toBe('http://localhost:4300/#/');
    });
});
