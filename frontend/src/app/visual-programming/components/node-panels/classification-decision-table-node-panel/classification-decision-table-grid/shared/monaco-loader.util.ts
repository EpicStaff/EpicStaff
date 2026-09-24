/**
 * One-time loader for the Monaco AMD bundle, for the CDT panel's read-only views
 * that want `colorize()` — highlighted HTML at a fraction of an editor's cost.
 *
 * The promise is module-level so two callers racing on first paint share one fetch.
 * A failed load resolves rather than rejects: a caller that cannot colour text
 * falls back to plain text, it does not break.
 */

interface MonacoEditorApi {
    colorize?: (text: string, lang: string, opts: Record<string, unknown>) => Promise<string>;
    setTheme?: (theme: string) => void;
}

interface MonacoWindow extends Window {
    monaco?: { editor?: MonacoEditorApi };
    require?: { config?: (opts: Record<string, unknown>) => void } & ((
        deps: string[],
        cb: () => void,
        errback?: () => void
    ) => void);
}

const MONACO_VS_PATH = 'assets/monaco/min/vs';

/**
 * Retries allowed across the page's lifetime. The callers are not one-shot — the
 * code view re-runs per block opened, the cell renderer per cell and per virtual
 * scroll recycle — so without a ceiling a misconfigured deployment collects one
 * dead `<script>` and one 404 per interaction.
 */
const MAX_LOAD_ATTEMPTS = 3;

let monacoLoadPromise: Promise<void> | null = null;
let failedAttempts = 0;

/** The `monaco.editor` API, or undefined until `ensureMonacoLoaded()` resolves. */
export function monacoEditorApi(): MonacoEditorApi | undefined {
    return (window as unknown as MonacoWindow).monaco?.editor;
}

export function ensureMonacoLoaded(): Promise<void> {
    if (monacoEditorApi()?.colorize) {
        return Promise.resolve();
    }
    if (monacoLoadPromise) {
        return monacoLoadPromise;
    }
    if (failedAttempts >= MAX_LOAD_ATTEMPTS) {
        return Promise.resolve();
    }

    monacoLoadPromise = new Promise<void>((resolve) => {
        const win = window as unknown as MonacoWindow;

        /** Give up on this attempt, and let the next caller start a fresh one. */
        const giveUp = (): void => {
            failedAttempts += 1;
            monacoLoadPromise = null;
            resolve();
        };

        // The AMD loader is already present when `ngx-monaco-editor-v2` has booted
        // an editor somewhere in the app; only the bundle itself is missing.
        if (win.require?.config) {
            try {
                win.require.config({ paths: { vs: MONACO_VS_PATH } });
                // `giveUp` is RequireJS's errback: without it a module that fails to
                // load goes to the global `require.onError` and this never settles.
                win.require(['vs/editor/editor.main'], () => resolve(), giveUp);
            } catch {
                giveUp();
            }
            return;
        }

        const script = document.createElement('script');
        script.src = `${MONACO_VS_PATH}/loader.js`;

        // `onload` fires for any 200, including an SPA `try_files` fallback serving
        // index.html. `win.require` is then undefined and this handler throws after
        // the executor has returned — hanging the promise for the life of the page
        // and making the retry unreachable. Hence the try/catch.
        script.onload = () => {
            try {
                win.require!.config!({ paths: { vs: MONACO_VS_PATH } });
                win.require!(['vs/editor/editor.main'], () => resolve(), giveUp);
            } catch {
                giveUp();
            }
        };
        script.onerror = () => {
            script.remove();
            giveUp();
        };

        document.head.appendChild(script);
    });

    return monacoLoadPromise;
}
