import { formatDate } from '@angular/common';
import { UserSummary } from '@shared/models';

/** Shown in place of a user, date or time that the backend does not know. */
export const AUTHORSHIP_EMPTY_VALUE = '—';
/** Shown for a user that exists but never set a display name (the API never sends an email fallback). */
export const AUTHORSHIP_UNNAMED_USER = 'Unnamed user';
/** Shown when the owner is unknown or has left the organization. */
export const AUTHORSHIP_UNKNOWN_OWNER = 'Unknown';

const TIMESTAMP_LOCALE = 'en-US';
const TIMESTAMP_DATE_FORMAT = 'MMM d, y';
const TIMESTAMP_TIME_FORMAT = 'HH:mm:ss';

/** A moment split into its date and time parts, both in the viewer's local time zone. */
export interface AuthorshipTimestamp {
    /** e.g. `Mar 12, 2026` */
    date: string;
    /** e.g. `13:28:23` */
    time: string;
}

/** Everything one column ("Owner" or "Last editor") needs to render. */
export interface AuthorshipColumn {
    label: string;
    userName: string;
    /** False when there is no user to picture, so the column shows the name placeholder alone. */
    showAvatar: boolean;
    /** Name the avatar takes its initials from; null renders the generic placeholder. */
    avatarName: string | null;
    avatarUrl: string | null;
    /** Null when the moment is unknown — render {@link AUTHORSHIP_EMPTY_VALUE}. */
    timestamp: AuthorshipTimestamp | null;
}

export interface AuthorshipColumnsSource {
    owner: UserSummary | null;
    createdAt: string | null;
    lastEditor: UserSummary | null;
    lastEditedAt: string | null;
}

export function buildAuthorshipColumns(source: AuthorshipColumnsSource): AuthorshipColumn[] {
    return [
        {
            label: 'Owner',
            userName: resolveUserName(source.owner, AUTHORSHIP_UNKNOWN_OWNER),
            // An unknown owner still is a person, so it keeps the placeholder avatar.
            showAvatar: true,
            avatarName: source.owner?.display_name ?? null,
            avatarUrl: source.owner?.avatar_url ?? null,
            timestamp: formatAuthorshipTimestamp(source.createdAt),
        },
        {
            label: 'Last editor',
            userName: resolveUserName(source.lastEditor, AUTHORSHIP_EMPTY_VALUE),
            showAvatar: source.lastEditor !== null,
            avatarName: source.lastEditor?.display_name ?? null,
            avatarUrl: source.lastEditor?.avatar_url ?? null,
            timestamp: formatAuthorshipTimestamp(source.lastEditedAt),
        },
    ];
}

/** The user's display name, or a fallback when the user or their display name is missing. */
export function resolveUserName(user: UserSummary | null, missingUserLabel: string): string {
    if (user === null) {
        return missingUserLabel;
    }
    return user.display_name?.trim() || AUTHORSHIP_UNNAMED_USER;
}

/** Splits an ISO 8601 timestamp into local date and time; null for a missing or unparseable value. */
export function formatAuthorshipTimestamp(value: string | null): AuthorshipTimestamp | null {
    if (!value) {
        return null;
    }
    const moment = new Date(value);
    if (Number.isNaN(moment.getTime())) {
        return null;
    }
    return {
        date: formatDate(moment, TIMESTAMP_DATE_FORMAT, TIMESTAMP_LOCALE),
        time: formatDate(moment, TIMESTAMP_TIME_FORMAT, TIMESTAMP_LOCALE),
    };
}
