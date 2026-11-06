import { VenvOwner } from './venv.model';

// Mirrors WHEEL_SUFFIX in the sandbox service's Wheel model; keep in sync. The only upload that can
// create a library, because it is the only one with a name before it is stored.
export const WHEEL_SUFFIX = '.whl';

// Mirrors WHEEL_SUFFIX and SOURCE_ARCHIVE_SUFFIXES in the sandbox service's Wheel model; keep in
// sync. A wheel is stored as it is, a source archive is built into one.
export const WHEEL_FILE_SUFFIXES = [WHEEL_SUFFIX, '.tar.gz', '.tgz', '.zip'] as const;

// The sandbox_new wheel lifecycle, mirrored from the service's WheelStatus enum. The same four
// values as a venv's, so the venv status badge renders them.
export type WheelStatus = 'declared' | 'processing' | 'completed' | 'failed';

/** The statuses a wheel is in while its build is still ahead of it or under way. A version in one
 *  of them has no number yet, and the one that holds it is still being decided. */
export const BUILDING_WHEEL_STATUSES: ReadonlySet<WheelStatus> = new Set<WheelStatus>(['declared', 'processing']);

// One version of a custom library. `version` is read off the built wheel, so it stays null until
// the build finished. Which filename is set says how the version arrived: a ready-made wheel was
// uploaded, or a source archive was built into one.
export interface Wheel {
    id: number;
    version: string | null;
    status: WheelStatus;
    error: string | null;
    source_filename: string | null;
    wheel_filename: string | null;
    created_at: string;
}

// The gateway injects `owner` from its org-scoped binding row; the sandbox_new payload carries the
// rest. `owner` is null when no person created the library -- an API key, a plugin service account.
// `name` is null when the library was created from a source archive still waiting to build: the
// distribution it names itself after is not known until that build succeeds.
export interface CustomLibrary {
    id: number;
    name: string | null;
    owner: VenvOwner | null;
    // Where the library's versions stand, taken together: a failed build is reported ahead of
    // one still running, and `null` means the library holds no version at all. `error` is the
    // failed version's, and is set only alongside `failed`.
    status: WheelStatus | null;
    error: string | null;
    created_at: string;
    updated_at: string;
}

// Like the venv list envelope, this one passes through sandbox_new and uses `result` (singular),
// not the `results` of the shared `ApiGetRequest`.
export interface CustomLibraryListResponse {
    count: number;
    limit: number;
    offset: number;
    next: string | null;
    previous: string | null;
    result: CustomLibrary[];
}
