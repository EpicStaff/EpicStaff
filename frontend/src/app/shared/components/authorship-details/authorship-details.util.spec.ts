import { UserSummary } from '@shared/models';

import {
    AUTHORSHIP_EMPTY_VALUE,
    AUTHORSHIP_UNNAMED_USER,
    AuthorshipColumn,
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
        expect(resolveUserName(IVAN)).toBe('Ivan Bohun');
    });

    it('falls back to "Unnamed user" for a user without a display name', () => {
        expect(resolveUserName(UNNAMED)).toBe(AUTHORSHIP_UNNAMED_USER);
        expect(resolveUserName({ ...IVAN, display_name: '   ' })).toBe(AUTHORSHIP_UNNAMED_USER);
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

const TIMESTAMP = { date: 'Mar 12, 2026', time: '13:28:23' };

/** Builds both columns with the same user and moment, so every case is checked for Owner and Last editor alike. */
function columns(user: UserSummary | null, moment: string | null): AuthorshipColumn[] {
    return buildAuthorshipColumns({ owner: user, createdAt: moment, lastEditor: user, lastEditedAt: moment });
}

describe('buildAuthorshipColumns', () => {
    it('labels the columns "Owner" and "Last editor", from created_* and last_edited_* respectively', () => {
        const [owner, lastEditor] = buildAuthorshipColumns({
            owner: IVAN,
            createdAt: LOCAL_MOMENT,
            lastEditor: UNNAMED,
            lastEditedAt: null,
        });

        expect(owner.label).toBe('Owner');
        expect(owner.userName).toBe('Ivan Bohun');
        expect(owner.timestamp).toEqual(TIMESTAMP);
        expect(lastEditor.label).toBe('Last editor');
        expect(lastEditor.userName).toBe(AUTHORSHIP_UNNAMED_USER);
        expect(lastEditor.timestamp).toBeNull();
    });

    describe.each([0, 1])('column %i', (index) => {
        it('shows a user with their name, avatar and moment', () => {
            expect(columns(IVAN, LOCAL_MOMENT)[index]).toMatchObject({
                userName: 'Ivan Bohun',
                showAvatar: true,
                avatarName: 'Ivan Bohun',
                avatarUrl: null,
                timestamp: TIMESTAMP,
            });
            expect(columns(UNNAMED, LOCAL_MOMENT)[index]).toMatchObject({
                userName: AUTHORSHIP_UNNAMED_USER,
                showAvatar: true,
                avatarName: null,
                avatarUrl: 'https://cdn.example/avatar.png',
            });
        });

        it('shows a user without a recorded moment (legacy rows) with their name and an empty date', () => {
            expect(columns(IVAN, null)[index]).toMatchObject({
                userName: 'Ivan Bohun',
                showAvatar: true,
                timestamp: null,
            });
        });

        it('shows a missing user with a known moment as a dash without an avatar, keeping the moment', () => {
            expect(columns(null, LOCAL_MOMENT)[index]).toEqual({
                label: index === 0 ? 'Owner' : 'Last editor',
                userName: AUTHORSHIP_EMPTY_VALUE,
                showAvatar: false,
                avatarName: null,
                avatarUrl: null,
                timestamp: TIMESTAMP,
            });
        });

        it('shows a missing user without a moment as an empty value, without an avatar', () => {
            expect(columns(null, null)[index]).toMatchObject({
                userName: AUTHORSHIP_EMPTY_VALUE,
                showAvatar: false,
                timestamp: null,
            });
        });

        it('treats an unparseable moment as missing', () => {
            expect(columns(null, 'not a date')[index]).toMatchObject({
                userName: AUTHORSHIP_EMPTY_VALUE,
                showAvatar: false,
                timestamp: null,
            });
        });
    });
});
