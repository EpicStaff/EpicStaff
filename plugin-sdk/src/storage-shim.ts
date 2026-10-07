/**
 * Side-effect entry: import it first thing in the app's entry file, before any library that may
 * touch storage at import time:
 *
 * ```ts
 * import '@epicstaff/plugin-sdk/storage-shim';
 * ```
 *
 * It replaces `localStorage`, `sessionStorage` and `document.cookie` with in-memory stand-ins
 * wherever the browser throws on access. To replace them even where they work, call
 * `installStorageShim({ force: true })` afterwards.
 */
import { installStorageShim } from './storage.js';

export { installStorageShim, MemoryCookieJar, MemoryStorage } from './storage.js';
export type { StorageLike, StorageShimOptions, StorageShimResult, StorageShimState } from './storage.js';

installStorageShim();
