import { UserSummary } from '@shared/models';

import {
    AUTHORSHIP_EMPTY_VALUE,
    AUTHORSHIP_UNKNOWN_OWNER,
    AUTHORSHIP_UNNAMED_USER,
    buildAuthorshipColumns,
    formatAuthorshipTimestamp,
    resolveUserName,
} from './authorship-details.util';

const IVAN: UserSummary = { id: 1, display_name: 'Ivan Bohun', avatar_url: null };
const UNNAMED: UserSummary = { id: 2, display_name: null, avatar_url: 'https://cdn.example/avatar.png' };

// Built from local-time parts so the expectation holds in any time zone the tests run in.
const LOCAL_MOMENT = new Date(2026, 2, 12, 13, 28, 23).toISOString();

describe('resolveUserName', () => {
    it('returns the display name', () => {
        expect(resolveUserName(IVAN, AUTHORSHIP_UNKNOWN_OWNER)).toBe('Ivan Bohun');
    });

    it('falls back to "Unnamed user" for a user without a display name', () => {
        expect(resolveUserName(UNNAMED, AUTHORSHIP_UNKNOWN_OWNER)).toBe(AUTHORSHIP_UNNAMED_USER);
        expect(resolveUserName({ ...IVAN, display_name: '   ' }, AUTHORSHIP_UNKNOWN_OWNER)).toBe(
            AUTHORSHIP_UNNAMED_USER
        );
    });

    it('falls back to the given label when there is no user', () => {
        expect(resolveUserName(null, AUTHORSHIP_UNKNOWN_OWNER)).toBe('Unknown');
        expect(resolveUserName(null, AUTHORSHIP_EMPTY_VALUE)).toBe('—');
    });
});

describe('formatAuthorshipTimestamp', () => {
    it('splits the moment into a local date and a 24-hour local time', () => {
        expect(formatAuthorshipTimestamp(LOCAL_MOMENT)).toEqual({ date: 'Mar 12, 2026', time: '13:28:23' });
    });

    it('is null for a missing or unparseable value', () => {
        expect(formatAuthorshipTimestamp(null)).toBeNull();
        expect(formatAuthorshipTimestamp('')).toBeNull();
        expect(formatAuthorshipTimestamp('not a date')).toBeNull();
    });
});

describe('buildAuthorshipColumns', () => {
    it('renders the owner and the last editor with their avatars and timestamps', () => {
        const [owner, lastEditor] = buildAuthorshipColumns({
            owner: IVAN,
            createdAt: LOCAL_MOMENT,
            lastEditor: UNNAMED,
            lastEditedAt: LOCAL_MOMENT,
        });

        expect(owner).toEqual({
            label: 'Owner',
            userName: 'Ivan Bohun',
            showAvatar: true,
            avatarName: 'Ivan Bohun',
            avatarUrl: null,
            timestamp: { date: 'Mar 12, 2026', time: '13:28:23' },
        });
        expect(lastEditor).toEqual({
            label: 'Last editor',
            userName: 'Unnamed user',
            showAvatar: true,
            avatarName: null,
            avatarUrl: 'https://cdn.example/avatar.png',
            timestamp: { date: 'Mar 12, 2026', time: '13:28:23' },
        });
    });

    it('shows an unknown owner with a placeholder avatar and no timestamp for a config without created_at', () => {
        const [owner] = buildAuthorshipColumns({
            owner: null,
            createdAt: null,
            lastEditor: null,
            lastEditedAt: null,
        });

        expect(owner).toEqual({
            label: 'Owner',
            userName: 'Unknown',
            showAvatar: true,
            avatarName: null,
            avatarUrl: null,
            timestamp: null,
        });
    });

    it('shows a never-edited resource as an empty last editor without an avatar', () => {
        const [, lastEditor] = buildAuthorshipColumns({
            owner: IVAN,
            createdAt: LOCAL_MOMENT,
            lastEditor: null,
            lastEditedAt: null,
        });

        expect(lastEditor).toEqual({
            label: 'Last editor',
            userName: '—',
            showAvatar: false,
            avatarName: null,
            avatarUrl: null,
            timestamp: null,
        });
    });
});
