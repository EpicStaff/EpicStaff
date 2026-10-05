import { Dialog, DialogRef } from '@angular/cdk/dialog';
import { inject, Injectable } from '@angular/core';

import {
    AuthorshipDetailsDialogComponent,
    AuthorshipDetailsDialogData,
    AuthorshipDetailsSource,
} from './authorship-details-dialog.component';

@Injectable({
    providedIn: 'root',
})
export class AuthorshipDetailsDialogService {
    private readonly dialog = inject(Dialog);
    private openedCount = 0;

    /** Shows who created and who last edited `resource` under the given heading. */
    open(title: string, resource: AuthorshipDetailsSource): DialogRef<void, AuthorshipDetailsDialogComponent> {
        const titleId = `authorship-details-dialog-title-${++this.openedCount}`;
        // Only the authorship fields travel into the dialog, never the whole resource.
        return this.dialog.open<void, AuthorshipDetailsDialogData, AuthorshipDetailsDialogComponent>(
            AuthorshipDetailsDialogComponent,
            {
                ariaLabelledBy: titleId,
                data: {
                    title,
                    titleId,
                    created_by: resource.created_by,
                    created_at: resource.created_at,
                    last_edited_by: resource.last_edited_by,
                    last_edited_at: resource.last_edited_at,
                },
            }
        );
    }
}
