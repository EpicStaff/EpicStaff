import { Dialog, DialogRef } from '@angular/cdk/dialog';
import { inject, Injectable } from '@angular/core';

import { ABOUT_DIALOG_TITLE_ID, AboutDialogComponent } from '../components/about-dialog/about-dialog.component';

/** Opens the About dialog, so every place that shows the build (sidebar, Help menu) opens it the same way. */
@Injectable({ providedIn: 'root' })
export class AboutDialogService {
    private readonly dialog = inject(Dialog);

    open(): DialogRef<void, AboutDialogComponent> {
        return this.dialog.open<void, unknown, AboutDialogComponent>(AboutDialogComponent, {
            ariaLabelledBy: ABOUT_DIALOG_TITLE_ID,
            autoFocus: false,
        });
    }
}
