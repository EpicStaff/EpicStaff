import { Component, computed, input } from '@angular/core';
import { UserSummary } from '@shared/models';

import {
    AUTHORSHIP_EMPTY_VALUE,
    formatAuthorshipTimestamp,
    resolveUserName,
} from '../authorship-details/authorship-details.util';

interface AuthorshipFooterColumn {
    /** "Created by" / "Edited by", shown on the left of the user name. */
    label: string;
    /** The user's name; the empty value stands in for an unknown user. */
    userName: string;
    /** `<date>, <time>`, shown below the name; the empty value stands in for an unknown moment. */
    when: string;
}

/**
 * Compact "Created by" / "Edited by" columns for the bottom of a window, side by side: the label and the user name
 * on one line, the date and time below. The text-only sibling of app-authorship-details, with the same name, date
 * and time formatting and the same fallbacks, but no avatars.
 */
@Component({
    selector: 'app-authorship-footer',
    templateUrl: './authorship-footer.component.html',
    styleUrls: ['./authorship-footer.component.scss'],
})
export class AuthorshipFooterComponent {
    readonly createdBy = input.required<UserSummary | null>();
    readonly createdAt = input.required<string | null>();
    readonly lastEditedBy = input.required<UserSummary | null>();
    readonly lastEditedAt = input.required<string | null>();

    protected readonly columns = computed<AuthorshipFooterColumn[]>(() => [
        buildColumn('Created by', this.createdBy(), this.createdAt()),
        buildColumn('Edited by', this.lastEditedBy(), this.lastEditedAt()),
    ]);
}

function buildColumn(label: string, user: UserSummary | null, moment: string | null): AuthorshipFooterColumn {
    const timestamp = formatAuthorshipTimestamp(moment);
    return {
        label,
        userName: user === null ? AUTHORSHIP_EMPTY_VALUE : resolveUserName(user),
        when: timestamp === null ? AUTHORSHIP_EMPTY_VALUE : `${timestamp.date}, ${timestamp.time}`,
    };
}
