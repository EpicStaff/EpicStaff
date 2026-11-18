import { WHEEL_FILE_SUFFIXES, WHEEL_SUFFIX } from '../models/custom-library.model';
import { VENV_LIBRARY_VERSION_PATTERN } from '../models/venv.model';

/** What the sandbox service refuses to store, checked here so the file is never sent. */
export const MAX_WHEEL_FILE_BYTES = 100 * 1024 * 1024;

// Mirrors DISTRIBUTION_NAME_PATTERN in the sandbox service's CustomLibrary model; keep in sync.
// Held against the canonical spelling, which is the only one this reads a filename into.
const DISTRIBUTION_NAME_PATTERN = /^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/;

// A wheel filename is `{distribution}-{version}-{build}?-{python}-{abi}-{platform}.whl`, so the
// two parts this needs are the first two of at least five.
const WHEEL_NAME_PARTS = 5;

export type StagedWheelIssue =
    | 'unsupported-file'
    | 'too-large'
    | 'unreadable-name'
    | 'other-library'
    | 'duplicate-version';

/** One chosen file, as the dialog shows it: what its name says it is, and what is wrong with it.
 *  A source archive says nothing -- the service renames it and only its build reveals the
 *  distribution and the version -- so both are null for one. */
export interface StagedWheel {
    readonly file: File;
    /** The distribution the wheel's filename names, spelled the way a package index would. */
    readonly distribution: string | null;
    readonly version: string | null;
    readonly issue: StagedWheelIssue | null;
}

export interface StagedWheelsContext {
    /** The library's name once it has one. Without it the first readable wheel names the library. */
    readonly libraryName?: string | null;
    /** Versions the library already holds, which a new wheel must not repeat. */
    readonly storedVersions?: readonly string[];
}

/** How a refused file is labelled, and what the label says when it is asked. */
export const STAGED_WHEEL_ISSUE_TEXT: Record<StagedWheelIssue, { label: string; reason: string }> = {
    'unsupported-file': {
        label: 'Failed',
        reason: 'Not a wheel (.whl) or a source archive (.tar.gz, .tgz, .zip).',
    },
    'too-large': {
        label: 'Failed',
        reason: 'Larger than 100 MB.',
    },
    'unreadable-name': {
        label: 'Failed',
        reason: "A wheel's filename has to say which distribution and version it holds.",
    },
    'other-library': {
        label: 'Other library',
        reason: 'This wheel belongs to another distribution, which would be a library of its own.',
    },
    'duplicate-version': {
        label: 'Failed',
        reason: 'This version is already in the library.',
    },
};

/**
 * Read every chosen file and say what is wrong with it, in the order they were chosen.
 *
 * A library holds one distribution, so the first wheel decides which one that is and every later
 * wheel is held to it. A source archive is taken as it comes: the service stores it under a name
 * of its own and only the build it runs says what the archive held, so there is nothing here to
 * hold it to.
 */
export function diagnoseStagedWheels(files: readonly File[], context: StagedWheelsContext = {}): StagedWheel[] {
    const takenVersions = new Set(context.storedVersions ?? []);
    let libraryName = context.libraryName ? canonicalizeDistribution(context.libraryName) : null;
    const staged: StagedWheel[] = [];

    for (const file of files) {
        const parsed = readWheelFilename(file.name);
        const issue = fileIssue(file, parsed, libraryName, takenVersions);

        if (parsed && issue === null) {
            libraryName ??= parsed.distribution;
            takenVersions.add(parsed.version);
        }

        staged.push({
            file,
            distribution: parsed?.distribution ?? null,
            version: parsed?.version ?? null,
            issue,
        });
    }

    return staged;
}

/** The name the library takes from these files, or null while no wheel among them names one. */
export function detectedLibraryName(staged: readonly StagedWheel[]): string | null {
    return staged.find((wheel) => wheel.issue === null && wheel.distribution !== null)?.distribution ?? null;
}

export function hasIssue(wheel: StagedWheel): boolean {
    return wheel.issue !== null;
}

/**
 * The distribution and version a wheel's filename names, or null when it is not a wheel or its
 * name does not follow the wheel convention.
 *
 * Mirrors what the sandbox service reads off the same name, so a wheel this cannot read is one
 * the service would refuse, and is never sent.
 */
export function readWheelFilename(filename: string): { distribution: string; version: string } | null {
    if (!filename.toLowerCase().endsWith(WHEEL_SUFFIX)) return null;

    const parts = filename.slice(0, filename.length - WHEEL_SUFFIX.length).split('-');
    if (parts.length < WHEEL_NAME_PARTS) return null;

    const distribution = canonicalizeDistribution(parts[0]);
    if (!DISTRIBUTION_NAME_PATTERN.test(distribution)) return null;
    if (!VENV_LIBRARY_VERSION_PATTERN.test(parts[1])) return null;

    return { distribution, version: parts[1] };
}

/** The spelling a package index would use, so `Print_Hello_World` and `print-hello-world` are one. */
export function canonicalizeDistribution(name: string): string {
    return name.replace(/[-_.]+/g, '-').toLowerCase();
}

function fileIssue(
    file: File,
    parsed: { distribution: string; version: string } | null,
    libraryName: string | null,
    takenVersions: ReadonlySet<string>
): StagedWheelIssue | null {
    const lowered = file.name.toLowerCase();
    if (!WHEEL_FILE_SUFFIXES.some((suffix) => lowered.endsWith(suffix))) return 'unsupported-file';
    if (file.size > MAX_WHEEL_FILE_BYTES) return 'too-large';
    // A source archive carries none of what the checks below need, and is not asked for it.
    if (!lowered.endsWith(WHEEL_SUFFIX)) return null;

    if (!parsed) return 'unreadable-name';
    if (libraryName !== null && parsed.distribution !== libraryName) return 'other-library';
    if (takenVersions.has(parsed.version)) return 'duplicate-version';
    return null;
}
