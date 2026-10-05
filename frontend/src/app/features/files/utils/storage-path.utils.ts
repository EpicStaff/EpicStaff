/** Storage path without surrounding slashes: backslashes become "/" and repeated slashes collapse. */
export function normalizeStoragePath(path: string): string {
    return path
        .trim()
        .replace(/\\/g, '/')
        .replace(/\/{2,}/g, '/')
        .replace(/^\/+|\/+$/g, '');
}
