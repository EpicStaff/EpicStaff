import { FrontendBuild, SystemInfo } from '../models/system-info.model';

/** Shown, and copied, for a branch, commit or date that the build does not know. */
export const UNKNOWN = 'unknown';
const SHORT_SHA_LENGTH = 7;
const DAY_LENGTH = 10;

/** `v1.6.0` for a release, `developer · 3f9c2a1` for a branch build, `local` when the build is not known. */
export function buildLabel(info: SystemInfo): string {
    if (info.version) {
        return info.version;
    }
    if (info.git_ref && info.git_sha) {
        return `${info.git_ref} · ${shortSha(info.git_sha)}`;
    }
    return 'local';
}

/**
 * The build in a few characters, for places with little room (the collapsed sidebar, the Help menu, the About
 * dialog's header): `v1.6.0` for a release, the short commit `3f9c2a1` for a branch build, `local` when the build is
 * not known. Never cut: the branch, which can be long, is left to `buildLabel`.
 */
export function shortBuildLabel(info: SystemInfo): string {
    if (info.version) {
        return info.version;
    }
    if (info.git_ref && info.git_sha) {
        return shortSha(info.git_sha);
    }
    return 'local';
}

/** The first characters of a commit hash, as git shows it. */
export function shortSha(sha: string): string {
    return sha.slice(0, SHORT_SHA_LENGTH);
}

export type BuildKind = 'Release' | 'Developer build' | 'Local build';

/** The chip next to the version: a tagged release, a build of a branch, or a build with no commit information. */
export function buildKind(info: SystemInfo): BuildKind {
    if (info.version) {
        return 'Release';
    }
    return info.git_ref && info.git_sha ? 'Developer build' : 'Local build';
}

/** Only a difference between two known commits counts: an unknown side proves nothing. */
export function isBuildMismatch(info: SystemInfo, frontend: FrontendBuild): boolean {
    return info.git_sha !== null && frontend.gitSha !== null && info.git_sha !== frontend.gitSha;
}

/** The calendar day of an ISO timestamp (`2026-11-24T09:30:00Z` gives `2026-11-24`). */
function commitDay(date: string): string {
    return date.slice(0, DAY_LENGTH);
}

function commitLine(sha: string | null, date: string | null): string {
    return `${sha ?? UNKNOWN} (${date ? commitDay(date) : UNKNOWN})`;
}

function onOff(enabled: boolean): string {
    return enabled ? 'on' : 'off';
}

/** What the About dialog's Copy button puts on the clipboard, for a bug report. The page's query and hash are left out. */
export function diagnosticsText(
    info: SystemInfo,
    frontend: FrontendBuild,
    page: { origin: string; pathname: string },
    userAgent: string,
    now: Date
): string {
    const { features } = info;
    return [
        `EpicStaff ${buildLabel(info)}`,
        `Branch: ${info.git_ref ?? UNKNOWN}`,
        `Backend commit: ${commitLine(info.git_sha, info.commit_date)}`,
        `Frontend commit: ${commitLine(frontend.gitSha, frontend.commitDate)}`,
        `Import/export format: ${info.import_version}`,
        `Chats: ${onOff(features.chats)} · Plugins: ${onOff(features.plugins)} · Session audit: ${onOff(features.session_audit)} · User audit: ${onOff(features.user_audit)}`,
        `Browser: ${userAgent}`,
        `Page: ${page.origin}${page.pathname}`,
        `Copied: ${now.toISOString()}`,
    ].join('\n');
}
