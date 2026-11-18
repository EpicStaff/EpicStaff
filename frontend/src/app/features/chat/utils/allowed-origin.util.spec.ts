import { allowedOriginError } from './allowed-origin.util';

describe('allowedOriginError', () => {
    it.each([
        ['https://www.example.com'],
        ['http://localhost:4200'],
        ['https://example.com:8443'],
        ['http://[::1]:8080'],
        // The chat service lower-cases and drops one trailing slash before it compares.
        ['HTTPS://WWW.Example.COM'],
        ['https://www.example.com/'],
        ['  https://www.example.com  '],
    ])('accepts %s', (value) => {
        expect(allowedOriginError(value)).toBeNull();
    });

    it.each([
        ['no scheme', 'www.example.com'],
        ['not a URL', 'https://'],
        ['a path', 'https://www.example.com/chat'],
        ['a query', 'https://www.example.com?x=1'],
        ['a fragment', 'https://www.example.com#top'],
        ['user info', 'https://user@www.example.com'],
        ['the default https port', 'https://www.example.com:443'],
        ['the default http port', 'http://www.example.com:80'],
        ['two trailing slashes', 'https://www.example.com//'],
        ['another scheme', 'ftp://www.example.com'],
        ['a unicode host, sent as punycode by browsers', 'https://bücher.example'],
    ])('refuses %s', (_, value) => {
        expect(allowedOriginError(value)).toBe('Use scheme and host only, e.g. https://www.example.com');
    });
});
