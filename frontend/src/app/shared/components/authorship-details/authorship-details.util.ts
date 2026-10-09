import { formatDate } from '@angular/common';
import { UserSummary } from '@shared/models';

/** Shown in place of a user, date or time that the backend does not know. */
export const AUTHORSHIP_EMPTY_VALUE = '—';
/** Shown for a user that exists but never set a display name (the API never sends an email fallback). */
export const AUTHORSHIP_UNNAMED_USER = 'Unnamed user';

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
        buildAuthorshipColumn('Owner', source.owner, source.createdAt),
        buildAuthorshipColumn('Last editor', source.lastEditor, source.lastEditedAt),
    ];
}

/**
 * One column, with the same fallbacks for "Owner" and "Last editor":
 * - a user: their name (or {@link AUTHORSHIP_UNNAMED_USER}) and avatar;
 * - no user (never recorded, or cleared when they left the organization): {@link AUTHORSHIP_EMPTY_VALUE}
 *   without an avatar.
 * The moment shows whenever it is known, independently of the user; a missing or unparseable one (e.g. rows
 * older than the timestamp column) renders as the empty value.
 */
export function buildAuthorshipColumn(
    label: string,
    user: UserSummary | null,
    moment: string | null
): AuthorshipColumn {
    const timestamp = formatAuthorshipTimestamp(moment);
    if (user === null) {
        return {
            label,
            userName: AUTHORSHIP_EMPTY_VALUE,
            showAvatar: false,
            avatarName: null,
            avatarUrl: null,
            timestamp,
        };
    }
    return {
        label,
        userName: resolveUserName(user),
        showAvatar: true,
        avatarName: user.display_name,
        avatarUrl: user.avatar_url,
        timestamp,
    };
}

/** The user's display name, or {@link AUTHORSHIP_UNNAMED_USER} when they never set one. */
export function resolveUserName(user: UserSummary): string {
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
