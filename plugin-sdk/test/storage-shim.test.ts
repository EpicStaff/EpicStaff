import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import { installStorageShim, MemoryCookieJar } from '../dist/index.js';
import { FakeWindow } from './helpers/fake-window.ts';

class WorkingStorage {
    readonly items = new Map<string, string>();

    getItem(key: string): string | null {
        return this.items.get(key) ?? null;
    }

    setItem(key: string, value: string): void {
        this.items.set(key, value);
    }

    removeItem(key: string): void {
        this.items.delete(key);
    }
}

/** A window whose storage works (a normal page), so the shim must leave it alone. */
class WorkingStorageWindow {
    readonly document = { cookie: 'native=1' };
    readonly localStorage = new WorkingStorage();
    readonly sessionStorage = new WorkingStorage();
}

describe('installStorageShim', () => {
    test('gives a sandboxed window in-memory localStorage, sessionStorage and document.cookie', () => {
        const win = new FakeWindow();
        assert.throws(() => win.localStorage);
        assert.throws(() => win.document.cookie);

        const result = installStorageShim({ window: win.asWindow() });

        assert.deepEqual(result, { localStorage: 'memory', sessionStorage: 'memory', cookie: 'memory' });
        const storage = win.asWindow().localStorage;
        storage.setItem('theme', 'dark');
        storage.setItem('count', 3 as unknown as string);
        assert.equal(storage.getItem('theme'), 'dark');
        assert.equal(storage.getItem('count'), '3');
        assert.equal(storage.length, 2);
        assert.equal(storage.key(1), 'count');
        storage.removeItem('theme');
        assert.equal(storage.getItem('theme'), null);
        storage.clear();
        assert.equal(storage.length, 0);
        assert.notEqual(win.asWindow().sessionStorage, storage, 'each storage is separate');

        const document = win.asWindow().document;
        document.cookie = 'session=abc; path=/';
        document.cookie = 'lang=en';
        assert.equal(document.cookie, 'session=abc; lang=en');
        document.cookie = 'session=; max-age=0';
        assert.equal(document.cookie, 'lang=en');
    });

    test('is idempotent and keeps the same stand-in', () => {
        const win = new FakeWindow();
        installStorageShim({ window: win.asWindow() });
        const first = win.asWindow().localStorage;
        first.setItem('kept', 'yes');

        const again = installStorageShim({ window: win.asWindow() });

        assert.equal(again.localStorage, 'memory');
        assert.equal(win.asWindow().localStorage.getItem('kept'), 'yes');
    });

    test('leaves working storage alone unless forced', () => {
        const working = new WorkingStorageWindow();
        const target = working as unknown as Window;
        const native = installStorageShim({ window: target });
        assert.deepEqual(native, { localStorage: 'native', sessionStorage: 'native', cookie: 'native' });

        const forced = installStorageShim({ window: target, force: true });

        assert.deepEqual(forced, { localStorage: 'memory', sessionStorage: 'memory', cookie: 'memory' });
        assert.equal(target.localStorage.getItem('anything'), null);
        assert.equal(target.document.cookie, '');
    });

    test('is a no-op without a window', () => {
        assert.deepEqual(installStorageShim(), { localStorage: 'native', sessionStorage: 'native', cookie: 'native' });
    });
});

describe('MemoryCookieJar', () => {
    test('drops cookies whose expiry is in the past', () => {
        const jar = new MemoryCookieJar();
        jar.write('a=1');
        jar.write('b=2; Expires=Thu, 01 Jan 1970 00:00:00 GMT');
        jar.write('c=3; Expires=Fri, 01 Jan 2100 00:00:00 GMT');
        assert.equal(jar.read(), 'a=1; c=3');
    });
});
