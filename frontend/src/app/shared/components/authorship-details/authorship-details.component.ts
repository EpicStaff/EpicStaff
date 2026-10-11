import { Component, computed, input } from '@angular/core';
import { UserSummary } from '@shared/models';

import { UserAvatarComponent } from '../user-avatar/user-avatar.component';
import { AUTHORSHIP_EMPTY_VALUE, buildAuthorshipColumns } from './authorship-details.util';

/**
 * Two-column "Owner" / "Last editor" block for any authored resource: avatar, name, and the
 * date + time of creation / last edit in the viewer's local time zone. Purely presentational —
 * the host decides where the data comes from and which dialog or panel wraps it.
 */
@Component({
    selector: 'app-authorship-details',
    imports: [UserAvatarComponent],
    templateUrl: './authorship-details.component.html',
    styleUrls: ['./authorship-details.component.scss'],
})
export class AuthorshipDetailsComponent {
    readonly owner = input.required<UserSummary | null>();
    readonly createdAt = input.required<string | null>();
    readonly lastEditor = input.required<UserSummary | null>();
    readonly lastEditedAt = input.required<string | null>();

    protected readonly columns = computed(() =>
        buildAuthorshipColumns({
            owner: this.owner(),
            createdAt: this.createdAt(),
            lastEditor: this.lastEditor(),
            lastEditedAt: this.lastEditedAt(),
        })
    );

    protected readonly emptyValue = AUTHORSHIP_EMPTY_VALUE;
}
