import { Dialog, DialogRef } from '@angular/cdk/dialog';
import { inject, Injectable } from '@angular/core';

import {
    AuthorshipDetailsDialogComponent,
    AuthorshipDetailsDialogData,
    AuthorshipDetailsExtraContent,
    AuthorshipDetailsSource,
} from './authorship-details-dialog.component';

@Injectable({
    providedIn: 'root',
})
export class AuthorshipDetailsDialogService {
    private readonly dialog = inject(Dialog);
    private openedCount = 0;

    /**
     * Shows who created and who last edited `resource` under the given heading.
     *
     * Pass `restoreFocusTo` when the dialog is opened from a menu: the dialog closes back to that
     * element (typically the menu trigger) instead of to whatever was focused when it opened, which
     * for a menu is an item destroyed with the menu. Focus moves there only on close, so a trigger
     * that is disabled now but enabled by then still gets it; if it is still disabled, focus falls
     * back to the document body. Omit it to keep the default (the element focused on open).
     *
     * Pass `extraContent` to show resource-specific details below the authorship block.
     */
    open<C>(
        title: string,
        resource: AuthorshipDetailsSource,
        restoreFocusTo?: HTMLElement,
        extraContent?: AuthorshipDetailsExtraContent<C>
    ): DialogRef<void, AuthorshipDetailsDialogComponent> {
        const titleId = `authorship-details-dialog-title-${++this.openedCount}`;
        // Only the authorship fields travel into the dialog, never the whole resource.
        return this.dialog.open<void, AuthorshipDetailsDialogData, AuthorshipDetailsDialogComponent>(
            AuthorshipDetailsDialogComponent,
            {
                ariaLabelledBy: titleId,
                restoreFocus: restoreFocusTo ?? true,
                data: {
                    title,
                    titleId,
                    created_by: resource.created_by,
                    created_at: resource.created_at,
                    last_edited_by: resource.last_edited_by,
                    last_edited_at: resource.last_edited_at,
                    ...(extraContent ? { extraContent } : {}),
                },
            }
        );
    }
}
