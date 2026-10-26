import {
    canonicalNavPath,
    formatNavPath,
    navPathFromRoute,
    parseNavPath,
    PLUGIN_ROOT_NAV_PATH,
} from './plugin-nav-path.util';

describe('plugin nav path', () => {
    describe('parseNavPath', () => {
        it('splits a path into decoded segments and query params, as the router takes them', () => {
            expect(parseNavPath('/')).toEqual({ segments: [], queryParams: {} });
            expect(parseNavPath('/conversations/c_1')).toEqual({ segments: ['conversations', 'c_1'], queryParams: {} });
            expect(parseNavPath('/a%20b/x%2Fy?q=a+b&page=2&tag=x&tag=y&flag')).toEqual({
                segments: ['a b', 'x/y'],
                queryParams: { q: 'a b', page: '2', tag: ['x', 'y'], flag: '' },
            });
        });

        it('keeps a __proto__ query key as plain data', () => {
            const target = parseNavPath('/?__proto__=x&constructor=y');

            expect(Object.keys(target?.queryParams ?? {})).toEqual(['__proto__', 'constructor']);
            expect(Object.getPrototypeOf(target?.queryParams)).toBe(Object.prototype);
        });

        it('drops a query param without a name and empty parts', () => {
            expect(parseNavPath('/a?=x&&b=1&')).toEqual({ segments: ['a'], queryParams: { b: '1' } });
        });

        it.each([
            ['no leading slash', 'a/b'],
            ['an empty segment', '/a//b'],
            ['a trailing slash', '/a/'],
            ['a dot segment', '/a/./b'],
            ['a dot-dot segment', '/a/../b'],
            ['an encoded dot-dot segment', '/%2E%2E/admin'],
            ['an encoded dot segment', '/%2e'],
            ['a fragment', '/a#b'],
            ['a malformed escape', '/a%2'],
            ['an invalid UTF-8 escape', '/%FF'],
            ['a malformed escape in the query', '/a?q=%zz'],
            ['a backslash', '/a\\b'],
            ['a colon', '/a:b'],
            ['a second question mark', '/a?b?c'],
            ['an absolute URL', 'https://evil.example/'],
            ['an empty string', ''],
            ['too long', `/${'a'.repeat(1024)}`],
            ['not a string', 7],
        ])('refuses %s', (_label, path) => {
            expect(parseNavPath(path)).toBeNull();
        });

        it('accepts exactly 1024 characters', () => {
            expect(parseNavPath(`/${'a'.repeat(1023)}`)).not.toBeNull();
        });
    });

    describe('formatNavPath and canonicalNavPath', () => {
        it('spells a path one way: everything but unreserved characters encoded, uppercase hex', () => {
            expect(
                formatNavPath({ segments: ["it's (x)!", 'a~b'], queryParams: { 'a b': 'c+d', e: ['1', '2'] } })
            ).toBe('/it%27s%20%28x%29%21/a~b?a%20b=c%2Bd&e=1&e=2');
            expect(canonicalNavPath('/a%7e%2fb?q=a+b')).toBe('/a~%2Fb?q=a%20b');
            expect(canonicalNavPath('/x?flag')).toBe('/x?flag=');
            expect(canonicalNavPath('/x?')).toBe('/x');
        });

        it('round-trips a canonical path unchanged', () => {
            for (const path of ['/', '/conversations', '/conversations/c_0123?search=a%20b&page=2', '/x?tag=1&tag=2']) {
                expect(canonicalNavPath(path)).toBe(path);
            }
        });

        it('refuses a path whose canonical form would break the grammar', () => {
            // 400 "+" are 400 characters as written, 1200 once a space is spelled "%20".
            expect(canonicalNavPath(`/a?q=${'+'.repeat(400)}`)).toBeNull();
        });
    });

    describe('navPathFromRoute', () => {
        it('turns the router segments and query params into the canonical path', () => {
            expect(navPathFromRoute([], {})).toBe('/');
            expect(
                navPathFromRoute(['conversations', 'c 1'], { sort: '-key', tag: ['a', 'b'], empty: undefined })
            ).toBe('/conversations/c%201?sort=-key&tag=a&tag=b');
        });

        it('falls back to the root path for what a page could not be told', () => {
            expect(navPathFromRoute(['..'], {})).toBe(PLUGIN_ROOT_NAV_PATH);
            expect(navPathFromRoute(['a'.repeat(2000)], {})).toBe(PLUGIN_ROOT_NAV_PATH);
            expect(navPathFromRoute(['\uD800'], {})).toBe(PLUGIN_ROOT_NAV_PATH);
        });

        it('agrees with a path the page reported, so the host never echoes it back', () => {
            const reported = canonicalNavPath('/conversations?search=a+b&page=2');
            const target = parseNavPath(reported);

            expect(navPathFromRoute(target?.segments ?? [], target?.queryParams ?? {})).toBe(reported);
        });
    });
});
