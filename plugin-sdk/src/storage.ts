/** The `Storage` methods libraries use; `MemoryStorage` implements exactly these. */
export type StorageLike = Pick<Storage, 'length' | 'key' | 'getItem' | 'setItem' | 'removeItem' | 'clear'>;

/** An in-memory `Storage`: same methods, nothing survives a reload. */
export class MemoryStorage implements StorageLike {
    readonly #items = new Map<string, string>();

    get length(): number {
        return this.#items.size;
    }

    key(index: number): string | null {
        return [...this.#items.keys()][index] ?? null;
    }

    getItem(key: string): string | null {
        return this.#items.get(String(key)) ?? null;
    }

    setItem(key: string, value: string): void {
        this.#items.set(String(key), String(value));
    }

    removeItem(key: string): void {
        this.#items.delete(String(key));
    }

    clear(): void {
        this.#items.clear();
    }
}

/** An in-memory cookie jar behind a `document.cookie` stand-in. Attributes other than expiry are ignored. */
export class MemoryCookieJar {
    readonly #cookies = new Map<string, string>();

    read(): string {
        return [...this.#cookies].map(([name, value]) => (name === '' ? value : `${name}=${value}`)).join('; ');
    }

    write(text: string): void {
        const [pair = '', ...attributes] = String(text).split(';');
        const separator = pair.indexOf('=');
        const name = separator >= 0 ? pair.slice(0, separator).trim() : '';
        const value = separator >= 0 ? pair.slice(separator + 1).trim() : pair.trim();
        if (attributes.some(isExpiry)) this.#cookies.delete(name);
        else this.#cookies.set(name, value);
    }
}

function isExpiry(attribute: string): boolean {
    const [rawName = '', ...rest] = attribute.split('=');
    const name = rawName.trim().toLowerCase();
    const value = rest.join('=').trim();
    if (name === 'max-age') return Number(value) <= 0;
    if (name === 'expires') {
        const time = Date.parse(value);
        return !Number.isNaN(time) && time <= Date.now();
    }
    return false;
}

export interface StorageShimOptions {
    /** Replace the browser's storage even where it works (no persistence at all). Default `false`. */
    force?: boolean;
    /** The window to patch. Default: the global `window`. */
    window?: Window;
}

/** Per stand-in: `native` (left alone), `memory` (replaced) or `unavailable` (broken and not replaceable). */
export type StorageShimState = 'native' | 'memory' | 'unavailable';

export interface StorageShimResult {
    localStorage: StorageShimState;
    sessionStorage: StorageShimState;
    cookie: StorageShimState;
}

const STORAGE_NAMES = ['localStorage', 'sessionStorage'] as const;
const PROBE_KEY = '__epicstaff_storage_probe__';
const installed = new WeakMap<object, Set<string>>();

/**
 * Gives `localStorage`, `sessionStorage` and `document.cookie` in-memory stand-ins where the
 * browser throws on access (a sandboxed plugin app always does), so libraries that touch storage
 * do not crash. Nothing persists: keep app state in memory and in the URL.
 *
 * Idempotent; a later call with `force: true` also replaces what still works.
 */
export function installStorageShim(options: StorageShimOptions = {}): StorageShimResult {
    const win = options.window ?? (typeof window === 'undefined' ? undefined : window);
    if (win === undefined) return { localStorage: 'native', sessionStorage: 'native', cookie: 'native' };
    const force = options.force ?? false;
    const done = installed.get(win) ?? new Set<string>();
    installed.set(win, done);

    const result: StorageShimResult = { localStorage: 'native', sessionStorage: 'native', cookie: 'native' };
    for (const name of STORAGE_NAMES) {
        if (done.has(name)) {
            result[name] = 'memory';
            continue;
        }
        if (!force && storageWorks(win, name)) continue;
        result[name] = defineGetter(win, name, new MemoryStorage()) ? 'memory' : 'unavailable';
        if (result[name] === 'memory') done.add(name);
    }

    const document = win.document as Document | undefined;
    if (document === undefined) return result;
    if (done.has('cookie')) {
        result.cookie = 'memory';
    } else if (force || !cookieWorks(document)) {
        const jar = new MemoryCookieJar();
        const replaced = defineAccessor(
            document,
            'cookie',
            () => jar.read(),
            (value) => jar.write(String(value))
        );
        result.cookie = replaced ? 'memory' : 'unavailable';
        if (replaced) done.add('cookie');
    }
    return result;
}

function storageWorks(win: Window, name: (typeof STORAGE_NAMES)[number]): boolean {
    try {
        const storage = win[name];
        if (!storage) return false;
        storage.setItem(PROBE_KEY, '1');
        storage.removeItem(PROBE_KEY);
        return true;
    } catch {
        return false;
    }
}

function cookieWorks(document: Document): boolean {
    try {
        void document.cookie;
        return true;
    } catch {
        return false;
    }
}

function defineGetter(target: object, name: string, value: unknown): boolean {
    return defineAccessor(target, name, () => value);
}

function defineAccessor(target: object, name: string, get: () => unknown, set?: (value: unknown) => void): boolean {
    try {
        Object.defineProperty(target, name, { configurable: true, enumerable: true, get, ...(set ? { set } : {}) });
        return true;
    } catch {
        return false;
    }
}
