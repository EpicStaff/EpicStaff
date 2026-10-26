import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import { addressToNavPath, canonicalNavPath, hashToNavPath, isValidNavPath } from '../dist/index.js';

describe('navigation path grammar', () => {
    test('accepts paths EpicStaff accepts', () => {
        for (const path of ['/', '/forecast', '/forecast/berlin?days=3&units=metric', '/a%20b', '/x?flag', '/x?']) {
            assert.equal(isValidNavPath(path), true, path);
        }
    });

    test('refuses dot segments, bad escapes, fragments and over-long paths', () => {
        for (const path of [
            'forecast',
            '/a//b',
            '/a/',
            '/a/./b',
            '/a/../b',
            '/%2e%2e/admin',
            '/%2E',
            '/a#b',
            '/a%2',
            '/%FF',
            '/a?q=%zz',
            '/a:b',
            'https://evil.example/',
            '',
            `/${'a'.repeat(1024)}`,
            7,
        ]) {
            assert.equal(isValidNavPath(path), false, String(path));
        }
        assert.equal(isValidNavPath(`/${'a'.repeat(1023)}`), true, 'exactly 1024 characters');
    });

    test('canonical spelling: unreserved characters plain, everything else uppercase escapes', () => {
        assert.equal(canonicalNavPath('/a%7e%2fb?q=a+b'), '/a~%2Fb?q=a%20b');
        assert.equal(canonicalNavPath('/x?flag'), '/x?flag=');
        assert.equal(canonicalNavPath('/x?'), '/x');
        assert.equal(canonicalNavPath('/c?b=1&10=x&2=y'), '/c?2=y&10=x&b=1', 'integer-like keys first');
        assert.equal(canonicalNavPath('/c?a=1&b=2&a=3'), '/c?a=1&a=3&b=2', 'a repeated key grouped');
        assert.equal(canonicalNavPath(`/a?q=${'+'.repeat(400)}`), null, 'over 1024 once spaces are escaped');
    });

    test('turns an address into its canonical path', () => {
        assert.equal(addressToNavPath('/', ''), '/');
        assert.equal(addressToNavPath('/forecast/', '?city=New York'), '/forecast?city=New%20York');
        assert.equal(addressToNavPath('/caf%C3%A9', ''), '/caf%C3%A9');
        assert.equal(addressToNavPath('/a/../b', ''), null);
    });

    test('turns a hash route into its canonical path', () => {
        assert.equal(hashToNavPath(''), '/');
        assert.equal(hashToNavPath('#/about'), '/about');
        assert.equal(hashToNavPath('#/a b/c?x=a:b'), '/a%20b/c?x=a%3Ab');
        assert.equal(hashToNavPath('#/a#section'), '/a');
        assert.equal(hashToNavPath('#/a/%2e%2e/b'), null);
    });
});
