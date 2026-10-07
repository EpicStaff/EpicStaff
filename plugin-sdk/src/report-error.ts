/** Reports an error from app code the SDK called (a handler or callback) without letting it change the SDK's flow. */
export function reportCallbackError(error: unknown): void {
    const report = (globalThis as { reportError?: (error: unknown) => void }).reportError;
    if (typeof report === 'function') report(error);
    else console.error(error);
}

/** Calls an optional app callback; a throw is reported, never propagated. */
export function notify<Value>(callback: ((value: Value) => void) | undefined, value: Value): void {
    if (!callback) return;
    try {
        callback(value);
    } catch (error) {
        reportCallbackError(error);
    }
}
