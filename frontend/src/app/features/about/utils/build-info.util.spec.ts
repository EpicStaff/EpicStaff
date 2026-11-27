import { FrontendBuild, SystemInfo } from '../models/system-info.model';
import { buildKind, buildLabel, diagnosticsText, isBuildMismatch, shortBuildLabel } from './build-info.util';

const SHA = '3f9c2a1e8b7d4c5a6e9f0123456789abcdef0123';
const OTHER_SHA = '9b41d07c22aa4c5a6e9f0123456789abcdef0123';

function systemInfo(overrides: Partial<SystemInfo> = {}): SystemInfo {
    return {
        version: 'v1.6.0',
        git_ref: 'main',
        git_sha: SHA,
        commit_date: '2026-11-24T08:00:00Z',
        import_version: 6,
        features: { chats: true, plugins: false, session_audit: true, user_audit: false },
        ...overrides,
    };
}

const FRONTEND: FrontendBuild = { gitSha: SHA, commitDate: '2026-11-24T08:00:00Z' };
const PAGE = { origin: 'https://host', pathname: '/flows/12' };
const NOW = new Date('2026-11-24T12:00:00.000Z');

describe('buildLabel', () => {
    it('shows the version of a release', () => {
        expect(buildLabel(systemInfo())).toBe('v1.6.0');
    });

    it('shows the branch and the short commit of a build without a version', () => {
        expect(buildLabel(systemInfo({ version: null, git_ref: 'developer' }))).toBe('developer · 3f9c2a1');
    });

    it.each([
        ['version, ref and sha are all missing', { version: null, git_ref: null, git_sha: null }],
        ['the ref is missing', { version: null, git_ref: null }],
        ['the sha is missing', { version: null, git_sha: null }],
    ])('says local when %s', (_name, overrides) => {
        expect(buildLabel(systemInfo(overrides))).toBe('local');
    });
});

describe('shortBuildLabel', () => {
    it.each([
        ['the version of a release', {}, 'v1.6.0'],
        [
            'the short commit, not the branch, of a build without a version',
            { version: null, git_ref: 'feat/a-very-long-branch-name' },
            '3f9c2a1',
        ],
        ['local when version, ref and sha are all missing', { version: null, git_ref: null, git_sha: null }, 'local'],
        ['local when the ref is missing', { version: null, git_ref: null }, 'local'],
        ['local when the sha is missing', { version: null, git_sha: null }, 'local'],
    ])('shows %s', (_name, overrides, expected) => {
        expect(shortBuildLabel(systemInfo(overrides))).toBe(expected);
    });
});

describe('buildKind', () => {
    it.each([
        ['a release', {}, 'Release'],
        ['a branch build', { version: null }, 'Developer build'],
        ['a build with no commit', { version: null, git_sha: null }, 'Local build'],
    ])('calls %s the right kind', (_name, overrides, expected) => {
        expect(buildKind(systemInfo(overrides))).toBe(expected);
    });
});

describe('isBuildMismatch', () => {
    it('is true when both commits are known and differ', () => {
        expect(isBuildMismatch(systemInfo({ git_sha: OTHER_SHA }), FRONTEND)).toBe(true);
    });

    it('is false when the commits match', () => {
        expect(isBuildMismatch(systemInfo(), FRONTEND)).toBe(false);
    });

    it('is false when either commit is unknown', () => {
        expect(isBuildMismatch(systemInfo({ git_sha: null }), FRONTEND)).toBe(false);
        expect(isBuildMismatch(systemInfo(), { gitSha: null, commitDate: null })).toBe(false);
    });
});

describe('diagnosticsText', () => {
    it('lists the build, the features, the browser and the page', () => {
        expect(diagnosticsText(systemInfo(), FRONTEND, PAGE, 'TestBrowser/1.0', NOW)).toBe(
            [
                'EpicStaff v1.6.0',
                'Branch: main',
                `Backend commit: ${SHA} (2026-11-24)`,
                `Frontend commit: ${SHA} (2026-11-24)`,
                'Import/export format: 6',
                'Chats: on · Plugins: off · Session audit: on · User audit: off',
                'Browser: TestBrowser/1.0',
                'Page: https://host/flows/12',
                'Copied: 2026-11-24T12:00:00.000Z',
            ].join('\n')
        );
    });

    it('writes unknown for a missing commit, date or branch', () => {
        const text = diagnosticsText(
            systemInfo({ version: null, git_ref: null, git_sha: null, commit_date: null }),
            { gitSha: null, commitDate: null },
            PAGE,
            'TestBrowser/1.0',
            NOW
        );

        expect(text).toContain('EpicStaff local\nBranch: unknown\n');
        expect(text).toContain('Backend commit: unknown (unknown)');
        expect(text).toContain('Frontend commit: unknown (unknown)');
    });

    it('drops query and hash: the page is built from origin and pathname only', () => {
        const text = diagnosticsText(systemInfo(), FRONTEND, PAGE, 'TestBrowser/1.0', NOW);

        expect(text).toContain('Page: https://host/flows/12\n');
        expect(text).not.toContain('?');
        expect(text).not.toContain('#');
    });
});
