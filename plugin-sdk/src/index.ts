/**
 * The bridge client. The mock host is a separate entry, `@epicstaff/plugin-sdk/mock-host`.
 *
 * `connect()` falls back to an empty mock host through a dynamic `import()`, used only when the
 * page is not framed and no `mock` is given. Bundlers therefore emit the mock as a lazy chunk:
 * it ships in the build (a few KB) but an app inside EpicStaff never downloads it. Import the
 * mock yourself only from a lazily loaded module; a static import puts it, and any sample data,
 * into the initial bundle.
 */
export {
    type BridgeNav,
    type BridgeTheme,
    connect,
    type ConnectOptions,
    type EpicStaffBridge,
    isFramed,
    type MockHostSource,
    type NavSyncConnectOptions,
} from './client.js';
export type { CallOptions, EventHandler } from './connection.js';
export { BridgeCallError, type BridgeCallErrorCode, FlowRunError, type FlowRunFailure } from './errors.js';
export { canonicalNavPath, hashToNavPath } from './nav-path.js';
export { installNavSync, type NavReport, type NavReporter, type NavSync, type NavSyncOptions } from './nav-sync.js';
export * from './protocol.js';
export { DEFAULT_RUN_TIMEOUT_MS, type RunAndWaitOptions } from './run-and-wait.js';
export {
    installStorageShim,
    MemoryCookieJar,
    MemoryStorage,
    type StorageLike,
    type StorageShimOptions,
    type StorageShimResult,
    type StorageShimState,
} from './storage.js';
export { applyTheme } from './theme.js';
