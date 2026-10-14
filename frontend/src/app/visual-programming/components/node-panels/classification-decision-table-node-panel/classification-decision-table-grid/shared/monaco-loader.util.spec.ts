type AmdRequire = ((deps: string[], onLoad: () => void, onError?: () => void) => void) & {
    config?: (options: Record<string, unknown>) => void;
};

interface TestWindow {
    monaco?: { editor?: { colorize?: unknown } };
    require?: AmdRequire;
}

type Loader = typeof import('./monaco-loader.util');

const testWindow = window as unknown as TestWindow;

/** The loader keeps its promise and failure count in module state; each test gets its own. */
async function freshLoader(): Promise<Loader> {
    vi.resetModules();
    return import('./monaco-loader.util');
}

function loaderScripts(): HTMLScriptElement[] {
    return Array.from(document.head.querySelectorAll<HTMLScriptElement>('script[src$="loader.js"]'));
}

/** Resolves to true when `promise` settles before the next macrotask. */
async function settles(promise: Promise<void>): Promise<boolean> {
    let settled = false;
    void promise.then(() => (settled = true));
    await new Promise((resolve) => setTimeout(resolve));
    return settled;
}

/** An AMD `require` whose module load fails the way RequireJS reports it: asynchronously. */
function failingAmdRequire(): AmdRequire & ReturnType<typeof vi.fn> {
    const amdRequire = vi.fn((_deps: string[], _onLoad: () => void, onError?: () => void) => {
        setTimeout(() => onError?.());
    }) as unknown as AmdRequire & ReturnType<typeof vi.fn>;
    amdRequire.config = vi.fn();
    return amdRequire;
}

/** Runs one failed attempt through a 404 on `loader.js`. */
async function failByNotFound(loader: Loader): Promise<void> {
    const attempt = loader.ensureMonacoLoaded();
    loaderScripts().at(-1)?.onerror?.(new Event('error'));
    await attempt;
}

/** Before as well as after: a spec that rendered the grid earlier in the run may have left a loader behind. */
function clearMonacoGlobals(): void {
    delete testWindow.monaco;
    delete testWindow.require;
    loaderScripts().forEach((script) => script.remove());
}

beforeEach(clearMonacoGlobals);
afterEach(clearMonacoGlobals);

describe('ensureMonacoLoaded', () => {
    it('resolves at once, loading nothing, when Monaco is already there', async () => {
        const loader = await freshLoader();
        testWindow.monaco = { editor: { colorize: () => Promise.resolve('') } };

        await loader.ensureMonacoLoaded();

        expect(loaderScripts()).toHaveLength(0);
    });

    it('shares one load between callers racing on first paint', async () => {
        const loader = await freshLoader();

        const first = loader.ensureMonacoLoaded();

        expect(loader.ensureMonacoLoaded()).toBe(first);
        expect(loaderScripts()).toHaveLength(1);
    });

    it('settles when loader.js answers 200 without defining require, and lets the next call retry', async () => {
        const loader = await freshLoader();
        const attempt = loader.ensureMonacoLoaded();

        // An SPA fallback serving index.html for the missing file.
        loaderScripts()[0].onload?.(new Event('load'));

        expect(await settles(attempt)).toBe(true);

        loader.ensureMonacoLoaded();
        expect(loaderScripts()).toHaveLength(2);
    });

    it('removes the dead script and settles when loader.js fails to load', async () => {
        const loader = await freshLoader();
        const attempt = loader.ensureMonacoLoaded();
        const script = loaderScripts()[0];

        script.onerror?.(new Event('error'));

        expect(await settles(attempt)).toBe(true);
        expect(script.isConnected).toBe(false);
    });

    it('settles through the errback when the AMD loader is present but the editor fails', async () => {
        const loader = await freshLoader();
        const amdRequire = failingAmdRequire();
        testWindow.require = amdRequire;

        expect(await settles(loader.ensureMonacoLoaded())).toBe(true);
        expect(amdRequire).toHaveBeenCalledTimes(1);
        expect(loaderScripts()).toHaveLength(0);
    });

    it('stops retrying after three failed attempts', async () => {
        const loader = await freshLoader();

        await failByNotFound(loader);
        await failByNotFound(loader);
        await failByNotFound(loader);
        const scriptsBefore = document.head.querySelectorAll('script').length;

        expect(await settles(loader.ensureMonacoLoaded())).toBe(true);
        expect(document.head.querySelectorAll('script')).toHaveLength(scriptsBefore);
    });

    it('stops calling the AMD loader after three failed attempts', async () => {
        const loader = await freshLoader();
        const amdRequire = failingAmdRequire();
        testWindow.require = amdRequire;

        for (let attempt = 0; attempt < 3; attempt++) await loader.ensureMonacoLoaded();
        await loader.ensureMonacoLoaded();

        expect(amdRequire).toHaveBeenCalledTimes(3);
    });

    // `giveUp` clears `monacoLoadPromise`, but when it runs synchronously inside
    // the Promise executor (the `catch` around `require.config`, or an errback the
    // AMD loader calls synchronously) it does so before the executor returns, and
    // the outer `monacoLoadPromise = new Promise(...)` then stores the settled
    // promise. Every later call returns that cached promise: no retry, ever.
    it('lets the next call retry after a synchronous failure', async () => {
        const loader = await freshLoader();
        const amdRequire = vi.fn() as unknown as AmdRequire & ReturnType<typeof vi.fn>;
        amdRequire.config = vi.fn(() => {
            throw new Error('config failed');
        });
        testWindow.require = amdRequire;

        await loader.ensureMonacoLoaded();
        await loader.ensureMonacoLoaded();

        expect(amdRequire.config).toHaveBeenCalledTimes(2);
    });
});
